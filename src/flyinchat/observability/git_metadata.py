from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .sanitize import sha256_text


@dataclass(frozen=True)
class GitMetadata:
    branch: str = "unknown"
    commit: str = "unknown"


@dataclass(frozen=True)
class GitDiffSummary:
    files_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    git_diff_hash: str = ""
    git_diff_summary: str = ""
    unexpected_files_changed: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "files_changed": self.files_changed,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "git_diff_hash": self.git_diff_hash,
            "git_diff_summary": self.git_diff_summary,
            "unexpected_files_changed": self.unexpected_files_changed,
        }


def collect_git_metadata(workspace: Path) -> GitMetadata:
    return GitMetadata(
        branch=_run_git(workspace, "rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        commit=_run_git(workspace, "rev-parse", "HEAD") or "unknown",
    )


def collect_git_diff_summary(workspace: Path) -> GitDiffSummary:
    stat = _run_git(workspace, "diff", "--stat") or ""
    numstat = _run_git(workspace, "diff", "--numstat") or ""
    diff = _run_git(workspace, "diff", "--no-ext-diff") or ""

    files_changed = 0
    lines_added = 0
    lines_deleted = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files_changed += 1
        added, deleted = parts[0], parts[1]
        if added.isdigit():
            lines_added += int(added)
        if deleted.isdigit():
            lines_deleted += int(deleted)

    return GitDiffSummary(
        files_changed=files_changed,
        lines_added=lines_added,
        lines_deleted=lines_deleted,
        git_diff_hash=sha256_text(diff) if diff else "",
        git_diff_summary=stat[:12_000],
    )


def _run_git(workspace: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
