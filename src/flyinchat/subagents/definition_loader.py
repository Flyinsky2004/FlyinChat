from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import SubAgentDefinition


class SubAgentDefinitionError(ValueError):
    """Raised when a sub-agent definition file is invalid."""


class SubAgentRegistry:
    """Load sub-agent definitions from workspace, user, and built-in sources."""

    def __init__(self, project_root: Path, user_root: Path | None = None) -> None:
        self.project_root = project_root
        self.user_root = user_root if user_root is not None else Path.home() / ".flyinchat"
        self._definitions: dict[str, SubAgentDefinition] = {}

    @property
    def definitions(self) -> dict[str, SubAgentDefinition]:
        return dict(self._definitions)

    def refresh(self) -> dict[str, SubAgentDefinition]:
        candidates = [
            ("workspace", self.project_root / ".flyinchat" / "subagents"),
            ("user", self.user_root / "subagents"),
            ("builtin", Path(__file__).parent / "builtin"),
        ]
        definitions: dict[str, SubAgentDefinition] = {}
        for source, root in candidates:
            for path in _definition_paths(root):
                definition = parse_subagent_file(path, source=source)
                if definition.name not in definitions:
                    definitions[definition.name] = definition
        self._definitions = definitions
        return dict(self._definitions)

    def get(self, name: str) -> SubAgentDefinition | None:
        if not self._definitions:
            self.refresh()
        return self._definitions.get(name)

    def list_definitions(self) -> list[SubAgentDefinition]:
        if not self._definitions:
            self.refresh()
        return sorted(self._definitions.values(), key=lambda item: item.name)


def parse_subagent_file(path: Path, *, source: str = "workspace") -> SubAgentDefinition:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    raw = _parse_frontmatter(frontmatter)
    system_prompt = _extract_system_prompt(body)
    definition = SubAgentDefinition(
        name=str(raw.get("name", "")).strip(),
        description=str(raw.get("description", "")).strip(),
        system_prompt=system_prompt,
        allowed_tools=_as_tuple(raw.get("allowed_tools")),
        disallowed_tools=_as_tuple(raw.get("disallowed_tools")),
        model=_optional_str(raw.get("model")),
        permission_mode=str(raw.get("permission_mode") or "inherit"),
        max_turns=_as_int(raw.get("max_turns"), default=10),
        max_tool_calls=_as_int(raw.get("max_tool_calls"), default=20),
        max_tokens=_as_int(raw.get("max_tokens"), default=50_000),
        context_policy=str(raw.get("context_policy") or "minimal"),
        source=source,
    )
    _validate_definition(definition, path)
    return definition


def _definition_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(sorted(path for path in root.glob("**/*.md") if path.is_file()))


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise SubAgentDefinitionError("definition must start with frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise SubAgentDefinitionError("frontmatter must be closed")
    return text[4:end].strip("\n"), text[end + 4 :].strip()


def _parse_frontmatter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise SubAgentDefinitionError(f"invalid frontmatter line: {line}")
        key, value = stripped.split(":", 1)
        result[key.strip()] = _parse_scalar(value.strip())
    return result


def _parse_scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(item.strip()) for item in inner.split(",") if item.strip()]
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return _strip_quotes(value)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_system_prompt(body: str) -> str:
    lines = body.strip().splitlines()
    if lines and lines[0].strip().lower() == "## system prompt":
        return "\n".join(lines[1:]).strip()
    return body.strip()


def _validate_definition(definition: SubAgentDefinition, path: Path) -> None:
    if not definition.name:
        raise SubAgentDefinitionError(f"missing name in {path}")
    if not definition.description:
        raise SubAgentDefinitionError(f"missing description in {path}")
    if not definition.system_prompt:
        raise SubAgentDefinitionError(f"missing system prompt in {path}")
    if not definition.allowed_tools:
        raise SubAgentDefinitionError(f"missing allowed_tools in {path}")
    if definition.max_turns < 1:
        raise SubAgentDefinitionError("max_turns must be positive")
    if definition.max_tool_calls < 1:
        raise SubAgentDefinitionError("max_tool_calls must be positive")
    if definition.max_tokens < 1:
        raise SubAgentDefinitionError("max_tokens must be positive")
