from pathlib import Path

from flyinchat.skills.registry import SkillRegistry


def _skill(root: Path, name: str, description: str) -> None:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n## Workflow\nDo it.\n",
        encoding="utf-8",
    )


def test_registry_loads_skills_deterministically(tmp_path: Path) -> None:
    _skill(tmp_path / "project", "z-skill", "Use when z")
    _skill(tmp_path / "project", "a-skill", "Use when a")

    snapshot = SkillRegistry(tmp_path / "project", tmp_path / "user").refresh()

    assert [skill.manifest.name for skill in snapshot.loaded_skills] == ["a-skill", "z-skill"]
    assert snapshot.invalid_skills == ()


def test_registry_excludes_invalid_skills(tmp_path: Path) -> None:
    bad = tmp_path / "project" / "skills" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("# bad", encoding="utf-8")

    snapshot = SkillRegistry(tmp_path / "project", tmp_path / "user").refresh()

    assert snapshot.loaded_skills == ()
    assert len(snapshot.invalid_skills) == 1


def test_project_skill_overrides_user_skill(tmp_path: Path) -> None:
    _skill(tmp_path / "user", "same-skill", "Use when user")
    _skill(tmp_path / "project", "same-skill", "Use when project")

    snapshot = SkillRegistry(tmp_path / "project", tmp_path / "user").refresh()

    assert len(snapshot.loaded_skills) == 1
    assert snapshot.loaded_skills[0].manifest.source == "project"
    assert snapshot.loaded_skills[0].manifest.description == "Use when project"
