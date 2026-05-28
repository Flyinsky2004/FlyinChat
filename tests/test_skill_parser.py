from pathlib import Path

import pytest

from flyinchat.skills.parser import SkillParseError, parse_skill_file
from flyinchat.skills.validator import SkillValidationError


def _write_skill(path: Path, frontmatter: str, body: str = "# Title\n\n## Workflow\nDo work.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_parse_valid_skill(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "skills" / "demo" / "SKILL.md",
        """name: demo-skill
description: Use when editing files
version: 1.2.3
category: software-development
metadata:
  tags: [edit, files]
constraints:
  - type: deny_tool
    tools: [bash]
    reason: no shell""",
        "# Demo\n\n## When to Use\nWhen editing files.\n\n## Workflow\nRead then edit.\n\n## Verification Checklist\nRun tests.",
    )

    skill = parse_skill_file(path)

    assert skill.manifest.name == "demo-skill"
    assert skill.manifest.version == "1.2.3"
    assert skill.manifest.tags == ("edit", "files")
    assert skill.manifest.constraints[0]["type"] == "deny_tool"
    assert skill.sections["when_to_use"] == "When editing files."
    assert skill.sections["workflow"] == "Read then edit."


def test_missing_frontmatter_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("# No frontmatter", encoding="utf-8")

    with pytest.raises(SkillParseError):
        parse_skill_file(path)


def test_invalid_slug_is_invalid(tmp_path: Path) -> None:
    path = _write_skill(tmp_path / "SKILL.md", "name: Bad Skill\ndescription: Use when testing")

    with pytest.raises(SkillValidationError):
        parse_skill_file(path)


def test_missing_description_is_invalid(tmp_path: Path) -> None:
    path = _write_skill(tmp_path / "SKILL.md", "name: valid-name")

    with pytest.raises(SkillValidationError):
        parse_skill_file(path)
