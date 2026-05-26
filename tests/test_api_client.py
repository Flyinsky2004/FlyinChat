from flyinchat.api_client import _convert_messages_for_openai, _dedupe_stream_delta


def test_dedupe_stream_delta_handles_snapshot_chunks() -> None:
    emitted = ""
    output = []

    for chunk in (
        "你好",
        "你好！",
        "很高兴",
        "很高兴见到",
        "你",
        "你。",
        "我是 ** Cl",
        "Claude",
        "aude**，由 Anthrop",
        "Anthropic 开发",
    ):
        delta = _dedupe_stream_delta(emitted, chunk)
        emitted += delta
        output.append(delta)

    assert "".join(output) == "你好！很高兴见到你。我是 ** Claude**，由 Anthropic 开发"


def test_dedupe_stream_delta_handles_single_char_overlap() -> None:
    emitted = ""
    output = []

    for chunk in ("a", "and", " another"):
        delta = _dedupe_stream_delta(emitted, chunk)
        emitted += delta
        output.append(delta)

    assert "".join(output) == "and another"


def test_convert_messages_for_openai_preserves_reasoning_for_tool_calls() -> None:
    converted = _convert_messages_for_openai([
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "need to inspect files", "signature": ""},
                {"type": "tool_use", "id": "call_1", "name": "file_read", "input": {"path": "a.py"}},
            ],
        },
        {"role": "tool", "tool_use_id": "call_1", "content": "1|print('hi')"},
    ])

    assert converted[0] == {
        "role": "assistant",
        "reasoning_content": "need to inspect files",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "file_read", "arguments": '{"path": "a.py"}'},
            }
        ],
        "content": None,
    }
    assert converted[1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "1|print('hi')",
    }


def test_convert_messages_for_openai_preserves_reasoning_for_normal_assistant() -> None:
    converted = _convert_messages_for_openai([
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "answer directly", "signature": ""},
                {"type": "text", "text": "hello"},
            ],
        }
    ])

    assert converted == [
        {
            "role": "assistant",
            "reasoning_content": "answer directly",
            "content": "hello",
        }
    ]


def test_convert_multi_round_tool_call_with_reasoning() -> None:
    converted = _convert_messages_for_openai([
        {"role": "user", "content": "read test.txt"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "need to read the file", "signature": ""},
                {"type": "tool_use", "id": "call_1", "name": "file_read", "input": {"path": "test.txt"}},
            ],
        },
        {"role": "tool", "tool_use_id": "call_1", "content": "file content here"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "I see the content, answer now", "signature": ""},
                {"type": "text", "text": "The file says: file content here"},
            ],
        },
    ])

    assert converted == [
        {"role": "user", "content": "read test.txt"},
        {
            "role": "assistant",
            "reasoning_content": "need to read the file",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": '{"path": "test.txt"}'},
                }
            ],
            "content": None,
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "file content here"},
        {
            "role": "assistant",
            "reasoning_content": "I see the content, answer now",
            "content": "The file says: file content here",
        },
    ]


def test_reasoning_content_always_preserved_from_history() -> None:
    """reasoning_content is part of the historical message, always passed back."""
    converted = _convert_messages_for_openai([
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hidden reasoning", "signature": ""},
                {"type": "tool_use", "id": "call_1", "name": "file_read", "input": {"path": "a.py"}},
            ],
        }
    ])

    assert converted == [
        {
            "role": "assistant",
            "reasoning_content": "hidden reasoning",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": '{"path": "a.py"}'},
                }
            ],
            "content": None,
        }
    ]
