from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from flyinchat.api_client import chat_completion
from flyinchat.i18n import I18nStore, TKey
from flyinchat.models import LLMChannel, LLMModel, Message
from flyinchat.storage import (
    add_message,
    list_messages,
    update_conversation_compacted_count,
    update_message_content,
)


@dataclass(frozen=True)
class CompactionOutput:
    applied: bool
    messages: tuple[Message, ...]
    boundary_message: Message | None = None
    tokens_before: int = 0
    tokens_after: int = 0
    strategy: str = ""


@dataclass(frozen=True)
class CompactMetadata:
    boundary_id: str
    strategy: str
    source_range_from: str
    source_range_to: str
    preserved_head_ids: tuple[str, ...]
    preserved_tail_id: str
    summary_msg_id: str
    tokens_before: int
    tokens_after: int


@dataclass(frozen=True)
class TokenEstimator:
    """Rough token count using chars/4 approximation."""

    def estimate(self, text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_messages(self, messages: Sequence[Message]) -> int:
        return sum(self.estimate(msg.content) for msg in messages)

    def estimate_api_messages(self, api_messages: Sequence[dict]) -> int:
        return sum(self.estimate(json.dumps(m, ensure_ascii=False)) for m in api_messages)


@dataclass(frozen=True)
class CompactionPolicy:
    context_window: int
    tool_result_budget_chars: int = 8_000
    soft_limit_ratio: float = 0.85
    preserve_turns: int = 4

    @property
    def soft_limit(self) -> int:
        return int(self.context_window * self.soft_limit_ratio)

    @property
    def hard_limit(self) -> int:
        return self.context_window

    @classmethod
    def from_model(cls, model: LLMModel) -> CompactionPolicy:
        return cls(context_window=model.context_window)


@dataclass
class CompactionEngine:
    _chat_db: Path
    _conversation_id: str
    _estimator: TokenEstimator = field(default_factory=TokenEstimator)
    _i18n: I18nStore = field(default_factory=I18nStore)

    def compact_if_needed(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        *,
        force: bool = False,
        model: LLMModel | None = None,
        channel: LLMChannel | None = None,
    ) -> CompactionOutput:
        estimated = self._estimator.estimate_messages(messages)

        if force or estimated > policy.soft_limit:
            result = self._apply_tool_result_budget(messages, api_messages, policy, estimated)
            if result.applied:
                return result

        if estimated > policy.hard_limit or (force and model is not None and channel is not None):
            if model is None or channel is None:
                return CompactionOutput(applied=False, messages=tuple(messages))
            return self._autocompact_sync(messages, api_messages, policy, model, channel, estimated)

        return CompactionOutput(applied=False, messages=tuple(messages), tokens_before=estimated)

    async def compact_if_needed_async(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        *,
        force: bool = False,
        model: LLMModel | None = None,
        channel: LLMChannel | None = None,
    ) -> CompactionOutput:
        """Async variant for use from @work methods on the event loop."""
        estimated = self._estimator.estimate_messages(messages)

        if force or estimated > policy.soft_limit:
            result = self._apply_tool_result_budget(messages, api_messages, policy, estimated)
            if result.applied:
                return result

        if estimated > policy.hard_limit or (force and model is not None and channel is not None):
            if model is None or channel is None:
                return CompactionOutput(applied=False, messages=tuple(messages))
            return await self._autocompact(messages, api_messages, policy, model, channel, estimated)

        return CompactionOutput(applied=False, messages=tuple(messages), tokens_before=estimated)

    def _autocompact_sync(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        model: LLMModel,
        channel: LLMChannel,
        tokens_before: int,
    ) -> CompactionOutput:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self._autocompact(messages, api_messages, policy, model, channel, tokens_before)
                )
            finally:
                loop.close()
        else:
            import concurrent.futures

            future = asyncio.run_coroutine_threadsafe(
                self._autocompact(messages, api_messages, policy, model, channel, tokens_before),
                loop,
            )
            return future.result()

    def _apply_tool_result_budget(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        tokens_before: int,
    ) -> CompactionOutput:
        truncated = 0
        for i, msg in enumerate(messages):
            try:
                parsed = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                continue

            if not (isinstance(parsed, dict) and "tool_use_id" in parsed):
                continue

            content = parsed.get("content", "")
            if not isinstance(content, str) or len(content) <= policy.tool_result_budget_chars:
                continue

            head = content[:2000]
            tail = content[-500:]
            truncated_chars = len(content) - 2000 - 500
            truncated_content = f"{head}\n...[truncated {truncated_chars} chars]...\n{tail}"
            parsed["content"] = truncated_content

            new_content = json.dumps(parsed)
            update_message_content(
                self._chat_db,
                message_id=msg.id,
                content=new_content,
            )
            if i < len(api_messages):
                api_messages[i]["content"] = truncated_content
            truncated += 1

        if truncated == 0:
            return CompactionOutput(
                applied=False, messages=tuple(messages), tokens_before=tokens_before
            )

        updated = list_messages(self._chat_db, conversation_id=self._conversation_id)
        tokens_after = self._estimator.estimate_messages(updated)
        return CompactionOutput(
            applied=True,
            messages=tuple(updated),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            strategy="tool_result_budget",
        )

    async def _autocompact(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        model: LLMModel,
        channel: LLMChannel,
        tokens_before: int,
    ) -> CompactionOutput:
        split_idx = self._find_split_index(messages, policy.preserve_turns)
        if split_idx <= 0:
            return CompactionOutput(
                applied=False, messages=tuple(messages), tokens_before=tokens_before
            )

        summarize_msgs = messages[:split_idx]
        preserved_msgs = messages[split_idx:]

        summary_text = await self._generate_summary(summarize_msgs, model, channel)

        summary_msg = add_message(
            self._chat_db,
            conversation_id=self._conversation_id,
            role="system",
            content=json.dumps({
                "type": "compact_summary",
                "summary": summary_text,
                "summarized_count": len(summarize_msgs),
            }),
        )

        metadata = CompactMetadata(
            boundary_id=str(uuid4()),
            strategy="autocompact_v1",
            source_range_from=summarize_msgs[0].id,
            source_range_to=summarize_msgs[-1].id,
            preserved_head_ids=tuple(m.id for m in preserved_msgs),
            preserved_tail_id=preserved_msgs[-1].id if preserved_msgs else "",
            summary_msg_id=summary_msg.id,
            tokens_before=tokens_before,
            tokens_after=0,
        )
        boundary_msg = add_message(
            self._chat_db,
            conversation_id=self._conversation_id,
            role="system",
            content=json.dumps({
                "type": "compact_boundary",
                "boundary_id": metadata.boundary_id,
                "strategy": metadata.strategy,
                "source_range_from": metadata.source_range_from,
                "source_range_to": metadata.source_range_to,
                "preserved_head_ids": list(metadata.preserved_head_ids),
                "preserved_tail_id": metadata.preserved_tail_id,
                "summary_msg_id": metadata.summary_msg_id,
                "tokens_before": metadata.tokens_before,
                "tokens_after": metadata.tokens_after,
            }),
        )

        update_conversation_compacted_count(
            self._chat_db,
            conversation_id=self._conversation_id,
            count=len(summarize_msgs),
        )

        updated = list_messages(self._chat_db, conversation_id=self._conversation_id)
        tokens_after = self._estimator.estimate_messages(updated)

        return CompactionOutput(
            applied=True,
            messages=tuple(updated),
            boundary_message=boundary_msg,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            strategy="autocompact_v1",
        )

    async def reactive_compact(
        self,
        messages: Sequence[Message],
        api_messages: list[dict],
        policy: CompactionPolicy,
        model: LLMModel,
        channel: LLMChannel,
        reason: str,
    ) -> CompactionOutput:
        aggressive_policy = CompactionPolicy(
            context_window=policy.context_window,
            tool_result_budget_chars=2_000,
            preserve_turns=1,
        )
        _ = self._apply_tool_result_budget(messages, api_messages, aggressive_policy, 0)
        updated = list_messages(self._chat_db, conversation_id=self._conversation_id)
        tokens_before = self._estimator.estimate_messages(updated)
        return await self._autocompact(
            updated, api_messages, aggressive_policy, model, channel, tokens_before
        )

    @staticmethod
    def _find_split_index(messages: Sequence[Message], preserve_turns: int) -> int:
        turn_count = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                turn_count += 1
                if turn_count >= preserve_turns:
                    return i
        return 0

    async def _generate_summary(
        self,
        messages: Sequence[Message],
        model: LLMModel,
        channel: LLMChannel,
    ) -> str:
        t = self._i18n.t
        role_labels = {
            "user": t(TKey.COMPACT_ROLE_USER),
            "assistant": t(TKey.COMPACT_ROLE_ASSISTANT),
            "tool": t(TKey.COMPACT_ROLE_TOOL),
            "system": t(TKey.COMPACT_ROLE_SYSTEM),
        }
        history_parts: list[str] = []
        for msg in messages:
            role_label = role_labels.get(msg.role, msg.role)
            try:
                parsed = json.loads(msg.content)
                if isinstance(parsed, list):
                    text_parts: list[str] = []
                    for block in parsed:
                        if block.get("type") == "tool_use":
                            text_parts.append(
                                f"[调用工具 {block.get('name', '')}：{json.dumps(block.get('input', {}), ensure_ascii=False)}]"
                            )
                        elif block.get("type") == "text":
                            text_parts.append(block["text"])
                    history_parts.append(f"{role_label}: {' '.join(text_parts)}")
                elif isinstance(parsed, dict) and "tool_use_id" in parsed:
                    content = str(parsed.get("content", ""))
                    preview = content[:500] + "..." if len(content) > 500 else content
                    history_parts.append(f"{role_label}: {preview}")
                else:
                    history_parts.append(f"{role_label}: {msg.content}")
            except (json.JSONDecodeError, TypeError):
                history_parts.append(f"{role_label}: {msg.content}")

        history_text = "\n".join(history_parts)

        summary_prompt = f"""{t(TKey.COMPACT_SUMMARY_PROMPT)}

{t(TKey.COMPACT_CONVERSATION_HISTORY)}
{history_text}

{t(TKey.COMPACT_OUTPUT_SUMMARY)}"""

        summary_messages: list[dict] = [
            {"role": "user", "content": summary_prompt},
        ]

        return await chat_completion(channel, model, summary_messages, max_tokens=2048)
