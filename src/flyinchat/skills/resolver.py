from __future__ import annotations

import re
from collections.abc import Sequence

from .models import LoadedSkill, RejectedSkill, SkillCatalogSnapshot, SkillDecision

_TOKEN_RE = re.compile(r"[a-z0-9_\-/]+")


class SkillResolver:
    def resolve(
        self,
        query: str,
        catalog: SkillCatalogSnapshot,
        *,
        top_k: int = 3,
    ) -> SkillDecision:
        scored = [
            (skill, _score_skill(query, skill))
            for skill in catalog.loaded_skills
        ]
        scored = sorted(scored, key=lambda item: (-item[1], -item[0].manifest.priority, item[0].manifest.name))
        selected = tuple(skill for skill, score in scored if score > 0)[:top_k]
        rejected = tuple(
            RejectedSkill(
                name=skill.manifest.name,
                score=score,
                reason="lower ranked candidate" if score > 0 else "no trigger matched",
            )
            for skill, score in scored
            if skill not in selected
        )
        if not selected:
            return SkillDecision(
                selected=(),
                rejected=rejected,
                confidence=0.0,
                reason="no skill matched the request",
            )
        best_score = scored[0][1] if scored else 0
        confidence = min(1.0, best_score / 12)
        return SkillDecision(
            selected=selected,
            rejected=rejected,
            confidence=confidence,
            reason="selected by deterministic keyword, tag, and workflow matching",
        )


def _score_skill(query: str, skill: LoadedSkill) -> int:
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0
    manifest = skill.manifest
    score = 0
    score += _match_count(query_tokens, _tokens(manifest.name)) * 4
    score += _match_count(query_tokens, _tokens(manifest.description)) * 3
    score += _match_count(query_tokens, manifest.tags) * 4
    score += _match_count(query_tokens, manifest.triggers) * 5
    score += _match_count(query_tokens, _tokens(skill.sections.get("when_to_use", ""))) * 2
    score += _match_count(query_tokens, _tokens(skill.sections.get("workflow", "")))
    return score + manifest.priority


def _tokens(text: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(text, str):
        return tuple(match.group(0).lower() for match in _TOKEN_RE.finditer(text))
    return tuple(str(item).lower() for item in text)


def _match_count(query_tokens: set[str], candidate_tokens: Sequence[str]) -> int:
    return sum(1 for token in candidate_tokens if token.lower() in query_tokens)
