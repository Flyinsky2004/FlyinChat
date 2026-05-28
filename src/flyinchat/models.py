from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMChannel:
    id: str
    name: str
    provider_type: str
    base_url: str | None
    api_key: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LLMModel:
    id: str
    channel_id: str
    name: str
    is_default: bool
    thinking_enabled: bool = True
    reasoning_effort: str = "high"
    context_window: int = 125_000
    max_output_tokens: int = 384_000
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    total_output_tokens: int = 0
    last_input_tokens: int = 0
    compacted_message_count: int = 0
    current_turn: int = 0
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    turn_id: str = ""
    subtype: str = "normal"
    tool_call_id: str | None = None
    meta: str = "{}"


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    status: str  # "completed" | "error" | "cancelled" | "max_rounds"
    final_text: str = ""
    tool_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    num_turns: int = 0
    max_turns: int = 0
    terminal_reason: str | None = None
    last_tool_error: str | None = None


@dataclass(frozen=True)
class SessionConfigSnapshot:
    model_name: str
    channel_name: str
    provider_type: str
    thinking_enabled: bool = True
    reasoning_effort: str = "high"
    context_window: int = 125_000
    max_tool_rounds: int = 10
