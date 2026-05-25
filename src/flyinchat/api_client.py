import json
from collections.abc import AsyncIterator

import httpx

from .models import LLMChannel, LLMModel


async def stream_chat_completion(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    if channel.provider_type == "anthropic":
        async for token in _stream_anthropic(channel, model, messages):
            yield token
    else:
        async for token in _stream_openai_compatible(channel, model, messages):
            yield token


async def _stream_openai_compatible(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    base = channel.base_url.rstrip("/") if channel.base_url else ""
    url = f"{base}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model.name,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue


async def _stream_anthropic(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": channel.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    system_prompt: str | None = None
    anthropic_messages: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_prompt = msg["content"]
        else:
            anthropic_messages.append({"role": msg["role"], "content": msg["content"]})

    body: dict = {
        "model": model.name,
        "max_tokens": 4096,
        "messages": anthropic_messages,
        "stream": True,
    }
    if system_prompt:
        body["system"] = system_prompt

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            text = data.get("delta", {}).get("text", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue
