from pathlib import Path

from flyinchat.skills.compiler import SkillCompiler
from flyinchat.skills.registry import SkillRegistry
from flyinchat.skills.resolver import SkillResolver


def test_compiler_builds_planning_injection_and_guards(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "safe-edit" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
name: safe-edit
description: Use when editing files
metadata:
  tags: [edit]
constraints:
  - type: deny_tool
    tools: [bash]
    reason: no shell
---

# Safe Edit

## Workflow
Read the file before editing.

## Verification Checklist
Run pytest.
""",
        encoding="utf-8",
    )
    catalog = SkillRegistry(tmp_path, tmp_path / "user").refresh()
    decision = SkillResolver().resolve("edit this file", catalog)

    compiled = SkillCompiler().compile(decision)

    assert "safe-edit@0.1.0" in compiled.planning_injection
    assert "discover -> validate -> apply -> verify" in compiled.planning_injection
    assert len(compiled.runtime_guards) == 1
    assert compiled.runtime_guards[0].guard_type == "deny_tool"
    assert compiled.runtime_state.applied_skills == ("safe-edit@0.1.0",)
