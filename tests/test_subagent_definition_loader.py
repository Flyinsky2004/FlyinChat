from pathlib import Path

import pytest

from flyinchat.subagents import (
    SubAgentDefinitionError,
    SubAgentRegistry,
    parse_subagent_file,
)


def test_builtin_subagent_definitions_are_loaded(tmp_path: Path) -> None:
    registry = SubAgentRegistry(tmp_path)

    definitions = registry.refresh()

    assert set(definitions) >= {"general-purpose", "code-reviewer", "debugger", "test-runner"}
    assert definitions["code-reviewer"].source == "builtin"
    assert "file_read" in definitions["code-reviewer"].allowed_tools
    assert "file_write" in definitions["code-reviewer"].disallowed_tools


def test_workspace_definition_overrides_builtin(tmp_path: Path) -> None:
    definition_dir = tmp_path / ".flyinchat" / "subagents"
    definition_dir.mkdir(parents=True)
    (definition_dir / "code-reviewer.md").write_text(
        """---
name: code-reviewer
description: Workspace override
allowed_tools: [file_read]
disallowed_tools: [file_write]
permission_mode: readonly
max_turns: 3
max_tool_calls: 4
max_tokens: 1000
context_policy: minimal
---

## System Prompt
Workspace reviewer prompt.
""",
        encoding="utf-8",
    )
    registry = SubAgentRegistry(tmp_path)

    definition = registry.get("code-reviewer")

    assert definition is not None
    assert definition.source == "workspace"
    assert definition.description == "Workspace override"
    assert definition.max_turns == 3


def test_invalid_definition_requires_allowed_tools(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text(
        """---
name: bad
description: Bad definition
---

## System Prompt
Missing tools.
""",
        encoding="utf-8",
    )

    with pytest.raises(SubAgentDefinitionError, match="missing allowed_tools"):
        parse_subagent_file(path)
