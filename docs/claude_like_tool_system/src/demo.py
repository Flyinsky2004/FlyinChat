from pathlib import Path

from tool_core import PermissionContext, ToolContext, ToolExecutor, ToolRegistry
from file_tools import FileReadTool, FileWriteTool


def event_printer(event: str, payload: dict) -> None:
    print(f"[{event}] {payload}")


def main() -> None:
    workspace = Path("/root/.hermes/artifacts/claude_like_tool_system/workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    permission = PermissionContext(
        allowed_tools={"file_read", "file_write"},
        denied_tools=set(),
        allowed_read_roots=[workspace],
        allowed_write_roots=[workspace],
    )

    context = ToolContext(
        session_id="demo-session",
        user_id="demo-user",
        workspace_root=workspace,
        permission=permission,
        emit_event=event_printer,
    )

    registry = ToolRegistry()
    registry.register(FileReadTool())
    registry.register(FileWriteTool())

    executor = ToolExecutor(registry)

    r1 = executor.execute(
        "file_write",
        {"path": "hello.txt", "content": "line1\nline2\nline3\n"},
        context,
    )
    print("WRITE RESULT:", r1)

    r2 = executor.execute(
        "file_read",
        {"path": "hello.txt", "offset": 1, "limit": 2},
        context,
    )
    print("READ RESULT:", r2)


if __name__ == "__main__":
    main()
