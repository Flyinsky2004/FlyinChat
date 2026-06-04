from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from flyinchat.api_client import chat_completion
from flyinchat.compact import TokenEstimator
from flyinchat.models import LLMChannel, LLMModel, Message

from .models import SubAgentDefinition, SubAgentResult


class SubAgentResultCompressor:
    """Compress a sub-agent transcript into a parent-visible result."""

    def __init__(self, channel: LLMChannel, model: LLMModel) -> None:
        self._channel = channel
        self._model = model
        self._estimator = TokenEstimator()

    async def compress(
        self,
        messages: list[Message],
        definition: SubAgentDefinition,
        task: str,
        status: str,
        subagent_session_id: str,
        tokens_used: int,
        turns_used: int,
    ) -> SubAgentResult:
        if self._estimator.estimate_messages(messages) >= 8_000:
            llm_result = await self._compress_with_llm(
                messages,
                definition,
                task,
                status,
                subagent_session_id,
                tokens_used,
                turns_used,
            )
            if llm_result is not None:
                return llm_result

        return self._compress_direct(
            messages,
            status,
            subagent_session_id,
            tokens_used,
            turns_used,
        )

    def _compress_direct(
        self,
        messages: list[Message],
        status: str,
        subagent_session_id: str,
        tokens_used: int,
        turns_used: int,
    ) -> SubAgentResult:
        files_read: list[str] = []
        files_modified: list[str] = []
        errors: list[str] = []
        evidence: list[str] = []
        tool_calls_count = 0
        final_text = ""

        for message in messages:
            if message.role == "assistant" and message.subtype == "normal":
                final_text = _assistant_text(message.content) or final_text
            if message.role != "tool":
                continue
            tool_calls_count += 1
            meta = _json_obj(message.meta)
            content_obj = _json_obj(message.content)
            content = str(content_obj.get("content", message.content))
            tool_name = str(meta.get("tool_name", ""))
            ok = bool(meta.get("ok", True))
            data = meta.get("data") if isinstance(meta.get("data"), dict) else {}

            if tool_name == "file_read" and isinstance(data, dict):
                path = str(data.get("path") or "")
                if path:
                    files_read.append(path)
                    evidence.append(f"read {path}")
            elif tool_name in {"file_write", "file_edit"} and isinstance(data, dict):
                path = str(data.get("path") or "")
                if path:
                    files_modified.append(path)
                    evidence.append(f"modified {path}")
            elif tool_name:
                evidence.append(f"{tool_name}: {_preview(content)}")

            if not ok:
                errors.append(f"{tool_name or 'tool'}: {_preview(content)}")

        summary = final_text.strip() or _fallback_summary(status, tool_calls_count, errors)
        findings = _extract_bullets(summary)
        recommendations = _extract_recommendations(summary)
        return SubAgentResult(
            status=status,
            summary=summary,
            findings=tuple(findings),
            evidence=tuple(dict.fromkeys(evidence)),
            files_read=tuple(dict.fromkeys(files_read)),
            files_modified=tuple(dict.fromkeys(files_modified)),
            tool_calls_count=tool_calls_count,
            errors=tuple(errors),
            recommendations=tuple(recommendations),
            subagent_session_id=subagent_session_id,
            tokens_used=tokens_used,
            turns_used=turns_used,
        )

    async def _compress_with_llm(
        self,
        messages: list[Message],
        definition: SubAgentDefinition,
        task: str,
        status: str,
        subagent_session_id: str,
        tokens_used: int,
        turns_used: int,
    ) -> SubAgentResult | None:
        transcript = "\n".join(_message_preview(message) for message in messages)
        prompt = f"""
Summarize this FlyinChat sub-agent transcript into JSON only.

Agent type: {definition.name}
Task: {task}
Status: {status}

Return keys:
summary: string
findings: string[]
evidence: string[]
files_read: string[]
files_modified: string[]
errors: string[]
recommendations: string[]

Transcript:
{transcript}
""".strip()
        try:
            text = await chat_completion(
                self._channel,
                self._model,
                [{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            parsed = json.loads(text)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        return SubAgentResult(
            status=status,
            summary=str(parsed.get("summary") or "Sub-agent completed."),
            findings=_tuple_of_str(parsed.get("findings")),
            evidence=_tuple_of_str(parsed.get("evidence")),
            files_read=_tuple_of_str(parsed.get("files_read")),
            files_modified=_tuple_of_str(parsed.get("files_modified")),
            tool_calls_count=sum(1 for message in messages if message.role == "tool"),
            errors=_tuple_of_str(parsed.get("errors")),
            recommendations=_tuple_of_str(parsed.get("recommendations")),
            subagent_session_id=subagent_session_id,
            tokens_used=tokens_used,
            turns_used=turns_used,
        )


def result_to_json(result: SubAgentResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, indent=2)


def _json_obj(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _assistant_text(content: str) -> str:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    if not isinstance(parsed, list):
        return content
    parts = [str(block.get("text", "")) for block in parsed if block.get("type") == "text"]
    return "\n".join(part for part in parts if part)


def _fallback_summary(status: str, tool_calls_count: int, errors: list[str]) -> str:
    if errors:
        return f"Sub-agent ended with {len(errors)} error(s) after {tool_calls_count} tool call(s)."
    return f"Sub-agent finished with status {status} after {tool_calls_count} tool call(s)."


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            bullets.append(stripped[2:].strip())
    return bullets[:20]


def _extract_recommendations(text: str) -> list[str]:
    recommendations: list[str] = []
    capture = False
    for line in text.splitlines():
        lowered = line.lower()
        if "recommend" in lowered or "next step" in lowered:
            capture = True
        elif capture and line.strip().startswith(("- ", "* ")):
            recommendations.append(line.strip()[2:].strip())
    return recommendations[:10]


def _message_preview(message: Message) -> str:
    content = _assistant_text(message.content) if message.role == "assistant" else message.content
    return f"{message.role}/{message.subtype}: {_preview(content, limit=1200)}"


def _preview(text: str, *, limit: int = 300) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "..."


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item))
