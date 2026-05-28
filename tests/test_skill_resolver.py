from pathlib import Path

from flyinchat.skills.registry import SkillRegistry
from flyinchat.skills.resolver import SkillResolver


def _skill(root: Path, name: str, description: str, tags: str) -> None:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  tags: [{tags}]\n---\n\n# {name}\n\n## When to Use\nUse when {tags}.\n\n## Workflow\nDo it.\n",
        encoding="utf-8",
    )


def test_resolver_selects_matching_skill(tmp_path: Path) -> None:
    _skill(tmp_path, "edit-skill", "Use when editing files", "edit, files")
    _skill(tmp_path, "deploy-skill", "Use when deploying", "deploy")
    catalog = SkillRegistry(tmp_path, tmp_path / "user").refresh()

    decision = SkillResolver().resolve("please edit files safely", catalog)

    assert [skill.manifest.name for skill in decision.selected] == ["edit-skill"]
    assert decision.confidence > 0
    assert any(item.name == "deploy-skill" for item in decision.rejected)


def test_resolver_returns_empty_for_low_confidence(tmp_path: Path) -> None:
    _skill(tmp_path, "deploy-skill", "Use when deploying", "deploy")
    catalog = SkillRegistry(tmp_path, tmp_path / "user").refresh()

    decision = SkillResolver().resolve("write a poem", catalog)

    assert decision.selected == ()
    assert decision.reason == "no skill matched the request"
