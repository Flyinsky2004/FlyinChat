from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .models import LoadedSkill, SkillManifest
from .validator import validate_manifest

_SECTION_NAMES = {
    "overview": "overview",
    "when to use": "when_to_use",
    "workflow": "workflow",
    "pitfalls": "pitfalls",
    "verification checklist": "verification_checklist",
}


class SkillParseError(ValueError):
    pass


def parse_skill_file(path: Path, *, source: str = "project") -> LoadedSkill:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    raw = _parse_frontmatter(frontmatter)
    manifest = _manifest_from_raw(raw, source)
    validate_manifest(manifest, body)
    return LoadedSkill(
        manifest=manifest,
        path=path,
        body=body.strip(),
        sections=_extract_sections(body),
        checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise SkillParseError("SKILL.md must start with frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise SkillParseError("frontmatter must be closed")
    frontmatter = text[4:end].strip("\n")
    body = text[end + 4 :].strip()
    return frontmatter, body


def _parse_frontmatter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(" "):
            i += 1
            continue
        key, value = _parse_key_value(line)
        if value is not None:
            result[key] = _parse_scalar(value)
            i += 1
            continue

        nested: list[str] = []
        i += 1
        while i < len(lines) and lines[i].startswith(" "):
            nested.append(lines[i])
            i += 1
        result[key] = _parse_nested(nested)
    return result


def _parse_key_value(line: str) -> tuple[str, str | None]:
    if ":" not in line:
        raise SkillParseError(f"invalid frontmatter line: {line}")
    key, value = line.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise SkillParseError("empty frontmatter key")
    return key, value or None


def _parse_nested(lines: list[str]) -> Any:
    if not lines:
        return {}
    stripped = [line.strip() for line in lines]
    if stripped[0].startswith("-"):
        return _parse_list_block(stripped)
    nested: dict[str, Any] = {}
    for line in stripped:
        key, value = _parse_key_value(line)
        nested[key] = _parse_scalar(value or "")
    return nested


def _parse_list_block(lines: list[str]) -> list[Any]:
    items: list[Any] = []
    current: dict[str, Any] | None = None
    for line in lines:
        if line.startswith("- "):
            value = line[2:].strip()
            if ":" in value:
                key, raw_value = _parse_key_value(value)
                current = {key: _parse_scalar(raw_value or "")}
                items.append(current)
            else:
                current = None
                items.append(_parse_scalar(value))
        elif current is not None and ":" in line:
            key, raw_value = _parse_key_value(line)
            current[key] = _parse_scalar(raw_value or "")
    return items


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return _strip_quotes(value)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _manifest_from_raw(raw: dict[str, Any], source: str) -> SkillManifest:
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    tags = _as_tuple(raw.get("tags") or metadata.get("tags"))
    related = _as_tuple(raw.get("related_skills") or metadata.get("related_skills"))
    return SkillManifest(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        version=str(raw.get("version", "0.1.0")),
        category=str(raw.get("category", "general")),
        tags=tags,
        triggers=_as_tuple(raw.get("triggers")),
        constraints=_as_constraints(raw.get("constraints")),
        related_skills=related,
        priority=int(raw.get("priority", 0) or 0),
        source=source,
    )


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    return ()


def _as_constraints(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if match:
            title = match.group(1).strip().lower()
            current = _SECTION_NAMES.get(title)
            if current is not None:
                sections.setdefault(current, [])
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}
