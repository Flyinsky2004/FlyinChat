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
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
