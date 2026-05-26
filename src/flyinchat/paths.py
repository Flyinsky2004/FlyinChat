from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    global_dir: Path
    project_dir: Path
    config_path: Path
    chat_path: Path


def resolve_app_paths(home: Path | None = None, cwd: Path | None = None) -> AppPaths:
    base_home = home if home is not None else Path.home()
    base_cwd = cwd if cwd is not None else Path.cwd()
    global_dir = base_home / ".flyinchat"
    project_dir = base_cwd / ".flyinchat"

    return AppPaths(
        global_dir=global_dir,
        project_dir=project_dir,
        config_path=global_dir / "config.json",
        chat_path=project_dir / "chat.json",
    )
