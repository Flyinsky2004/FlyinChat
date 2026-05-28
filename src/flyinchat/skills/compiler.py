from __future__ import annotations

from typing import Any
from uuid import uuid4

from .models import CompiledSkill, RuntimeGuard, SkillDecision, SkillRuntimeState

_PHASE_MODEL = ("discover", "validate", "apply", "verify")


class SkillCompiler:
    def compile(self, decision: SkillDecision) -> CompiledSkill:
        guards = tuple(
            guard
            for skill in decision.selected
            for guard in _compile_constraints(skill.manifest.name, skill.manifest.constraints)
        )
        state = SkillRuntimeState(
            applied_skills=decision.applied_refs,
            active_phase=_PHASE_MODEL[0],
            guards_applied=guards,
            decision_reason=decision.reason,
        )
        return CompiledSkill(
            planning_injection=_planning_injection(decision),
            runtime_guards=guards,
            phase_model=_PHASE_MODEL,
            runtime_state=state,
        )


def _planning_injection(decision: SkillDecision) -> str:
    if not decision.selected:
        return ""
    lines = [
        "Active Skills:",
        f"- Selection reason: {decision.reason}",
        f"- Phase model: {' -> '.join(_PHASE_MODEL)}",
    ]
    for skill in decision.selected:
        manifest = skill.manifest
        lines.append(f"- {manifest.ref}: {manifest.description}")
        workflow = skill.sections.get("workflow")
        verification = skill.sections.get("verification_checklist")
        if workflow:
            lines.append(f"  Workflow: {_single_line(workflow)}")
        if verification:
            lines.append(f"  Verification: {_single_line(verification)}")
    lines.append("Follow the active skill workflow and satisfy its verification checklist before finalizing.")
    return "\n".join(lines)


def _compile_constraints(skill_name: str, constraints: tuple[dict[str, Any], ...]) -> tuple[RuntimeGuard, ...]:
    guards: list[RuntimeGuard] = []
    for constraint in constraints:
        guard_type = str(constraint.get("type") or constraint.get("guard") or "").strip()
        if not guard_type:
            continue
        action = "ask" if guard_type == "ask_tool" else "deny"
        guards.append(
            RuntimeGuard(
                guard_id=f"sg_{uuid4().hex[:12]}",
                skill_name=skill_name,
                guard_type=guard_type,
                action=action,
                reason=str(constraint.get("reason") or f"skill guard from {skill_name}"),
                parameters={key: value for key, value in constraint.items() if key not in {"type", "guard", "reason"}},
            )
        )
    return tuple(guards)


def _single_line(text: str) -> str:
    return " ".join(part.strip() for part in text.splitlines() if part.strip())
