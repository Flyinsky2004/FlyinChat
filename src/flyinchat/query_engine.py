import asyncio
import json
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import uuid4

from .api_client import stream_chat_completion
from .compact import CompactionEngine, CompactionPolicy, TokenEstimator
from .message_utils import message_to_api_format, sanitize_api_messages
from .prompt_assembler import assemble_system_prompt
from .models import LLMChannel, LLMModel, Message, TurnResult
from .skills import CompiledSkill, SkillCompiler, SkillRegistry, SkillResolver
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
from .tools.core import PERMISSION_REQUIRED, USER_INPUT_REQUIRED, ToolContext, ToolExecutor, ToolRegistry, ToolResult
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
    max_turns: int | None = None
    max_context_retries: int = 1
    enable_auto_compact: bool = True
    skill_registry: SkillRegistry | None = None
    enable_auto_continue: bool = True
    max_auto_continues: int = 3
    auto_continue_turns: int = 10


class QueryEngine:
    def __init__(self, config: QueryEngineConfig) -> None:
        self.config = config
        self.mode: str = "normal"
        self._tool_registry: ToolRegistry | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_context: ToolContext | None = None
        self._permission_store = PermissionRequestStore()
        self._pending_permissions: dict[str, asyncio.Future[str]] = {}
        self._pending_user_inputs: dict[str, asyncio.Future[dict]] = {}
        self._cancel_event = asyncio.Event()
        self._skill_resolver = SkillResolver()
        self._skill_compiler = SkillCompiler()

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
                "num_turns": result.num_turns,
                "max_turns": result.max_turns,
                "terminal_reason": result.terminal_reason,
                "last_tool_error": result.last_tool_error,
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
        compiled_skill = self._resolve_turn_skills(turn_id, active_messages)
        api_messages: list[dict] = [
            formatted
            for msg in active_messages
            if (formatted := message_to_api_format(msg)) is not None
        ]
        api_messages = sanitize_api_messages(api_messages)

        # ── Assemble and inject system prompt ──
        compact_text = _extract_compact_summary(api_messages)
        api_messages = [m for m in api_messages if m.get("role") != "system"]
        system_prompt = assemble_system_prompt(
            mode=self.mode,
            compact_summary=compact_text,
            skill_injection=compiled_skill.planning_injection if compiled_skill else None,
        )
        api_messages.insert(0, {"role": "system", "content": system_prompt})
        if compiled_skill and compiled_skill.runtime_state.applied_skills:
            await self._emit(
                on_event,
                TurnEvent(
                    turn_id,
                    "skill_resolved",
                    {
                        "applied_skills": list(compiled_skill.runtime_state.applied_skills),
                        "active_phase": compiled_skill.runtime_state.active_phase,
                        "guards_applied": len(compiled_skill.runtime_guards),
                    },
                ),
            )

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

        base_max_turns = max(1, self.config.max_turns or self.config.max_tool_rounds)
        current_max_turns = base_max_turns
        compact_retry_remaining = self.config.max_context_retries
        total_input_tokens = 0
        total_output_tokens = 0
        num_turns = 0
        tool_rounds = 0
        auto_continue_count = 0
        incomplete_continue_count = 0
        max_incomplete_continues = 3
        pending_tool_results = False
        finalization_pass = False
        last_tool_error: str | None = None

        def assistant_blocks(thinking_blocks: list[dict], text_content: str) -> list[dict]:
            blocks = [
                {
                    "type": "thinking",
                    "thinking": th["thinking"],
                    "signature": th.get("signature", ""),
                }
                for th in thinking_blocks
            ]
            if text_content:
                blocks.append({"type": "text", "text": text_content})
            return blocks

        def persist_normal_message(thinking_blocks: list[dict], text_content: str) -> None:
            if not thinking_blocks and not text_content:
                return
            content = (
                json.dumps(assistant_blocks(thinking_blocks, text_content))
                if thinking_blocks
                else text_content
            )
            add_message_with_turn(
                self.config.paths.chat_path,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="assistant",
                subtype="normal",
                content=content,
            )

        async def finish(
            status: str,
            terminal_reason: str,
            *,
            final_text: str = "",
            error: str | None = None,
            cancelled: bool = False,
        ) -> TurnResult:
            data = {
                "status": status,
                "terminal_reason": terminal_reason,
                "final_text": final_text,
                "tool_rounds": tool_rounds,
                "num_turns": num_turns,
                "base_max_turns": base_max_turns,
                "max_turns": current_max_turns,
                "current_max_turns": current_max_turns,
                "auto_continue_count": auto_continue_count,
                "last_tool_error": last_tool_error,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            }
            if cancelled:
                data["cancelled"] = True
            await self._emit(on_event, TurnEvent(turn_id, "turn_end", data))
            return TurnResult(
                turn_id=turn_id,
                status=status,
                final_text=final_text,
                tool_rounds=tool_rounds,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                error=error,
                num_turns=num_turns,
                max_turns=current_max_turns,
                terminal_reason=terminal_reason,
                last_tool_error=last_tool_error,
            )

        while True:
            if self._cancel_event.is_set():
                if num_turns == 0:
                    add_message_with_turn(
                        self.config.paths.chat_path,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="interrupted",
                        content="[Interrupted]",
                    )
                return await finish("cancelled", "cancelled", cancelled=True)

            if num_turns >= current_max_turns:
                can_auto_continue = (
                    self.config.enable_auto_continue
                    and auto_continue_count < self.config.max_auto_continues
                    and not self._pending_permissions
                    and not self._pending_user_inputs
                    and not self._cancel_event.is_set()
                )
                if can_auto_continue:
                    auto_continue_count += 1
                    additional_turns = max(1, self.config.auto_continue_turns)
                    current_max_turns += additional_turns
                    api_messages.append({
                        "role": "user",
                        "content": (
                            "Continue the user's original task from the latest tool results. "
                            "Do not repeat completed work. If you have enough information, "
                            "provide the final answer. Use more tools only when necessary and "
                            "continue to follow the existing permission requirements."
                        ),
                    })
                    logger.info(
                        "auto-continuing after turn budget reached",
                        extra={
                            "turn_id": turn_id,
                            "num_turns": num_turns,
                            "base_max_turns": base_max_turns,
                            "max_turns": current_max_turns,
                            "current_max_turns": current_max_turns,
                            "auto_continue_count": auto_continue_count,
                        },
                    )
                    await self._emit(
                        on_event,
                        TurnEvent(
                            turn_id,
                            "auto_continue",
                            {
                                "count": auto_continue_count,
                                "additional_turns": additional_turns,
                                "num_turns": num_turns,
                                "base_max_turns": base_max_turns,
                                "max_turns": current_max_turns,
                                "current_max_turns": current_max_turns,
                            },
                        ),
                    )
                    continue

                if pending_tool_results and not finalization_pass:
                    finalization_pass = True
                    api_messages.append({
                        "role": "user",
                        "content": (
                            "The automatic turn budget is exhausted. Do not call tools. "
                            "Summarize what has been completed, explain the latest tool result, "
                            "name any blocker, and list the remaining work clearly."
                        ),
                    })
                else:
                    logger.warning(
                        "max turns reached",
                        extra={
                            "turn_id": turn_id,
                            "base_max_turns": base_max_turns,
                            "max_turns": current_max_turns,
                            "num_turns": num_turns,
                            "tool_rounds": tool_rounds,
                            "terminal_reason": "max_turns",
                            "last_tool_error": last_tool_error,
                        },
                    )
                    return await finish("max_rounds", "max_turns")

            text_content = ""
            thinking_blocks: list[dict] = []
            tool_uses: list[dict] = []
            usage_info: dict = {}
            had_incomplete_tool_call = False
            tools_for_call = [] if finalization_pass else tool_list

            try:
                async for event in stream_chat_completion(
                    channel, model, api_messages, usage_info, tools_for_call
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
                            TurnEvent(turn_id, "text", {"content": event["content"]}),
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
                    elif event["type"] == "incomplete_tool_call":
                        had_incomplete_tool_call = True
                        logger.info(
                            "detected incomplete tool call, will auto-continue",
                            extra={"turn_id": turn_id, "tool_name": event.get("name")},
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
                        extra={"turn_id": turn_id, "round": num_turns, "error": error_str},
                    )
                    await self._emit(
                        on_event,
                        TurnEvent(turn_id, "compact_start", {"strategy": "reactive"}),
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
                return await finish("error", "error", error=error_str)
            finally:
                if channel.provider_type == "anthropic":
                    total_output_tokens += usage_info.get("output_tokens", 0)
                    total_input_tokens = usage_info.get("input_tokens", 0)
                else:
                    total_output_tokens += usage_info.get("completion_tokens", 0)
                    total_input_tokens = usage_info.get("prompt_tokens", 0)
                # Fallback: some providers (e.g. DeepSeek) may not report
                # input_tokens in their Anthropic-compatible SSE events.
                # Estimate from the messages we sent to avoid showing "↑0".
                if total_input_tokens == 0 and api_messages:
                    total_input_tokens = TokenEstimator().estimate_api_messages(api_messages)
                update_conversation_usage(
                    self.config.paths.chat_path,
                    conversation_id=self.config.conversation_id,
                    total_output_tokens=total_output_tokens,
                    last_input_tokens=total_input_tokens,
                )

            num_turns += 1
            pending_tool_results = False

            if self._cancel_event.is_set():
                persist_normal_message(thinking_blocks, text_content)
                return await finish("cancelled", "cancelled", cancelled=True)

            if finalization_pass and tool_uses:
                reason = (
                    "auto_continue_limit_reached"
                    if self.config.enable_auto_continue
                    and auto_continue_count >= self.config.max_auto_continues
                    else "max_turns"
                )
                return await finish("max_rounds", reason)

            if not tool_uses:
                if (
                    had_incomplete_tool_call
                    and incomplete_continue_count < max_incomplete_continues
                ):
                    incomplete_continue_count += 1
                    logger.info(
                        "auto-continuing after incomplete tool call",
                        extra={
                            "turn_id": turn_id,
                            "round": num_turns,
                            "auto_continue_count": incomplete_continue_count,
                            "tool_name": "unknown",
                        },
                    )
                    persist_normal_message(thinking_blocks, text_content)
                    api_messages.append({
                        "role": "assistant",
                        "content": assistant_blocks(thinking_blocks, text_content)
                        if thinking_blocks
                        else text_content,
                    })
                    api_messages.append({
                        "role": "user",
                        "content": (
                            "Your last response was cut off mid-stream — the tool call JSON was incomplete. "
                            "Please continue exactly where you left off and complete the tool call you started."
                        ),
                    })
                    continue

                if had_incomplete_tool_call:
                    persist_normal_message(thinking_blocks, text_content)
                    return await finish(
                        "max_rounds",
                        "incomplete_tool_call_limit_reached",
                        final_text=text_content,
                    )

                persist_normal_message(thinking_blocks, text_content)
                if finalization_pass:
                    reason = (
                        "auto_continue_limit_reached"
                        if self.config.enable_auto_continue
                        and auto_continue_count >= self.config.max_auto_continues
                        else "max_turns"
                    )
                    return await finish(
                        "max_rounds",
                        reason,
                        final_text=text_content,
                    )
                return await finish(
                    "completed",
                    "completed",
                    final_text=text_content,
                )

            assistant_content = assistant_blocks(thinking_blocks, text_content)
            assistant_content.extend(
                {
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                }
                for tu in tool_uses
            )

            add_message_with_turn(
                self.config.paths.chat_path,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="assistant",
                subtype="tool_call",
                content=json.dumps(assistant_content),
            )
            api_messages.append({"role": "assistant", "content": assistant_content})
            tool_rounds += 1

            for tu in tool_uses:
                tool_result = await self._execute_tool(
                    turn_id, tu["name"], tu["input"], tu["id"], on_event
                )
                if tool_result.get("ok", False):
                    last_tool_error = None
                else:
                    last_tool_error = tool_result.get("error_code") or "TOOL_ERROR"
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
                            "error_code": tool_result.get("error_code"),
                        },
                    ),
                )

            pending_tool_results = True

    def _resolve_turn_skills(
        self,
        turn_id: str,
        active_messages: list[Message],
    ) -> CompiledSkill | None:
        registry = self.config.skill_registry
        if registry is None:
            if self._tool_context is not None:
                self._tool_context.turn_state = {
                    key: value
                    for key, value in self._tool_context.turn_state.items()
                    if key not in {"runtime_guards", "skill_runtime_state"}
                }
            return None

        query = _latest_user_content(active_messages)
        catalog = registry.refresh()
        decision = self._skill_resolver.resolve(query, catalog)
        compiled = self._skill_compiler.compile(decision)
        if self._tool_context is not None:
            self._tool_context.turn_state = {
                **self._tool_context.turn_state,
                "runtime_guards": compiled.runtime_guards,
                "skill_runtime_state": compiled.runtime_state,
            }
        self._write_skill_transcript(turn_id, decision, compiled)
        return compiled if decision.selected else None

    def _write_skill_transcript(
        self,
        turn_id: str,
        decision: Any,
        compiled: CompiledSkill,
    ) -> None:
        content = json.dumps({
            "event": "skill.resolve.complete",
            "applied_skills": list(decision.applied_refs),
            "rejected": [
                {"name": item.name, "reason": item.reason, "score": item.score}
                for item in decision.rejected
            ],
            "confidence": decision.confidence,
            "skill_decision_reason": decision.reason,
            "active_phase": compiled.runtime_state.active_phase,
            "guards_applied": [
                {
                    "guard_id": guard.guard_id,
                    "skill_name": guard.skill_name,
                    "guard_type": guard.guard_type,
                    "action": guard.action,
                    "reason": guard.reason,
                }
                for guard in compiled.runtime_guards
            ],
        }, ensure_ascii=False)
        add_message_with_turn(
            self.config.paths.chat_path,
            conversation_id=self.config.conversation_id,
            turn_id=turn_id,
            role="system",
            subtype="skill_event",
            content=content,
        )
        logger.info(
            "skill resolved",
            extra={
                "turn_id": turn_id,
                "applied_skills": list(decision.applied_refs),
                "confidence": decision.confidence,
                "active_phase": compiled.runtime_state.active_phase,
                "guard_count": len(compiled.runtime_guards),
            },
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
            return {
                "ok": False,
                "content": result_text,
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "error_code": "TOOL_NOT_INITIALIZED",
            }

        logger.info(
            "executing tool",
            extra={"turn_id": turn_id, "tool_name": tool_name, "tool_use_id": tool_use_id},
        )
        result = await self._tool_executor.execute(tool_name, tool_input, self._tool_context)

        if result.error_code == PERMISSION_REQUIRED:
            return await self._handle_permission_required(
                turn_id, tool_name, tool_input, tool_use_id, result, on_event
            )

        if result.error_code == USER_INPUT_REQUIRED:
            return await self._handle_user_input_required(
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
            exec_result = await self._tool_executor.execute_approved(
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
            exec_result = await self._tool_executor.execute_approved(
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

    async def _handle_user_input_required(
        self,
        turn_id: str,
        tool_name: str,
        tool_input: dict,
        tool_use_id: str,
        execute_result: Any,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
    ) -> dict:
        questions = execute_result.meta.get("questions", [])
        user_input_id = str(uuid4())

        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending_user_inputs[user_input_id] = future

        await self._emit(
            on_event,
            TurnEvent(
                turn_id,
                "user_input_required",
                {
                    "request_id": user_input_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_use_id,
                    "questions": questions,
                },
            ),
        )

        try:
            answers = await asyncio.wait_for(future, timeout=120.0)
        except asyncio.TimeoutError:
            answers = {"_timeout": True}

        del self._pending_user_inputs[user_input_id]

        result = ToolResult(
            ok=True,
            content=json.dumps(answers, ensure_ascii=False),
        )
        return self._persist_tool_result(turn_id, tool_name, tool_use_id, result)

    def resolve_user_input(self, request_id: str, answers: dict) -> bool:
        future = self._pending_user_inputs.get(request_id)
        if future is None or future.done():
            logger.warning(
                "no pending user input to resolve",
                extra={"request_id": request_id},
            )
            return False
        future.set_result(answers)
        return True

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
                "skill_guard_id": result.meta.get("skill_guard_id"),
                "skill_name": result.meta.get("skill_name"),
                "guard_type": result.meta.get("guard_type"),
                "guard_reason": result.meta.get("guard_reason"),
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
            "tool_name": tool_name,
            "error_code": result.error_code,
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


def _latest_user_content(messages: list[Message]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return ""


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
