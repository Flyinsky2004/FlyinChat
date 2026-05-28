from __future__ import annotations

import re

from .models import SkillManifest

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SkillValidationError(ValueError):
    pass


def validate_manifest(manifest: SkillManifest, body: str) -> None:
    if not manifest.name.strip():
        raise SkillValidationError("name is required")
    if not _SLUG_RE.match(manifest.name):
        raise SkillValidationError("name must be a lowercase slug")
    if not manifest.description.strip():
        raise SkillValidationError("description is required")
    if len(manifest.description) > 1024:
        raise SkillValidationError("description must be <= 1024 characters")
    if not body.strip():
        raise SkillValidationError("body is required")
