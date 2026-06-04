from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from flyinchat.models import LLMChannel, LLMModel, TurnResult

from .client import NoopObservabilityClient, ObservabilityClient
from .config import ObservabilityConfig
from .git_metadata import collect_git_diff_summary, collect_git_metadata
from .metrics import AgentRunMetrics, ToolCallMetric
from .sanitize import preview_tool_result, sanitize_messages, sanitize_tool_args, sanitize_value
from .scoring import build_scores


@dataclass
class AgentTrace:
    client: ObservabilityClient = field(default_factory=NoopObservabilityClient)
    trace_ref: Any = None
    span_ref: Any = None
    workspace: Path = field(default_factory=Path.cwd)
    turn_id: str = ""
    started_at: float = field(default_factory=time.time)
    config: ObservabilityConfig | None = None
    metrics: AgentRunMetrics = field(default_factory=AgentRunMetrics)

    @classmethod
    def start(
        cls,
        client: ObservabilityClient | None,
        *,
        turn_id: str,
        conversation_id: str,
        user_input: str,
        workspace: Path,
        agent_mode: str,
        permission_mode: str,
        model_name: str = "unknown",
        config: ObservabilityConfig | None = None,
    ) -> "AgentTrace":
        client = client or NoopObservabilityClient()
        git = collect_git_metadata(workspace)
        agent_version = _agent_version(config, git.commit)
        metadata = {
            "trace_id": "managed_by_langfuse",
            "session_id": conversation_id,
            "task_id": turn_id,
            "agent_version": agent_version,
            "model_name": model_name,
            "prompt_version": "default",
            "tool_version": "default",
            "workspace": str(workspace),
            "git_branch": git.branch,
            "git_commit_before": git.commit,
            "agent_mode": agent_mode,
            "permission_mode": permission_mode,
            "started_at": time.time(),
            "agent_env": config.agent_env if config else "development",
        }
        trace_ref = client.start_trace(
            name="flyinchat.user_task",
            input=user_input,
            metadata=metadata,
            session_id=conversation_id,
            user_id=None,
        )
        span_ref = client.start_span(
            trace_ref,
            name="agent.loop",
            input={"user_input": user_input},
            metadata=metadata,
        )
        return cls(
            client=client,
            trace_ref=trace_ref,
            span_ref=span_ref,
            workspace=workspace,
            turn_id=turn_id,
            config=config,
        )

    def update_model(self, model: LLMModel) -> None:
        self.client.update_trace(
            self.trace_ref,
            metadata={"model_name": model.name, "model_id": model.id},
        )

    def mark_compaction(self, *, tokens_before: int, tokens_after: int) -> None:
        self.metrics = self.metrics.with_compaction(
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

    def start_generation(
        self,
        *,
        name: str,
        channel: LLMChannel,
        model: LLMModel,
        messages: list[dict[str, Any]],
        tools_count: int = 0,
        max_tokens: int | None = None,
    ) -> "GenerationTrace":
        sanitized_messages = sanitize_messages(messages)
        model_parameters = {
            "provider_type": channel.provider_type,
            "max_tokens": max_tokens or model.max_output_tokens,
            "thinking_enabled": model.thinking_enabled,
            "reasoning_effort": model.reasoning_effort,
            "tools_count": tools_count,
        }
        metadata = {
            "message_count": len(messages),
            "input_hash": sanitized_messages["hash"],
            "input_sanitized_hash": sanitized_messages["sanitized_hash"],
            "input_truncated": sanitized_messages["truncated"],
            "input_original_length": sanitized_messages["original_length"],
        }
        ref = self.client.start_generation(
            self.trace_ref,
            name=name,
            model=model.name,
            input={
                "messages": sanitized_messages["messages"],
                "preview": sanitized_messages["preview"],
            },
            metadata=metadata,
            model_parameters=model_parameters,
        )
        return GenerationTrace(parent=self, ref=ref, started_at=time.time())

    def start_tool(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
    ) -> "ToolTrace":
        sanitized_args = sanitize_tool_args(tool_args)
        ref = self.client.start_span(
            self.trace_ref,
            name=f"tool.{tool_name}",
            input=sanitized_args,
            metadata={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "risk_level": risk_level,
                "requires_approval": False,
                "approval_status": "not_required",
            },
        )
        return ToolTrace(
            parent=self,
            ref=ref,
            started_at=time.time(),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk_level,
        )

    def finish(self, result: TurnResult, *, task_latency_ms: int) -> None:
        diff = collect_git_diff_summary(self.workspace)
        scores = build_scores(result, self.metrics, task_latency_ms=task_latency_ms)
        metadata = {
            **self.metrics.as_metadata(),
            **diff.as_dict(),
            **scores.metadata,
            "status": result.status,
            "terminal_reason": result.terminal_reason,
            "last_tool_error": result.last_tool_error,
            "ended_at": time.time(),
        }
        self.client.end_span(
            self.span_ref,
            output={
                "final_answer": result.final_text,
                "status": result.status,
                "error_message": result.error,
                "total_steps": self.metrics.total_steps,
                "total_tool_calls": self.metrics.tool_call_count,
                "total_llm_calls": self.metrics.llm_call_count,
                "total_latency_ms": task_latency_ms,
            },
            metadata=metadata,
            status_message=result.error,
        )
        for name, value in scores.scores.items():
            self.client.score_trace(self.trace_ref, name=name, value=value)
        self.client.update_trace(
            self.trace_ref,
            output=result.final_text or result.error or result.status,
            metadata=metadata,
            status_message=result.error,
        )
        self.client.flush()


@dataclass
class GenerationTrace:
    parent: AgentTrace
    ref: Any
    started_at: float

    def finish(
        self,
        *,
        output: Any,
        usage_info: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
        error: str | None = None,
    ) -> None:
        elapsed_ms = int((time.time() - self.started_at) * 1000)
        metadata = {
            "latency_ms": elapsed_ms,
            "finish_reason": "error" if error else "stop",
            "error": error,
        }
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            **{key: value for key, value in usage_info.items() if isinstance(value, int | float)},
        }
        self.parent.client.end_generation(
            self.ref,
            output=sanitize_value(output),
            usage=usage,
            metadata=metadata,
            status_message=error,
        )
        self.parent.metrics = self.parent.metrics.with_llm_call(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
        )


@dataclass
class ToolTrace:
    parent: AgentTrace
    ref: Any
    started_at: float
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]
    risk_level: str
    requires_approval: bool = False
    approval_status: str = "not_required"

    def with_approval_required(self) -> "ToolTrace":
        self.requires_approval = True
        self.approval_status = "pending"
        self.parent.client.update_trace(
            self.parent.trace_ref,
            metadata={"permission_request_count": self.parent.metrics.permission_request_count + 1},
        )
        return self

    def set_approval_status(self, status: str) -> None:
        self.requires_approval = True
        self.approval_status = status

    def finish(self, result: Any) -> None:
        elapsed_ms = int(result.meta.get("elapsed_ms") or int((time.time() - self.started_at) * 1000))
        content = str(getattr(result, "content", ""))
        result_preview = preview_tool_result(self.tool_name, self.tool_args, content)
        metadata = {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "status": "success" if result.ok else "error",
            "error_type": result.error_code,
            "error_message": None if result.ok else result.content,
            "latency_ms": elapsed_ms,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "approval_status": self.approval_status,
            "tool_result_hash": result_preview["hash"],
            "tool_result_truncated": result_preview["truncated"],
            "tool_result_original_length": result_preview["original_length"],
            "tool_result_redacted": result_preview.get("redacted", False),
            "data": sanitize_value(getattr(result, "data", None)),
        }
        self.parent.client.end_span(
            self.ref,
            output={"tool_result_preview": result_preview["preview"]},
            metadata=metadata,
            status_message=None if result.ok else str(result.error_code or result.content),
        )
        metric = ToolCallMetric(
            tool_name=self.tool_name,
            ok=bool(result.ok),
            error_code=result.error_code,
            requires_approval=self.requires_approval,
            approval_status=self.approval_status,
            risk_level=self.risk_level,
            elapsed_ms=elapsed_ms,
            command=str(self.tool_args.get("command", "")),
            exit_code=(result.data or {}).get("exit_code") if getattr(result, "data", None) else None,
        )
        self.parent.metrics = self.parent.metrics.with_tool_call(metric)


def _agent_version(config: ObservabilityConfig | None, git_commit: str) -> str:
    if config and config.agent_version:
        return config.agent_version
    return git_commit if git_commit != "unknown" else "local"
