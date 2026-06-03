from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from flyinchat.models import LLMChannel, LLMModel
from flyinchat.tools.convert import tools_to_api_format
from flyinchat.tools.core import Tool

logger = logging.getLogger("flyinchat.api_client")


def _dedupe_stream_delta(emitted: str, chunk: str) -> str:
    if not chunk:
        return ""
    if not emitted:
        return chunk
    if chunk.startswith(emitted):
        return chunk[len(emitted):]

    max_overlap = min(len(emitted), len(chunk))
    for size in range(max_overlap, 0, -1):
        if emitted.endswith(chunk[:size]):
            return chunk[size:]
    return chunk


async def stream_chat_completion(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    usage_info: dict | None = None,
    tools: list[Tool] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if channel.provider_type == "anthropic":
        async for event in _stream_anthropic(channel, model, messages, usage_info, tools):
            yield event
    else:
        async for event in _stream_openai_compatible(channel, model, messages, usage_info, tools):
            yield event


def _convert_messages_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for msg in messages:
        if msg["role"] == "tool":
            converted.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_use_id", ""),
                "content": msg["content"],
            })
        elif msg["role"] == "assistant" and isinstance(msg.get("content"), list):
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in msg["content"]:
                if block["type"] == "thinking":
                    reasoning = block.get("thinking", "")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                elif block["type"] == "text":
                    text_parts.append(block["text"])
                elif block["type"] == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })
            text_content = "\n".join(text_parts) if text_parts else ""
            converted_msg: dict[str, Any] = {"role": "assistant"}
            if reasoning_parts:
                converted_msg["reasoning_content"] = "\n".join(reasoning_parts)
            if tool_calls:
                converted_msg["tool_calls"] = tool_calls
            converted_msg["content"] = text_content or ""
            converted.append(converted_msg)
        else:
            converted.append(msg)
    return converted


async def _stream_openai_compatible(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    usage_info: dict | None = None,
    tools: list[Tool] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    base = channel.base_url.rstrip("/") if channel.base_url else ""
    url = f"{base}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model.name,
        "messages": _convert_messages_for_openai(messages),
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": model.max_output_tokens,
        "max_completion_tokens": model.max_output_tokens,
    }
    if model.thinking_enabled:
        body["reasoning_effort"] = model.reasoning_effort
        body["thinking"] = {"type": "enabled"}
    if tools:
        body["tools"] = tools_to_api_format(tools, "openai_compatible")

    logger.debug(
        "openai request",
        extra={
            "model": body["model"],
            "message_count": len(body["messages"]),
            "has_tools": tools is not None,
            "thinking": body.get("thinking"),
            "reasoning_effort": body.get("reasoning_effort"),
            "max_tokens": body.get("max_tokens"),
        },
    )

    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    reasoning_text = ""
    text_content = ""
    reasoning_done = False

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                error_text = error_body.decode(errors="replace")[:2000]
                logger.error(
                    "openai compatible request failed",
                    extra={
                        "url": url,
                        "status_code": response.status_code,
                        "model": body["model"],
                        "error_body": error_text,
                    },
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise httpx.HTTPStatusError(
                        f"{e}\nAPI response: {error_text}",
                        request=e.request,
                        response=e.response,
                    ) from None
            async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if "usage" in data and data["usage"] is not None and usage_info is not None:
                            usage_info.update(data["usage"])

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        finish_reason = choices[0].get("finish_reason")
                        if finish_reason:
                            logger.info(
                                "stream chunk finish_reason",
                                extra={"finish_reason": finish_reason},
                            )
                            if finish_reason == "length":
                                logger.warning(
                                    "model output truncated by token limit (finish_reason=length)",
                                    extra={"output_tokens_so_far": usage_info.get("completion_tokens", 0) if usage_info else 0},
                                )

                        delta = choices[0].get("delta", {})

                        rc = delta.get("reasoning_content", "")
                        if rc:
                            reasoning_delta = _dedupe_stream_delta(reasoning_text, rc)
                            reasoning_text += reasoning_delta

                        content = delta.get("content", "")
                        if content:
                            content_delta = _dedupe_stream_delta(text_content, content)
                            if content_delta:
                                if not reasoning_done and reasoning_text:
                                    reasoning_done = True
                                    yield {"type": "reasoning", "content": reasoning_text}
                                text_content += content_delta
                                yield {"type": "text", "content": content_delta}

                        tc_list = delta.get("tool_calls", [])
                        for tc in tc_list:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_by_index:
                                tool_calls_by_index[idx] = {"name": "", "id": "", "arguments": ""}
                            entry = tool_calls_by_index[idx]
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            if tc.get("function", {}).get("name"):
                                entry["name"] = tc["function"]["name"]
                            if tc.get("function", {}).get("arguments"):
                                arguments = tc["function"]["arguments"]
                                entry["arguments"] += _dedupe_stream_delta(entry["arguments"], arguments)

                        # try to finalize complete tool calls
                        finished_indices = []
                        for idx, entry in tool_calls_by_index.items():
                            if entry["arguments"]:
                                try:
                                    parsed = json.loads(entry["arguments"])
                                    yield {
                                        "type": "tool_use",
                                        "id": entry["id"],
                                        "name": entry["name"],
                                        "input": parsed,
                                    }
                                    finished_indices.append(idx)
                                except json.JSONDecodeError:
                                    pass
                        for idx in finished_indices:
                            del tool_calls_by_index[idx]

    # flush reasoning that wasn't yielded (no text, just tool calls)
    if reasoning_text and not reasoning_done:
        yield {"type": "reasoning", "content": reasoning_text}

    # flush remaining incomplete tool calls
    for entry in tool_calls_by_index.values():
        if entry["name"] and entry["arguments"]:
            try:
                parsed = json.loads(entry["arguments"])
                yield {"type": "tool_use", "id": entry["id"], "name": entry["name"], "input": parsed}
            except json.JSONDecodeError:
                logger.warning(
                    "stream ended with incomplete tool call, model output may have been truncated",
                    extra={"tool_name": entry["name"], "partial_args": entry["arguments"][:200]},
                )
                yield {"type": "incomplete_tool_call", "name": entry["name"]}


def _convert_messages_for_anthropic(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    tool_buffer: list[dict[str, Any]] = []

    def _flush_tools() -> None:
        if tool_buffer:
            converted.append({"role": "user", "content": list(tool_buffer)})
            tool_buffer.clear()

    for msg in messages:
        if msg["role"] == "system":
            content = msg.get("content", "")
            if content:
                system_parts.append(content)
        elif msg["role"] == "tool":
            tool_buffer.append({
                "type": "tool_result",
                "tool_use_id": msg.get("tool_use_id", ""),
                "content": msg["content"],
            })
        else:
            _flush_tools()
            content = msg.get("content", "")
            if isinstance(content, str):
                converted.append({"role": msg["role"], "content": content})
            else:
                converted.append({"role": msg["role"], "content": content})

    _flush_tools()
    system_prompt = "\n\n".join(system_parts) if system_parts else None
    return system_prompt, converted


class ToolPairError(Exception):
    """Raised when tool_use/tool_result pairing is invalid."""


def validate_tool_pairing(messages: list[dict[str, Any]]) -> None:
    """Validate tool_use/tool_result pairing on the Anthropic-converted message list.

    Must be called AFTER _convert_messages_for_anthropic, when tool messages
    have been converted to role="user" with tool_result content blocks.
    Raises ToolPairError if the structure is invalid.
    """
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "assistant":
            i += 1
            continue

        content = msg.get("content", "")
        tool_use_ids: list[str] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id", "")
                    if tid:
                        tool_use_ids.append(tid)

        if not tool_use_ids:
            i += 1
            continue

        # The next non-system message must be user with tool_result blocks
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "system":
            j += 1

        if j >= len(messages):
            raise ToolPairError(
                f"assistant has tool_use blocks {tool_use_ids} but no following message with tool_results"
            )

        next_msg = messages[j]
        if next_msg.get("role") != "user":
            raise ToolPairError(
                f"assistant has tool_use blocks {tool_use_ids} but next message is role='{next_msg.get('role')}' (expected user with tool_results)"
            )

        result_ids: list[str] = []
        next_content = next_msg.get("content", "")
        if isinstance(next_content, list):
            for block in next_content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    rid = block.get("tool_use_id", "")
                    if rid:
                        result_ids.append(rid)

        missing = set(tool_use_ids) - set(result_ids)
        extra = set(result_ids) - set(tool_use_ids)
        if missing:
            raise ToolPairError(
                f"tool_use ids {sorted(missing)} have no matching tool_result blocks. "
                f"Found tool_results for: {sorted(result_ids)}"
            )
        if extra:
            logger.warning(
                "tool_result blocks with no matching tool_use",
                extra={"extra_tool_result_ids": sorted(extra)},
            )

        i = j + 1


async def _stream_anthropic(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    usage_info: dict | None = None,
    tools: list[Tool] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    url = f"{channel.base_url.rstrip('/')}/v1/messages" if channel.base_url else "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": channel.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)
    validate_tool_pairing(anthropic_messages)

    body: dict[str, Any] = {
        "model": model.name,
        "max_tokens": model.max_output_tokens,
        "messages": anthropic_messages,
        "stream": True,
    }
    if system_prompt:
        body["system"] = system_prompt
    if model.thinking_enabled:
        body["thinking"] = {"type": "enabled"}
    if tools:
        body["tools"] = tools_to_api_format(tools, "anthropic")

    blocks: dict[int, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                error_text = error_body.decode(errors="replace")[:2000]
                logger.error(
                    "anthropic stream request failed",
                    extra={
                        "url": url,
                        "status_code": response.status_code,
                        "model": body["model"],
                        "error_body": error_text,
                    },
                )
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code} {response.reason_phrase}\nURL: {url}\n{error_text}",
                    request=response.request,
                    response=response,
                )
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    if event_type == "message_start" and usage_info is not None:
                        msg_data = data.get("message", {})
                        usage = msg_data.get("usage", {})
                        if not usage:
                            usage = data.get("usage", {})
                        if usage:
                            inp = usage.get("input_tokens") or usage.get("prompt_tokens", 0)
                            if inp:
                                usage_info["input_tokens"] = inp
                            out = usage.get("output_tokens") or usage.get("completion_tokens", 0)
                            if out:
                                usage_info["output_tokens"] = out
                            if not inp and not out:
                                logger.debug(
                                    "message_start usage keys not recognized",
                                    extra={"usage_keys": list(usage.keys())},
                                )

                    elif event_type == "message_delta" and usage_info is not None:
                        usage = data.get("usage", {})
                        if usage:
                            inp = usage.get("input_tokens") or usage.get("prompt_tokens", 0)
                            if inp:
                                usage_info["input_tokens"] = inp
                            out = usage.get("output_tokens") or usage.get("completion_tokens", 0)
                            if out:
                                usage_info["output_tokens"] = out

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        idx = data.get("index", 0)
                        bt = block.get("type", "")
                        if bt == "thinking":
                            blocks[idx] = {"type": "thinking", "thinking": "", "signature": ""}
                        elif bt == "tool_use":
                            blocks[idx] = {
                                "type": "tool_use",
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "json_fragments": [],
                            }

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        idx = data.get("index", 0)
                        dt = delta.get("type", "")
                        if dt == "text_delta":
                            yield {"type": "text", "content": delta.get("text", "")}
                        elif dt == "thinking_delta":
                            if idx in blocks:
                                blocks[idx]["thinking"] += delta.get("thinking", "")
                        elif dt == "signature_delta":
                            if idx in blocks:
                                blocks[idx]["signature"] = delta.get("signature", "")
                        elif dt == "input_json_delta":
                            if idx in blocks:
                                blocks[idx]["json_fragments"].append(delta.get("partial_json", ""))

                    elif event_type == "content_block_stop":
                        idx = data.get("index", 0)
                        if idx in blocks:
                            block = blocks.pop(idx)
                            if block["type"] == "thinking":
                                yield {
                                    "type": "thinking",
                                    "thinking": block["thinking"],
                                    "signature": block["signature"],
                                }
                            elif block["type"] == "tool_use":
                                json_str = "".join(block["json_fragments"])
                                try:
                                    parsed = json.loads(json_str)
                                    yield {
                                        "type": "tool_use",
                                        "id": block["id"],
                                        "name": block["name"],
                                        "input": parsed,
                                    }
                                except json.JSONDecodeError:
                                    pass


async def chat_completion(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 2048,
) -> str:
    """Non-streaming chat completion for summarization."""
    if channel.provider_type == "anthropic":
        return await _anthropic_chat(channel, model, messages, max_tokens)
    return await _openai_chat(channel, model, messages, max_tokens)


async def _openai_chat(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    base = channel.base_url.rstrip("/") if channel.base_url else ""
    url = f"{base}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model.name,
        "messages": _convert_messages_for_openai(messages),
        "stream": False,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            error_text = response.text[:2000]
            logger.error(
                "openai chat request failed",
                extra={
                    "url": url,
                    "status_code": response.status_code,
                    "model": body["model"],
                    "error_body": error_text,
                },
            )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


async def _anthropic_chat(
    channel: LLMChannel,
    model: LLMModel,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    url = f"{channel.base_url.rstrip('/')}/v1/messages" if channel.base_url else "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": channel.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    system_prompt, anthropic_messages = _convert_messages_for_anthropic(messages)
    body: dict[str, Any] = {
        "model": model.name,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
        "stream": False,
    }
    if system_prompt:
        body["system"] = system_prompt
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            error_text = response.text[:2000]
            logger.error(
                "anthropic chat request failed",
                extra={
                    "url": url,
                    "status_code": response.status_code,
                    "model": body["model"],
                    "error_body": error_text,
                },
            )
        response.raise_for_status()
        data = response.json()
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""
