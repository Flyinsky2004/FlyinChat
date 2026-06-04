from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubAgentDefinition:
    """Definition for a selectable sub-agent type."""

    name: str
    description: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...] = ()
    model: str | None = None
    permission_mode: str = "inherit"
    max_turns: int = 10
    max_tool_calls: int = 20
    max_tokens: int = 50_000
    context_policy: str = "minimal"
    source: str = "builtin"


@dataclass(frozen=True)
class SubAgentResult:
    """Parent-visible structured result from a sub-agent run."""

    status: str
    summary: str
    findings: tuple[str, ...]
    evidence: tuple[str, ...]
    files_read: tuple[str, ...]
    files_modified: tuple[str, ...]
    tool_calls_count: int
    errors: tuple[str, ...]
    recommendations: tuple[str, ...]
    subagent_session_id: str
    tokens_used: int = 0
    turns_used: int = 0


@dataclass(frozen=True)
class SubAgentSession:
    """Runtime metadata for an isolated sub-agent session."""

    session_id: str
    parent_session_id: str
    agent_type: str
    status: str
    created_at: str
    completed_at: str = ""
    working_directory: str = ""
    tokens_used: int = 0
    turns_used: int = 0
