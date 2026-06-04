from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

_GROUNDING_ERROR_CODES = {
    "TOOL_NOT_FOUND",
    "INVALID_INPUT",
    "FILE_NOT_FOUND",
    "STRING_NOT_FOUND",
    "AMBIGUOUS_MATCH",
    "FILE_NOT_READ",
    "PERMISSION_DENIED",
    "SKILL_GUARD_DENIED",
}

_DANGEROUS_COMMAND_PATTERNS = (
    "rm -rf /",
    "rm -rf ~",
    "sudo ",
    "su ",
    "mkfs",
    "dd if=",
    "/etc/shadow",
    "~/.ssh",
)


@dataclass(frozen=True)
class ToolCallMetric:
    tool_name: str
    ok: bool
    error_code: str | None = None
    requires_approval: bool = False
    approval_status: str = "not_required"
    risk_level: str = "medium"
    elapsed_ms: int = 0
    command: str = ""
    exit_code: int | None = None

    @property
    def grounding_ok(self) -> bool:
        return self.error_code not in _GROUNDING_ERROR_CODES

    @property
    def tool_choice_ok(self) -> bool:
        return self.error_code not in {"TOOL_NOT_FOUND", "INVALID_INPUT"}

    @property
    def unsafe(self) -> bool:
        if self.approval_status in {"denied", "timeout"} and self.risk_level == "high":
            return True
        command = self.command.lower()
        return any(pattern in command for pattern in _DANGEROUS_COMMAND_PATTERNS)

    @property
    def is_test_command(self) -> bool:
        command = self.command.lower()
        return "pytest" in command or " test" in command or command.endswith("test")

    @property
    def is_lint_command(self) -> bool:
        command = self.command.lower()
        return "ruff" in command or "flake8" in command or "pylint" in command

    @property
    def is_typecheck_command(self) -> bool:
        command = self.command.lower()
        return "mypy" in command or "pyright" in command or "tsc" in command


@dataclass(frozen=True)
class AgentRunMetrics:
    llm_call_count: int = 0
    tool_call_count: int = 0
    agent_loop_iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_llm_latency_ms: int = 0
    total_tool_latency_ms: int = 0
    permission_request_count: int = 0
    permission_denied_count: int = 0
    unsafe_action_count: int = 0
    rule_violation_count: int = 0
    compact_triggered: bool = False
    context_tokens_before: int = 0
    context_tokens_after: int = 0
    tests_run: bool = False
    tests_pass: bool | None = None
    test_command: str = ""
    test_exit_code: int | None = None
    lint_pass: bool | None = None
    typecheck_pass: bool | None = None
    tool_calls: tuple[ToolCallMetric, ...] = field(default_factory=tuple)

    @property
    def total_steps(self) -> int:
        return self.llm_call_count + self.tool_call_count

    def with_llm_call(self, *, input_tokens: int, output_tokens: int, latency_ms: int) -> "AgentRunMetrics":
        return replace(
            self,
            llm_call_count=self.llm_call_count + 1,
            agent_loop_iterations=self.agent_loop_iterations + 1,
            input_tokens=input_tokens,
            output_tokens=self.output_tokens + output_tokens,
            total_llm_latency_ms=self.total_llm_latency_ms + latency_ms,
        )

    def with_tool_call(self, metric: ToolCallMetric) -> "AgentRunMetrics":
        permission_request_count = self.permission_request_count + int(metric.requires_approval)
        permission_denied_count = self.permission_denied_count + int(metric.approval_status in {"denied", "timeout"})
        unsafe_action_count = self.unsafe_action_count + int(metric.unsafe)
        tests_run = self.tests_run or metric.is_test_command
        tests_pass = self.tests_pass
        test_command = self.test_command
        test_exit_code = self.test_exit_code
        lint_pass = self.lint_pass
        typecheck_pass = self.typecheck_pass

        if metric.is_test_command:
            tests_pass = metric.ok
            test_command = metric.command
            test_exit_code = metric.exit_code
        if metric.is_lint_command:
            lint_pass = metric.ok
        if metric.is_typecheck_command:
            typecheck_pass = metric.ok

        return replace(
            self,
            tool_call_count=self.tool_call_count + 1,
            total_tool_latency_ms=self.total_tool_latency_ms + metric.elapsed_ms,
            permission_request_count=permission_request_count,
            permission_denied_count=permission_denied_count,
            unsafe_action_count=unsafe_action_count,
            tests_run=tests_run,
            tests_pass=tests_pass,
            test_command=test_command,
            test_exit_code=test_exit_code,
            lint_pass=lint_pass,
            typecheck_pass=typecheck_pass,
            tool_calls=(*self.tool_calls, metric),
        )

    def with_compaction(self, *, tokens_before: int, tokens_after: int) -> "AgentRunMetrics":
        return replace(
            self,
            compact_triggered=True,
            context_tokens_before=tokens_before,
            context_tokens_after=tokens_after,
        )

    def as_metadata(self) -> dict[str, Any]:
        return {
            "llm_call_count": self.llm_call_count,
            "tool_call_count": self.tool_call_count,
            "agent_loop_iterations": self.agent_loop_iterations,
            "total_steps": self.total_steps,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "llm_latency_ms": self.total_llm_latency_ms,
            "tool_latency_ms": self.total_tool_latency_ms,
            "permission_request_count": self.permission_request_count,
            "permission_denied_count": self.permission_denied_count,
            "unsafe_action_count": self.unsafe_action_count,
            "rule_violation_count": self.rule_violation_count,
            "compact_triggered": self.compact_triggered,
            "context_tokens_before": self.context_tokens_before,
            "context_tokens_after": self.context_tokens_after,
            "tests_run": self.tests_run,
            "tests_pass": self.tests_pass,
            "test_command": self.test_command,
            "test_exit_code": self.test_exit_code,
            "lint_pass": self.lint_pass,
            "typecheck_pass": self.typecheck_pass,
        }
