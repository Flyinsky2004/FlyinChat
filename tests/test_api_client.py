from flyinchat.api_client import _dedupe_stream_delta


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


def test_dedupe_stream_delta_keeps_normal_ascii_deltas() -> None:
    emitted = ""
    output = []

    for chunk in ("a", "and", " another"):
        delta = _dedupe_stream_delta(emitted, chunk)
        emitted += delta
        output.append(delta)

    assert "".join(output) == "aand another"
