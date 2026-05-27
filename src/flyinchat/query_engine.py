import asyncio
import json
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .api_client import stream_chat_completion
from .compact import CompactionEngine, CompactionPolicy
from .message_utils import message_to_api_format, sanitize_api_messages
from .prompt_assembler import assemble_system_prompt
from .models import LLMChannel, LLMModel, TurnResult
from .paths import AppPaths
from .storage import (
    add_message_with_turn,
    get_conversation,
    get_primary_llm_model,
    increment_turn,
    list_active_messages,
    list_messages,
    update_conversation_usage,
)
from .tools.core import PERMISSION_REQUIRED, ToolContext, ToolExecutor, ToolRegistry, ToolResult
from .tools.permission_request import (
    PermissionRequest,
    PermissionRequestStore,
    RequestStatus,
    sanitize_args,
)

logger = logging.getLogger("flyinchat.query_engine")


@dataclass(frozen=True)
class TurnEvent:
    turn_id: str
    event_type: str  # "thinking" | "text" | "tool_use" | "tool_result" | "turn_start" | "turn_end" | "error" | "compact_start" | "compact_end"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryEngineConfig:
    paths: AppPaths
    conversation_id: str
    max_tool_rounds: int = 10
    max_context_retries: int = 1
    enable_auto_compact: bool = True


class QueryEngine:
    def __init__(self, config: QueryEngineConfig) -> None:
        self.config = config
        self.mode: str = "normal"
        self._tool_registry: ToolRegistry | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_context: ToolContext | None = None
        self._permission_store = PermissionRequestStore()
        self._pending_permissions: dict[str, asyncio.Future[str]] = {}
        self._cancel_event = asyncio.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def configure_tools(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        context: ToolContext,
    ) -> None:
        self._tool_registry = registry
        self._tool_executor = executor
        self._tool_context = context

    @property
    def permission_store(self) -> PermissionRequestStore:
        return self._permission_store

    async def submit_message(
        self,
        user_content: str,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
        *,
        user_message_persisted: bool = False,
    ) -> TurnResult:
        t_start = time.time()
        turn_number = increment_turn(
            self.config.paths.chat_path, conversation_id=self.config.conversation_id
        )
        turn_id = f"turn_{turn_number}_{self.config.conversation_id[:8]}"

        if not user_message_persisted:
            add_message_with_turn(
                self.config.paths.chat_path,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="user",
                subtype="normal",
                content=user_content,
            )

        await self._emit(on_event, TurnEvent(turn_id, "turn_start", {"turn_number": turn_number}))

        primary = get_primary_llm_model(self.config.paths.config_path)
        if primary is None:
            err_msg = "No model configured. Add one with /api, then /model."
            await self._emit(
                on_event,
                TurnEvent(turn_id, "error", {"message": err_msg}),
            )
            logger.warning("submit_message no model configured", extra={"turn_id": turn_id})
            return TurnResult(
                turn_id=turn_id,
                status="error",
                error=err_msg,
            )

        channel, model = primary
        try:
            result = await self._run_turn(turn_id, channel, model, on_event)
        except Exception as exc:
            logger.exception("submit_message unhandled error", extra={"turn_id": turn_id})
            await self._emit(
                on_event,
                TurnEvent(turn_id, "error", {"message": str(exc)}),
            )
            return TurnResult(
                turn_id=turn_id,
                status="error",
                error=str(exc),
                tool_rounds=0,
            )

        elapsed_ms = int((time.time() - t_start) * 1000)
        logger.info(
            "turn complete",
            extra={
                "turn_id": turn_id,
                "status": result.status,
                "tool_rounds": result.tool_rounds,
                "elapsed_ms": elapsed_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        return result

    async def _run_turn(
        self,
        turn_id: str,
        channel: LLMChannel,
        model: LLMModel,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        active_messages = list_active_messages(
            self.config.paths.chat_path, conversation_id=self.config.conversation_id
        )
        api_messages: list[dict] = [
            formatted
            for msg in active_messages
            if (formatted := message_to_api_format(msg)) is not None
        ]
        api_messages = sanitize_api_messages(api_messages)

        # ── Assemble and inject system prompt ──
        compact_text = _extract_compact_summary(api_messages)
        api_messages = [m for m in api_messages if m.get("role") != "system"]
        system_prompt = assemble_system_prompt(mode=self.mode, compact_summary=compact_text)
        api_messages.insert(0, {"role": "system", "content": system_prompt})

        tool_list = (
            list(self._tool_registry.tools) if self._tool_registry else None
        )

        if self.config.enable_auto_compact:
            policy = CompactionPolicy.from_model(model)
            engine = CompactionEngine(
                self.config.paths.chat_path, self.config.conversation_id
            )
            await self._emit(
                on_event, TurnEvent(turn_id, "compact_start", {"strategy": "preflight"})
            )
            compact_result = await engine.compact_if_needed_async(
                active_messages, api_messages, policy, force=False,
                model=model, channel=channel,
            )
            if compact_result.applied:
                active_messages = list(compact_result.messages)
                api_messages = sanitize_api_messages([
                    formatted
                    for msg in active_messages
                    if (formatted := message_to_api_format(msg)) is not None
                ])
                logger.info(
                    "preflight compact applied",
                    extra={
                        "turn_id": turn_id,
                        "strategy": compact_result.strategy,
                        "tokens_before": compact_result.tokens_before,
                        "tokens_after": compact_result.tokens_after,
                    },
                )
            await self._emit(
                on_event,
                TurnEvent(
                    turn_id,
                    "compact_end",
                    {"applied": compact_result.applied, "strategy": compact_result.strategy},
                ),
            )

        max_rounds = self.config.max_tool_rounds
        compact_retry_remaining = self.config.max_context_retries
        total_input_tokens = 0
        total_output_tokens = 0

        for round_num in range(max_rounds):
            if self._cancel_event.is_set():
                if round_num == 0:
                    add_message_with_turn(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="interrupted",
                        content="[Interrupted]",
                    )
                await self._emit(
                    on_event,
                    TurnEvent(turn_id, "turn_end", {"cancelled": True}),
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="cancelled",
                    tool_rounds=round_num,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            text_content = ""
            thinking_blocks: list[dict] = []
            tool_uses: list[dict] = []
            usage_info: dict = {}

            try:
                async for event in stream_chat_completion(
                    channel, model, api_messages, usage_info, tool_list
                ):
                    if self._cancel_event.is_set():
                        break
                    if event["type"] == "thinking":
                        thinking_blocks.append(event)
                        preview = (
                            event["thinking"][:200] + "..."
                            if len(event["thinking"]) > 200
                            else event["thinking"]
                        )
                        await self._emit(
                            on_event,
                            TurnEvent(
                                turn_id,
                                "thinking",
                                {"content": event["thinking"], "preview": preview},
                            ),
                        )
                    elif event["type"] == "reasoning":
                        thinking_blocks.append(
                            {"thinking": event["content"], "signature": ""}
                        )
                        preview = (
                            event["content"][:200] + "..."
                            if len(event["content"]) > 200
                            else event["content"]
                        )
                        await self._emit(
                            on_event,
                            TurnEvent(
                                turn_id,
                                "thinking",
                                {"content": event["content"], "preview": preview},
                            ),
                        )
                    elif event["type"] == "text":
                        text_content += event["content"]
                        await self._emit(
                            on_event,
                            TurnEvent(
                                turn_id, "text", {"content": event["content"]}
                            ),
                        )
                    elif event["type"] == "tool_use":
                        tool_uses.append(event)
                        await self._emit(
                            on_event,
                            TurnEvent(
                                turn_id,
                                "tool_use",
                                {
                                    "name": event["name"],
                                    "id": event["id"],
                                    "input": event["input"],
                                },
                            ),
                        )
            except Exception as error:
                error_str = str(error)
                if compact_retry_remaining > 0 and (
                    "context_length_exceeded" in error_str
                    or "413" in error_str
                    or "too long" in error_str.lower()
                    or "maximum context length" in error_str.lower()
                ):
                    compact_retry_remaining -= 1
                    logger.warning(
                        "context length exceeded, retrying with reactive compact",
                        extra={"turn_id": turn_id, "round": round_num, "error": error_str},
                    )
                    await self._emit(
                        on_event,
                        TurnEvent(
                            turn_id,
                            "compact_start",
                            {"strategy": "reactive"},
                        ),
                    )
                    all_messages = list_messages(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                    )
                    reactive_engine = CompactionEngine(
                        self.config.paths.chat_path, self.config.conversation_id
                    )
                    policy = CompactionPolicy.from_model(model)
                    reactive_result = await reactive_engine.reactive_compact(
                        all_messages, api_messages, policy, model, channel,
                        reason=error_str,
                    )
                    if reactive_result.applied:
                        active_messages = list(reactive_result.messages)
                        api_messages[:] = sanitize_api_messages([
                            formatted
                            for msg in active_messages
                            if (formatted := message_to_api_format(msg)) is not None
                        ])
                        await self._emit(
                            on_event,
                            TurnEvent(
                                turn_id,
                                "compact_end",
                                {"applied": True, "strategy": "reactive"},
                            ),
                        )
                        continue
                    await self._emit(
                        on_event,
                        TurnEvent(
                            turn_id,
                            "compact_end",
                            {"applied": False, "strategy": "reactive"},
                        ),
                    )
                await self._emit(
                    on_event,
                    TurnEvent(turn_id, "error", {"message": error_str}),
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="error",
                    error=error_str,
                    tool_rounds=round_num,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )
            finally:
                if channel.provider_type == "anthropic":
                    total_output_tokens += usage_info.get("output_tokens", 0)
                    total_input_tokens = usage_info.get("input_tokens", 0)
                else:
                    total_output_tokens += usage_info.get("completion_tokens", 0)
                    total_input_tokens = usage_info.get("prompt_tokens", 0)
                update_conversation_usage(
                    self.config.paths.chat_path,
                    conversation_id=self.config.conversation_id,
                    total_output_tokens=total_output_tokens,
                    last_input_tokens=total_input_tokens,
                )

            if self._cancel_event.is_set():
                if text_content:
                    if thinking_blocks:
                        assistant_content = []
                        for th in thinking_blocks:
                            assistant_content.append({
                                "type": "thinking",
                                "thinking": th["thinking"],
                                "signature": th.get("signature", ""),
                            })
                        assistant_content.append({"type": "text", "text": text_content})
                        content = json.dumps(assistant_content)
                    else:
                        content = text_content
                    add_message_with_turn(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="normal",
                        content=content,
                    )
                elif round_num == 0:
                    add_message_with_turn(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="interrupted",
                        content="[Interrupted]",
                    )
                await self._emit(
                    on_event,
                    TurnEvent(turn_id, "turn_end", {"cancelled": True}),
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="cancelled",
                    tool_rounds=round_num,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            if not tool_uses:
                if text_content:
                    if thinking_blocks:
                        assistant_content: list[dict] = []
                        for th in thinking_blocks:
                            assistant_content.append({
                                "type": "thinking",
                                "thinking": th["thinking"],
                                "signature": th.get("signature", ""),
                            })
                        assistant_content.append({"type": "text", "text": text_content})
                        content = json.dumps(assistant_content)
                    else:
                        content = text_content
                    add_message_with_turn(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="normal",
                        content=content,
                    )
                await self._emit(
                    on_event,
                    TurnEvent(
                        turn_id,
                        "turn_end",
                        {
                            "final_text": text_content,
                            "tool_rounds": round_num,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        },
                    ),
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="completed",
                    final_text=text_content,
                    tool_rounds=round_num,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            assistant_content: list[dict] = []
            for th in thinking_blocks:
                assistant_content.append({
                    "type": "thinking",
                    "thinking": th["thinking"],
                    "signature": th.get("signature", ""),
                })
            if text_content:
                assistant_content.append({"type": "text", "text": text_content})
            for tu in tool_uses:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                })

            add_message_with_turn(
                self.config.paths.chat_path,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="assistant",
                subtype="tool_call",
                content=json.dumps(assistant_content),
            )
            api_messages.append({"role": "assistant", "content": assistant_content})

            for tu in tool_uses:
                tool_result = await self._execute_tool(
                    turn_id, tu["name"], tu["input"], tu["id"], on_event
                )
                api_messages.append({
                    "role": "tool",
                    "tool_use_id": tu["id"],
                    "content": tool_result["content"],
                })
                await self._emit(
                    on_event,
                    TurnEvent(
                        turn_id,
                        "tool_result",
                        {
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "ok": tool_result.get("ok", False),
                            "content": tool_result.get("content", ""),
                        },
                    ),
                )

            if self._cancel_event.is_set():
                await self._emit(
                    on_event,
                    TurnEvent(turn_id, "turn_end", {"cancelled": True}),
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="cancelled",
                    tool_rounds=round_num + 1,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            if round_num + 1 >= max_rounds:
                logger.warning(
                    "max tool rounds reached",
                    extra={"turn_id": turn_id, "max_rounds": max_rounds},
                )
                return TurnResult(
                    turn_id=turn_id,
                    status="max_rounds",
                    tool_rounds=max_rounds,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

        return TurnResult(
            turn_id=turn_id,
            status="max_rounds",
            tool_rounds=max_rounds,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    async def _execute_tool(
        self,
        turn_id: str,
        tool_name: str,
        tool_input: dict,
        tool_use_id: str,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
    ) -> dict:
        if self._tool_executor is None or self._tool_context is None:
            result_text = "Tool system not initialized"
            add_message_with_turn(
                self.config.paths.chat_path,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="tool",
                subtype="tool_result",
                content=json.dumps({"tool_use_id": tool_use_id, "content": result_text}),
                tool_call_id=tool_use_id,
                meta=json.dumps({"error_code": "TOOL_NOT_INITIALIZED"}),
            )
            return {"ok": False, "content": result_text, "tool_use_id": tool_use_id}

        logger.info(
            "executing tool",
            extra={"turn_id": turn_id, "tool_name": tool_name, "tool_use_id": tool_use_id},
        )
        result = self._tool_executor.execute(tool_name, tool_input, self._tool_context)

        if result.error_code == PERMISSION_REQUIRED:
            return await self._handle_permission_required(
                turn_id, tool_name, tool_input, tool_use_id, result, on_event
            )

        return self._persist_tool_result(turn_id, tool_name, tool_use_id, result)

    async def _handle_permission_required(
        self,
        turn_id: str,
        tool_name: str,
        tool_input: dict,
        tool_use_id: str,
        execute_result: Any,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
    ) -> dict:
        tool = self._tool_registry.get(tool_name)
        risk_level = getattr(tool, "risk_level", "medium")
        args_preview = sanitize_args(tool_input)

        request = PermissionRequest.create(
            session_id=self.config.conversation_id,
            turn_id=turn_id,
            tool_call_id=tool_use_id,
            tool_name=tool_name,
            args_preview=args_preview,
            risk_level=risk_level,
            reason=execute_result.content,
            timeout_seconds=120.0,
        )
        request = request.with_status(RequestStatus.PENDING_USER_APPROVAL)
        self._permission_store.save(request)

        self._write_permission_transcript(
            turn_id, "permission_request_created",
            request_id=request.request_id,
            tool_name=tool_name,
            args_preview=args_preview,
            risk_level=risk_level,
        )

        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_permissions[request.request_id] = future

        await self._emit(
            on_event,
            TurnEvent(
                turn_id,
                "permission_required",
                {
                    "request_id": request.request_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_use_id,
                    "tool_input": tool_input,
                    "args_preview": args_preview,
                    "risk_level": risk_level,
                    "reason": execute_result.content,
                    "expires_at": request.expires_at,
                },
            ),
        )

        remaining = max(request.expires_at - time.time(), 1.0)
        try:
            resolution = await asyncio.wait_for(future, timeout=remaining)
        except asyncio.TimeoutError:
            resolution = "timeout"

        del self._pending_permissions[request.request_id]

        if resolution == "approve":
            approved_req = self._permission_store.update_status(
                request.request_id, RequestStatus.APPROVED
            )
            self._write_permission_transcript(
                turn_id, "permission_request_resolved",
                request_id=request.request_id, resolution="approved",
            )
            logger.info(
                "permission approved, executing tool",
                extra={"request_id": request.request_id, "tool_name": tool_name},
            )
            exec_result = self._tool_executor.execute_approved(
                tool_name, tool_input, self._tool_context
            )
            if exec_result.ok:
                if approved_req:
                    self._permission_store.update_status(
                        request.request_id, RequestStatus.EXECUTED
                    )
                self._write_permission_transcript(
                    turn_id, "permission_effect_applied",
                    request_id=request.request_id, outcome="executed",
                )
            else:
                if approved_req:
                    self._permission_store.update_status(
                        request.request_id, RequestStatus.FAILED_AFTER_APPROVAL
                    )
                self._write_permission_transcript(
                    turn_id, "permission_effect_applied",
                    request_id=request.request_id,
                    outcome="failed",
                    error=exec_result.content,
                )
            return self._persist_tool_result(turn_id, tool_name, tool_use_id, exec_result)

        if resolution == "always_approve":
            cmd = tool_input.get("command", "").strip()
            if cmd and self._tool_executor is not None:
                try:
                    parts = shlex.split(cmd)
                except ValueError:
                    parts = cmd.split()
                if parts:
                    pattern = _extract_command_pattern(parts)
                    self._tool_executor.add_command_to_allowlist(pattern)
            approved_req = self._permission_store.update_status(
                request.request_id, RequestStatus.APPROVED
            )
            self._write_permission_transcript(
                turn_id, "permission_request_resolved",
                request_id=request.request_id, resolution="always_approved",
            )
            logger.info(
                "permission always-approved, executing tool",
                extra={"request_id": request.request_id, "tool_name": tool_name},
            )
            exec_result = self._tool_executor.execute_approved(
                tool_name, tool_input, self._tool_context
            )
            if exec_result.ok:
                if approved_req:
                    self._permission_store.update_status(
                        request.request_id, RequestStatus.EXECUTED
                    )
                self._write_permission_transcript(
                    turn_id, "permission_effect_applied",
                    request_id=request.request_id, outcome="executed",
                )
            else:
                if approved_req:
                    self._permission_store.update_status(
                        request.request_id, RequestStatus.FAILED_AFTER_APPROVAL
                    )
                self._write_permission_transcript(
                    turn_id, "permission_effect_applied",
                    request_id=request.request_id,
                    outcome="failed",
                    error=exec_result.content,
                )
            return self._persist_tool_result(turn_id, tool_name, tool_use_id, exec_result)

        if resolution == "deny":
            self._permission_store.update_status(
                request.request_id, RequestStatus.DENIED
            )
            self._write_permission_transcript(
                turn_id, "permission_request_resolved",
                request_id=request.request_id, resolution="denied",
            )
            deny_result = ToolResult(
                ok=False,
                content=f"User denied permission for {tool_name}",
                error_code="PERMISSION_DENIED",
            )
            return self._persist_tool_result(turn_id, tool_name, tool_use_id, deny_result)

        # timeout
        self._permission_store.update_status(
            request.request_id, RequestStatus.EXPIRED
        )
        self._write_permission_transcript(
            turn_id, "permission_request_resolved",
            request_id=request.request_id, resolution="timeout",
        )
        timeout_result = ToolResult(
            ok=False,
            content=f"Permission request timed out for {tool_name}",
            error_code="PERMISSION_DENIED",
        )
        return self._persist_tool_result(turn_id, tool_name, tool_use_id, timeout_result)

    def _persist_tool_result(
        self, turn_id: str, tool_name: str, tool_use_id: str, result: Any
    ) -> dict:
        add_message_with_turn(
            self.config.paths.chat_path,
            conversation_id=self.config.conversation_id,
            turn_id=turn_id,
            role="tool",
            subtype="tool_result",
            content=json.dumps({"tool_use_id": tool_use_id, "content": result.content}),
            tool_call_id=tool_use_id,
            meta=json.dumps({
                "tool_name": tool_name,
                "ok": result.ok,
                "error_code": result.error_code,
                "elapsed_ms": result.meta.get("elapsed_ms", 0),
                "data": result.data,
            }),
        )

        logger.info(
            "tool executed",
            extra={
                "turn_id": turn_id,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "ok": result.ok,
                "error_code": result.error_code or "",
                "elapsed_ms": result.meta.get("elapsed_ms", 0),
            },
        )
        return {
            "ok": result.ok,
            "content": result.content,
            "tool_use_id": tool_use_id,
        }

    def _write_permission_transcript(
        self, turn_id: str, event_type: str, **kwargs: Any
    ) -> None:
        transcript_entry = json.dumps({
            "event": event_type,
            **kwargs,
        })
        add_message_with_turn(
            self.config.paths.chat_path,
            conversation_id=self.config.conversation_id,
            turn_id=turn_id,
            role="system",
            subtype="permission_event",
            content=transcript_entry,
        )

    def resolve_permission(self, request_id: str, resolution: str) -> bool:
        future = self._pending_permissions.get(request_id)
        if future is None or future.done():
            logger.warning(
                "no pending permission to resolve",
                extra={"request_id": request_id, "resolution": resolution},
            )
            return False
        future.set_result(resolution)
        return True

    async def _emit(
        self,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None,
        event: TurnEvent,
    ) -> None:
        if on_event is not None:
            await on_event(event)

    def get_session_state(self) -> dict:
        conv = get_conversation(
            self.config.paths.chat_path,
            conversation_id=self.config.conversation_id,
        )
        if conv is None:
            return {}
        return {
            "turn_count": conv.current_turn,
            "total_output_tokens": conv.total_output_tokens,
            "last_input_tokens": conv.last_input_tokens,
            "status": conv.status,
        }


def _extract_compact_summary(api_messages: list[dict]) -> str | None:
    """Extract compact summary text from system messages in the API message list."""
    parts: list[str] = []
    for msg in api_messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if content:
                parts.append(content)
    return "\n\n".join(parts) if parts else None


def _extract_command_pattern(parts: list[str]) -> str:
    if len(parts) >= 2 and parts[0] == "git":
        return f"{parts[0]} {parts[1]}"
    return parts[0]
