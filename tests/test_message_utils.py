import json

from flyinchat.message_utils import message_to_api_format, message_to_display
from flyinchat.models import Message


def _message(*, content: dict, meta: dict) -> Message:
    return Message(
        id="m1",
        conversation_id="c1",
        role="tool",
        content=json.dumps(content),
        created_at="2026-05-27T00:00:00Z",
        meta=json.dumps(meta),
    )


def test_file_read_display_shows_path_without_file_content() -> None:
    display = message_to_display(
        _message(
            content={"tool_use_id": "tu_1", "content": "1|secret = 'hidden'"},
            meta={
                "tool_name": "file_read",
                "ok": True,
                "data": {
                    "path": "/workspace/src/example.py",
                    "offset": 1,
                    "returned_lines": 1,
                    "total_lines": 20,
                },
            },
        )
    )

    assert "example.py" in display
    assert "/workspace/src/example.py" in display
    assert "Lines 1-1 of 20" in display
    assert "secret = 'hidden'" not in display


def test_non_read_tool_result_still_renders_full_content() -> None:
    display = message_to_display(
        _message(
            content={"tool_use_id": "tu_1", "content": "diff --git a/a.py b/a.py\n+changed"},
            meta={"tool_name": "file_write", "ok": True},
        )
    )

    assert "diff --git a/a.py b/a.py" in display
    assert "+changed" in display


def test_skill_event_renders_loaded_skill_notice() -> None:
    msg = Message(
        id="m1",
        conversation_id="c1",
        role="system",
        subtype="skill_event",
        content=json.dumps({
            "event": "skill.resolve.complete",
            "applied_skills": ["liquid-glass@0.1.0"],
            "confidence": 1.0,
            "active_phase": "discover",
            "guards_applied": [],
        }),
        created_at="2026-05-27T00:00:00Z",
    )

    display = message_to_display(msg)

    assert "Loaded Skill" in display
    assert "liquid-glass@0.1.0" in display
    assert "phase: `discover`" in display


def test_skill_event_is_not_sent_to_model() -> None:
    msg = Message(
        id="m1",
        conversation_id="c1",
        role="system",
        subtype="skill_event",
        content=json.dumps({"event": "skill.resolve.complete", "applied_skills": ["x@1"]}),
        created_at="2026-05-27T00:00:00Z",
    )

    assert message_to_api_format(msg) is None
