from flyinchat.models import TurnResult
from flyinchat.observability.metrics import AgentRunMetrics, ToolCallMetric
from flyinchat.observability.scoring import build_scores


def test_completed_turn_scores_success() -> None:
    metrics = AgentRunMetrics().with_llm_call(
        input_tokens=10,
        output_tokens=5,
        latency_ms=100,
    )
    result = TurnResult(turn_id="turn_1", status="completed", final_text="done")

    scores = build_scores(result, metrics, task_latency_ms=200)

    assert scores.scores["task_success"] == 1.0
    assert scores.scores["grounding_accuracy"] == 1.0
    assert scores.metadata["failure_stage"] == "none"


def test_failed_tool_scores_failure_reason() -> None:
    metrics = AgentRunMetrics().with_tool_call(
        ToolCallMetric(
            tool_name="file_read",
            ok=False,
            error_code="FILE_NOT_FOUND",
        )
    )
    result = TurnResult(
        turn_id="turn_1",
        status="max_rounds",
        last_tool_error="FILE_NOT_FOUND",
    )

    scores = build_scores(result, metrics, task_latency_ms=200)

    assert scores.scores["task_success"] == 0.0
    assert scores.scores["grounding_accuracy"] == 0.0
    assert scores.metadata["failure_stage"] == "tool_execution_error"
    assert scores.metadata["failure_reason"] == "FILE_NOT_FOUND"


def test_permission_denied_classifies_permission_error() -> None:
    metrics = AgentRunMetrics().with_tool_call(
        ToolCallMetric(
            tool_name="bash",
            ok=False,
            error_code="PERMISSION_DENIED",
            requires_approval=True,
            approval_status="denied",
            risk_level="high",
        )
    )
    result = TurnResult(turn_id="turn_1", status="error", error="denied")

    scores = build_scores(result, metrics, task_latency_ms=100)

    assert scores.metadata["failure_stage"] == "permission_error"
    assert scores.scores["rule_compliance"] == 0.0
