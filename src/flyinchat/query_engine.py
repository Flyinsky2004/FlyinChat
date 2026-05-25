import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .api_client import stream_chat_completion
from .compact import CompactionEngine, CompactionPolicy
from .message_utils import message_to_api_format
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
from .tools.core import ToolContext, ToolExecutor, ToolRegistry

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
        self._tool_registry: ToolRegistry | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_context: ToolContext | None = None

    def configure_tools(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        context: ToolContext,
    ) -> None:
        self._tool_registry = registry
        self._tool_executor = executor
        self._tool_context = context

    async def submit_message(
        self,
        user_content: str,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None = None,
        *,
        user_message_persisted: bool = False,
    ) -> TurnResult:
        t_start = time.time()
        turn_number = increment_turn(
            self.config.paths.chat_db, conversation_id=self.config.conversation_id
        )
        turn_id = f"turn_{turn_number}_{self.config.conversation_id[:8]}"

        if not user_message_persisted:
            add_message_with_turn(
                self.config.paths.chat_db,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="user",
                subtype="normal",
                content=user_content,
            )

        await self._emit(on_event, TurnEvent(turn_id, "turn_start", {"turn_number": turn_number}))

        primary = get_primary_llm_model(self.config.paths.config_db)
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
            self.config.paths.chat_db, conversation_id=self.config.conversation_id
        )
        api_messages: list[dict] = [
            formatted
            for msg in active_messages
            if (formatted := message_to_api_format(msg)) is not None
        ]

        tool_list = (
            list(self._tool_registry.tools) if self._tool_registry else None
        )

        if self.config.enable_auto_compact:
            policy = CompactionPolicy.from_model(model)
            engine = CompactionEngine(
                self.config.paths.chat_db, self.config.conversation_id
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
                api_messages = [
                    formatted
                    for msg in active_messages
                    if (formatted := message_to_api_format(msg)) is not None
                ]
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
            text_content = ""
            thinking_blocks: list[dict] = []
            tool_uses: list[dict] = []
            usage_info: dict = {}

            try:
                async for event in stream_chat_completion(
                    channel, model, api_messages, usage_info, tool_list
                ):
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
                        self.config.paths.chat_db,
                        conversation_id=self.config.conversation_id,
                    )
                    reactive_engine = CompactionEngine(
                        self.config.paths.chat_db, self.config.conversation_id
                    )
                    policy = CompactionPolicy.from_model(model)
                    reactive_result = await reactive_engine.reactive_compact(
                        all_messages, api_messages, policy, model, channel,
                        reason=error_str,
                    )
                    if reactive_result.applied:
                        active_messages = list(reactive_result.messages)
                        api_messages[:] = [
                            formatted
                            for msg in active_messages
                            if (formatted := message_to_api_format(msg)) is not None
                        ]
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
                    self.config.paths.chat_db,
                    conversation_id=self.config.conversation_id,
                    total_output_tokens=total_output_tokens,
                    last_input_tokens=total_input_tokens,
                )

            if not tool_uses:
                if text_content:
                    add_message_with_turn(
                        self.config.paths.chat_db,
                        conversation_id=self.config.conversation_id,
                        turn_id=turn_id,
                        role="assistant",
                        subtype="normal",
                        content=text_content,
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
                self.config.paths.chat_db,
                conversation_id=self.config.conversation_id,
                turn_id=turn_id,
                role="assistant",
                subtype="tool_call",
                content=json.dumps(assistant_content),
            )
            api_messages.append({"role": "assistant", "content": assistant_content})

            for tu in tool_uses:
                tool_result = self._execute_tool(
                    turn_id, tu["name"], tu["input"], tu["id"]
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

    def _execute_tool(
        self, turn_id: str, tool_name: str, tool_input: dict, tool_use_id: str
    ) -> dict:
        if self._tool_executor is None or self._tool_context is None:
            result_text = "Tool system not initialized"
            add_message_with_turn(
                self.config.paths.chat_db,
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

        add_message_with_turn(
            self.config.paths.chat_db,
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

    async def _emit(
        self,
        on_event: Callable[[TurnEvent], Awaitable[None]] | None,
        event: TurnEvent,
    ) -> None:
        if on_event is not None:
            await on_event(event)

    def get_session_state(self) -> dict:
        conv = get_conversation(
            self.config.paths.chat_db,
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
