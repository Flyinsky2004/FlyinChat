from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flyinchat.models import TurnResult

from .metrics import AgentRunMetrics


@dataclass(frozen=True)
class ScoreSet:
    scores: dict[str, float]
    metadata: dict[str, Any]


def build_scores(result: TurnResult, metrics: AgentRunMetrics, *, task_latency_ms: int) -> ScoreSet:
    task_success = 1.0 if result.status == "completed" and result.last_tool_error is None else 0.0
    grounding_accuracy = _ratio(
        sum(1 for metric in metrics.tool_calls if metric.grounding_ok),
        metrics.tool_call_count,
        default=1.0,
    )
    tool_call_accuracy = _ratio(
        sum(1 for metric in metrics.tool_calls if metric.tool_choice_ok),
        metrics.tool_call_count,
        default=1.0,
    )
    rule_compliance = 0.0 if metrics.rule_violation_count or metrics.unsafe_action_count else 1.0
    progress_rate = _progress_rate(result, metrics)
    decision_accuracy = 1.0 if result.status in {"completed", "cancelled", "error", "max_rounds"} else 0.0
    failure = classify_failure(result, metrics)

    return ScoreSet(
        scores={
            "task_success": task_success,
            "progress_rate": progress_rate,
            "tool_call_accuracy": tool_call_accuracy,
            "grounding_accuracy": grounding_accuracy,
            "decision_accuracy": decision_accuracy,
            "rule_compliance": rule_compliance,
            "task_latency_ms": float(task_latency_ms),
            "total_steps": float(metrics.total_steps),
        },
        metadata={
            "failure_stage": failure["failure_stage"],
            "failure_reason": failure["failure_reason"],
            "root_cause": failure["root_cause"],
            "recoverable": failure["recoverable"],
            "suggested_fix": failure["suggested_fix"],
        },
    )


def classify_failure(result: TurnResult, metrics: AgentRunMetrics) -> dict[str, Any]:
    if result.status == "completed" and result.last_tool_error is None:
        return {
            "failure_stage": "none",
            "failure_reason": "none",
            "root_cause": "none",
            "recoverable": False,
            "suggested_fix": "none",
        }

    if result.status == "cancelled":
        return {
            "failure_stage": "user_interaction",
            "failure_reason": "cancelled",
            "root_cause": "User cancelled the task",
            "recoverable": True,
            "suggested_fix": "Resume or resubmit the task if needed",
        }

    if metrics.permission_denied_count:
        return {
            "failure_stage": "permission_error",
            "failure_reason": "permission_denied",
            "root_cause": "A required tool permission was denied or timed out",
            "recoverable": True,
            "suggested_fix": "Approve the required safe action or choose a lower-risk alternative",
        }

    if result.last_tool_error:
        return {
            "failure_stage": "tool_execution_error",
            "failure_reason": result.last_tool_error,
            "root_cause": "The latest tool call failed and was not recovered before the turn ended",
            "recoverable": True,
            "suggested_fix": "Inspect the tool error and retry with corrected arguments or an alternate tool",
        }

    if result.status == "max_rounds":
        return {
            "failure_stage": "timeout",
            "failure_reason": result.terminal_reason or "max_rounds",
            "root_cause": "The agent reached its configured turn budget",
            "recoverable": True,
            "suggested_fix": "Increase max turns or split the task into smaller steps",
        }

    if result.error:
        return {
            "failure_stage": "environment_error",
            "failure_reason": result.error,
            "root_cause": result.error,
            "recoverable": True,
            "suggested_fix": "Check model/API/tool environment and retry",
        }

    return {
        "failure_stage": "unknown",
        "failure_reason": result.status,
        "root_cause": "The task did not complete successfully",
        "recoverable": True,
        "suggested_fix": "Review trace events and retry with more context",
    }


def _progress_rate(result: TurnResult, metrics: AgentRunMetrics) -> float:
    completed = 1  # understood user request enough to enter QueryEngine
    total = 8
    if metrics.llm_call_count:
        completed += 2  # assembled prompt + made model decision
    if metrics.tool_call_count:
        completed += 2  # selected and executed tools
    if metrics.tests_run:
        completed += 1
    if result.final_text:
        completed += 1
    if result.status == "completed":
        completed += 1
    return min(1.0, completed / total)


def _ratio(numerator: int, denominator: int, *, default: float) -> float:
    if denominator == 0:
        return default
    return numerator / denominator
