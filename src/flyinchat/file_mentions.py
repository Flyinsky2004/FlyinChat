from dataclasses import dataclass
from pathlib import Path


IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".flyinchat",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "node_modules",
        "dist",
        "build",
    }
)


@dataclass(frozen=True)
class MentionSpan:
    start: int
    end: int
    query: str


@dataclass(frozen=True)
class WorkspacePathSuggestion:
    path: str
    is_dir: bool


def find_active_mention(value: str, cursor_position: int | None = None) -> MentionSpan | None:
    cursor = len(value) if cursor_position is None else cursor_position
    cursor = max(0, min(cursor, len(value)))
    start = value.rfind("@", 0, cursor)
    if start == -1:
        return None

    query = value[start + 1 : cursor]
    if any(char.isspace() for char in query):
        return None

    return MentionSpan(start=start, end=cursor, query=query)


def workspace_path_suggestions(
    workspace_root: Path,
    query: str,
    *,
    limit: int = 12,
) -> tuple[WorkspacePathSuggestion, ...]:
    root = workspace_root.resolve()
    if not root.exists() or not root.is_dir():
        return ()

    normalized_query = query.casefold()
    matches: list[WorkspacePathSuggestion] = []
    for candidate in root.rglob("*"):
        if _is_ignored_path(candidate, root):
            continue
        if not candidate.is_file() and not candidate.is_dir():
            continue

        relative_path = candidate.relative_to(root).as_posix()
        name = candidate.name
        if _matches_path(relative_path, name, normalized_query):
            matches.append(
                WorkspacePathSuggestion(path=relative_path, is_dir=candidate.is_dir())
            )

    ordered = sorted(matches, key=lambda item: _sort_key(item, normalized_query))
    return tuple(ordered[:limit])


def _is_ignored_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in IGNORED_DIR_NAMES for part in relative.parts)


def _matches_path(relative_path: str, name: str, query: str) -> bool:
    if not query:
        return True
    return query in name.casefold() or query in relative_path.casefold()


def _sort_key(item: WorkspacePathSuggestion, query: str) -> tuple[int, int, str]:
    path = item.path.casefold()
    name = Path(item.path).name.casefold()
    if not query:
        rank = 0
    elif name == query:
        rank = 0
    elif name.startswith(query):
        rank = 1
    elif query in name:
        rank = 2
    elif path.startswith(query):
        rank = 3
    else:
        rank = 4
    file_rank = 1 if item.is_dir else 0
    return (rank, file_rank, path)
