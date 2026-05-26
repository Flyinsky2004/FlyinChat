from pathlib import Path

from flyinchat.file_mentions import find_active_mention, workspace_path_suggestions


def test_find_active_mention_reads_token_before_cursor() -> None:
    span = find_active_mention("fix @app", len("fix @app"))

    assert span is not None
    assert span.start == 4
    assert span.end == 8
    assert span.query == "app"


def test_find_active_mention_ignores_completed_token() -> None:
    span = find_active_mention("fix @app now")

    assert span is None


def test_workspace_path_suggestions_returns_relative_files_and_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / "src" / "flyinchat").mkdir(parents=True)
    (workspace / "src" / "flyinchat" / "app.py").write_text("app", encoding="utf-8")
    (workspace / "src" / "flyinchat" / "api_client.py").write_text("api", encoding="utf-8")

    paths = [item.path for item in workspace_path_suggestions(workspace, "app")]
    src_paths = [item.path for item in workspace_path_suggestions(workspace, "src")]

    assert "src/flyinchat/app.py" in paths
    assert "src" in src_paths
    assert all(not path.startswith(str(workspace)) for path in paths)


def test_workspace_path_suggestions_ignores_internal_generated_dirs(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / ".flyinchat").mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / ".venv" / "lib").mkdir(parents=True)
    (workspace / "node_modules" / "pkg").mkdir(parents=True)
    (workspace / ".gitignore").write_text("*.pyc", encoding="utf-8")
    (workspace / ".flyinchat" / "chat.json").write_text("{}", encoding="utf-8")
    (workspace / ".git" / "config").write_text("config", encoding="utf-8")
    (workspace / "__pycache__" / "app.pyc").write_text("cache", encoding="utf-8")
    (workspace / ".venv" / "lib" / "app.py").write_text("venv", encoding="utf-8")
    (workspace / "node_modules" / "pkg" / "app.js").write_text("node", encoding="utf-8")

    paths = [item.path for item in workspace_path_suggestions(workspace, "git")]
    app_paths = [item.path for item in workspace_path_suggestions(workspace, "app")]

    assert ".gitignore" in paths
    assert app_paths == []
