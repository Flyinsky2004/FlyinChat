from __future__ import annotations

import hashlib
from pathlib import Path

from .models import InvalidSkill, LoadedSkill, SkillCatalogSnapshot
from .parser import parse_skill_file


class SkillRegistry:
    def __init__(self, project_root: Path, user_root: Path | None = None) -> None:
        self.project_root = project_root
        self.user_root = user_root if user_root is not None else Path.home() / ".flyinchat"
        self._snapshot = SkillCatalogSnapshot(loaded_skills=())

    @property
    def snapshot(self) -> SkillCatalogSnapshot:
        return self._snapshot

    def refresh(self) -> SkillCatalogSnapshot:
        candidates = [
            ("project", self.project_root / "skills"),
            ("user-local", self.user_root / "skills"),
        ]
        loaded_by_name: dict[str, LoadedSkill] = {}
        invalid: list[InvalidSkill] = []
        checksums: list[str] = []

        for source, root in candidates:
            for path in _skill_paths(root):
                try:
                    skill = parse_skill_file(path, source=source)
                except Exception as error:
                    invalid.append(InvalidSkill(path=path, reason=str(error)))
                    continue
                checksums.append(skill.checksum)
                if skill.manifest.name not in loaded_by_name:
                    loaded_by_name[skill.manifest.name] = skill

        loaded = tuple(sorted(loaded_by_name.values(), key=lambda skill: skill.manifest.name))
        checksum = hashlib.sha256("".join(sorted(checksums)).encode("utf-8")).hexdigest()
        self._snapshot = SkillCatalogSnapshot(
            loaded_skills=loaded,
            invalid_skills=tuple(invalid),
            checksum=checksum,
        )
        return self._snapshot

    def get(self, name: str) -> LoadedSkill | None:
        return self._snapshot.by_name(name)


def _skill_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(sorted(root.glob("**/SKILL.md")))
