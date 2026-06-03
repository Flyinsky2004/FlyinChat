from __future__ import annotations

import json
from pathlib import Path

from flyinchat.compact import (
    CompactMetadata,
    CompactionEngine,
    CompactionOutput,
    CompactionPolicy,
    TokenEstimator,
)
from flyinchat.models import LLMChannel, LLMModel
from flyinchat.paths import resolve_app_paths
from flyinchat.storage import (
    add_message,
    create_conversation,
    initialize_storage,
    list_active_messages,
    list_messages,
    update_message_content,
)


def test_token_estimator_basic() -> None:
    est = TokenEstimator()
    # "hello world" = 11 ASCII chars → 11 * 0.3 = 3
    assert est.estimate("hello world") == 3
    assert est.estimate("") == 0
    # 100 ASCII chars → 100 * 0.3 = 30
    assert est.estimate("a" * 100) == 30


def test_token_estimator_messages() -> None:
    from flyinchat.models import Message

    msgs = [
        Message(id="1", conversation_id="c1", role="user", content="hello world", created_at=""),
        Message(id="2", conversation_id="c1", role="assistant", content="a" * 40, created_at=""),
    ]
    est = TokenEstimator()
    # "hello world" = 11 * 0.3 = 3, "a"*40 = 40 * 0.3 = 12, total = 15
    assert est.estimate_messages(msgs) == 15


def test_compaction_policy_thresholds() -> None:
    policy = CompactionPolicy(context_window=125_000)
    assert policy.soft_limit == 87_500  # 125000 * 0.70
    assert policy.hard_limit == 125_000


def test_compaction_policy_from_model() -> None:
    model = LLMModel(
        id="m1", channel_id="c1", name="test",
        is_default=True, context_window=1_000_000,
    )
    policy = CompactionPolicy.from_model(model)
    assert policy.context_window == 1_000_000


def test_compaction_policy_custom_budget() -> None:
    policy = CompactionPolicy(context_window=125_000, tool_result_budget_chars=4_000, preserve_turns=2)
    assert policy.tool_result_budget_chars == 4_000
    assert policy.preserve_turns == 2


def test_tool_result_budget_truncates_large_results(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")

    long_content = "x" * 10_000
    tool_msg = add_message(
        paths.chat_path,
        conversation_id=conv.id,
        role="tool",
        content=json.dumps({"tool_use_id": "tc_1", "content": long_content}),
    )

    messages = list_messages(paths.chat_path, conversation_id=conv.id)
    api_messages = [{"role": "tool", "tool_use_id": "tc_1", "content": long_content}]
    policy = CompactionPolicy(context_window=125_000, tool_result_budget_chars=8_000)
    engine = CompactionEngine(paths.chat_path, conv.id)

    result = engine.compact_if_needed(messages, api_messages, policy, force=True)
    assert result.applied is True
    assert result.strategy == "tool_result_budget"

    updated = list_messages(paths.chat_path, conversation_id=conv.id)
    parsed = json.loads(updated[0].content)
    assert "truncated" in parsed["content"]
    assert len(parsed["content"]) < 10_000
    assert parsed["tool_use_id"] == "tc_1"


def test_tool_result_budget_skips_small_results(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")

    add_message(
        paths.chat_path,
        conversation_id=conv.id,
        role="tool",
        content=json.dumps({"tool_use_id": "tc_1", "content": "short output"}),
    )

    messages = list_messages(paths.chat_path, conversation_id=conv.id)
    api_messages = [{"role": "tool", "tool_use_id": "tc_1", "content": "short output"}]
    policy = CompactionPolicy(context_window=125_000)
    engine = CompactionEngine(paths.chat_path, conv.id)

    result = engine.compact_if_needed(messages, api_messages, policy)
    assert result.applied is False


def test_tool_result_budget_skips_non_tool_messages(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")

    add_message(
        paths.chat_path,
        conversation_id=conv.id,
        role="user",
        content="x" * 10_000,
    )

    messages = list_messages(paths.chat_path, conversation_id=conv.id)
    api_messages = [{"role": "user", "content": "x" * 10_000}]
    policy = CompactionPolicy(context_window=125_000)
    engine = CompactionEngine(paths.chat_path, conv.id)

    result = engine.compact_if_needed(messages, api_messages, policy)
    assert result.applied is False


def test_list_active_messages_no_compact(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")
    add_message(paths.chat_path, conversation_id=conv.id, role="user", content="hello")
    add_message(paths.chat_path, conversation_id=conv.id, role="assistant", content="hi")

    active = list_active_messages(paths.chat_path, conversation_id=conv.id)
    assert len(active) == 2


def test_list_active_messages_with_compact_boundary(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")

    # pre-compact messages
    add_message(paths.chat_path, conversation_id=conv.id, role="user", content="old msg 1")
    add_message(paths.chat_path, conversation_id=conv.id, role="assistant", content="old reply 1")

    # compact summary
    add_message(
        paths.chat_path,
        conversation_id=conv.id,
        role="system",
        content=json.dumps({"type": "compact_summary", "summary": "Summarized...", "summarized_count": 2}),
    )
    # compact boundary
    add_message(
        paths.chat_path,
        conversation_id=conv.id,
        role="system",
        content=json.dumps({
            "type": "compact_boundary",
            "boundary_id": "cb_1",
            "strategy": "autocompact_v1",
            "source_range_from": "m1",
            "source_range_to": "m2",
            "preserved_head_ids": [],
            "preserved_tail_id": "",
            "summary_msg_id": "sum1",
            "tokens_before": 1000,
            "tokens_after": 100,
        }),
    )

    # post-compact messages
    add_message(paths.chat_path, conversation_id=conv.id, role="user", content="new msg")
    add_message(paths.chat_path, conversation_id=conv.id, role="assistant", content="new reply")

    active = list_active_messages(paths.chat_path, conversation_id=conv.id)
    assert len(active) == 4  # summary + boundary + new user + new assistant

    all_msgs = list_messages(paths.chat_path, conversation_id=conv.id)
    assert len(all_msgs) == 6  # all messages still in DB


def test_update_message_content(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")
    msg = add_message(paths.chat_path, conversation_id=conv.id, role="user", content="original")

    update_message_content(paths.chat_path, message_id=msg.id, content="updated")

    msgs = list_messages(paths.chat_path, conversation_id=conv.id)
    assert msgs[0].content == "updated"


def test_compact_if_needed_below_threshold_noop(tmp_path: Path) -> None:
    paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
    conv = create_conversation(paths.chat_path, title="Test")
    add_message(paths.chat_path, conversation_id=conv.id, role="user", content="hi")

    messages = list_messages(paths.chat_path, conversation_id=conv.id)
    api_messages = [{"role": "user", "content": "hi"}]
    policy = CompactionPolicy(context_window=125_000)
    engine = CompactionEngine(paths.chat_path, conv.id)

    result = engine.compact_if_needed(messages, api_messages, policy)
    assert result.applied is False


def test_find_split_index() -> None:
    from flyinchat.models import Message

    msgs = [
        Message(id="1", conversation_id="c1", role="user", content="turn 1", created_at=""),
        Message(id="2", conversation_id="c1", role="assistant", content="reply 1", created_at=""),
        Message(id="3", conversation_id="c1", role="user", content="turn 2", created_at=""),
        Message(id="4", conversation_id="c1", role="assistant", content="reply 2", created_at=""),
        Message(id="5", conversation_id="c1", role="user", content="turn 3", created_at=""),
        Message(id="6", conversation_id="c1", role="assistant", content="reply 3", created_at=""),
    ]

    idx = CompactionEngine._find_split_index(msgs, preserve_turns=2)
    assert idx == 2  # keep last 2 turns (index 2 onwards: turn 2 + turn 3)


def test_compact_metadata_dataclass() -> None:
    meta = CompactMetadata(
        boundary_id="cb_1",
        strategy="autocompact_v1",
        source_range_from="m1",
        source_range_to="m10",
        preserved_head_ids=("m11", "m12"),
        preserved_tail_id="m12",
        summary_msg_id="sum1",
        tokens_before=50000,
        tokens_after=10000,
    )
    assert meta.strategy == "autocompact_v1"
    assert meta.tokens_before == 50000


def test_compaction_output_dataclass() -> None:
    output = CompactionOutput(
        applied=False,
        messages=(),
        tokens_before=1000,
    )
    assert output.applied is False
    assert output.boundary_message is None


def test_autocompact_summary_preserves_skill_state(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    async def run():
        paths = initialize_storage(resolve_app_paths(home=tmp_path / "home", cwd=tmp_path / "project"))
        conv = create_conversation(paths.chat_path, title="Test")
        add_message(paths.chat_path, conversation_id=conv.id, role="user", content="old")
        add_message(
            paths.chat_path,
            conversation_id=conv.id,
            role="system",
            subtype="skill_event",
            content=json.dumps({
                "event": "skill.resolve.complete",
                "applied_skills": ["safe-edit@0.1.0"],
                "active_phase": "validate",
                "guards_applied": [{"guard_id": "g1"}],
            }),
        )
        add_message(paths.chat_path, conversation_id=conv.id, role="user", content="new")

        captured: dict[str, str] = {}

        async def fake_chat_completion(channel, model, messages, max_tokens):
            captured["prompt"] = messages[0]["content"]
            return "summary"

        monkeypatch.setattr("flyinchat.compact.chat_completion", fake_chat_completion)
        engine = CompactionEngine(paths.chat_path, conv.id)
        model = LLMModel(id="m1", channel_id="c1", name="m", is_default=True, context_window=10)
        channel = LLMChannel(
            id="c1",
            name="c",
            provider_type="anthropic",
            base_url=None,
            api_key="sk-test",
            created_at="",
            updated_at="",
        )

        result = await engine._autocompact(
            list_messages(paths.chat_path, conversation_id=conv.id),
            [],
            CompactionPolicy(context_window=10, preserve_turns=1),
            model,
            channel,
            100,
        )

        assert result.applied is True
        assert "Skills applied: safe-edit@0.1.0" in captured["prompt"]
        assert "phase: validate" in captured["prompt"]

    asyncio.run(run())
