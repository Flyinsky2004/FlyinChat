from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str
    version: str = "0.1.0"
    category: str = "general"
    tags: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    constraints: tuple[dict[str, Any], ...] = ()
    related_skills: tuple[str, ...] = ()
    priority: int = 0
    source: str = "project"

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True)
class LoadedSkill:
    manifest: SkillManifest
    path: Path
    body: str
    sections: dict[str, str]
    checksum: str


@dataclass(frozen=True)
class InvalidSkill:
    path: Path
    reason: str


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    loaded_skills: tuple[LoadedSkill, ...]
    invalid_skills: tuple[InvalidSkill, ...] = ()
    checksum: str = ""

    def by_name(self, name: str) -> LoadedSkill | None:
        return next((skill for skill in self.loaded_skills if skill.manifest.name == name), None)


@dataclass(frozen=True)
class RejectedSkill:
    name: str
    reason: str
    score: int = 0


@dataclass(frozen=True)
class SkillDecision:
    selected: tuple[LoadedSkill, ...]
    rejected: tuple[RejectedSkill, ...] = ()
    confidence: float = 0.0
    reason: str = ""

    @property
    def applied_refs(self) -> tuple[str, ...]:
        return tuple(skill.manifest.ref for skill in self.selected)


@dataclass(frozen=True)
class RuntimeGuard:
    guard_id: str
    skill_name: str
    guard_type: str
    action: str
    reason: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillRuntimeState:
    applied_skills: tuple[str, ...]
    active_phase: str = "discover"
    guards_applied: tuple[RuntimeGuard, ...] = ()
    decision_reason: str = ""


@dataclass(frozen=True)
class CompiledSkill:
    planning_injection: str
    runtime_guards: tuple[RuntimeGuard, ...]
    phase_model: tuple[str, ...]
    runtime_state: SkillRuntimeState
