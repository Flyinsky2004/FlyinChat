from dataclasses import dataclass


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
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    total_output_tokens: int = 0
    last_input_tokens: int = 0
    compacted_message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
