# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_query_engine.py

# Run a single test by name
pytest tests/test_query_engine.py -k "test_submit_message"

# Run with verbose output
pytest -v
```

The project uses `pytest` with `pytest-asyncio`. Python path is configured in `pyproject.toml` (`pythonpath = ["src"]`, `testpaths = ["tests"]`).

## Run the App

```bash
flyinchat          # if installed
python -m flyinchat
```

## Architecture

FlyinChat is a **terminal-based AI coding assistant TUI** built with [Textual](https://textual.textualize.io/). It connects to LLM APIs (Anthropic, OpenAI-compatible, DeepSeek) and provides a Claude Code-like tool-use loop with streaming responses, permission gating, and MCP server support.

### Data Flow (per user message)

```
app.py (TUI) → QueryEngine → API Client → LLM API (streaming)
                   ↕
              ToolExecutor → Tool.run()   (bash, file ops, MCP, etc.)
                   ↕
              Storage (JSON persistence)
```

1. **app.py**: Textual TUI — chat view, command menu, selection UI, permission dialogs, `@` file mentions. Handles user input and delegates to `QueryEngine`.
2. **query_engine.py** (`QueryEngine`): Orchestrates the turn loop: streams LLM responses, parses tool calls, executes tools via `ToolExecutor`, handles permission requests and user input prompts, manages auto-compaction and auto-continue on context/turn budget exhaustion.
3. **api_client.py**: Dual-provider streaming (`stream_chat_completion`) and non-streaming (`chat_completion`) clients. Converts internal message format to/from Anthropic and OpenAI-compatible wire formats.
4. **tools/core.py**: `Tool` protocol, `ToolRegistry`, `ToolExecutor` with three-layer permission model (allow/ask/deny sets, command auto-allowlist, skill runtime guards).
5. **compact.py**: Context window management — `CompactionEngine` applies tool-result truncation (soft limit) or LLM-based summarization (hard limit) via `CompactionPolicy`.

### Key Modules

| Module | Purpose |
|--------|---------|
| `storage.py` | JSON file-based CRUD for conversations, messages, LLM channels/models. Atomic writes via temp-file + `os.replace`. Supports migration from legacy SQLite. |
| `prompt_assembler.py` | Builds system prompt from layered sections: base + mode + safety policy + skill injection + compact summary. |
| `models.py` | Immutable dataclasses: `LLMChannel`, `LLMModel`, `Conversation`, `Message`, `TurnResult`. |
| `paths.py` | `AppPaths` — resolves global config (`~/.flyinchat/config.json`) and per-project chat storage (`.flyinchat/chat.json`). |
| `message_utils.py` | Converts between internal `Message` and API-ready dict format. |
| `file_mentions.py` | `@`-triggered file path autocomplete (parses cursor position, suggests workspace paths). |
| `mcp/` | MCP client integration — `adapter.py` wraps MCP tools as `Tool` protocol, `config.py` parses server configs, `manager.py` handles server lifecycle. |
| `skills/` | Skill system — `parser.py` reads YAML/Markdown skill files, `resolver.py` matches user query to skills, `compiler.py` produces planning guidance + runtime guards, `guards.py` enforces tool constraints per-turn. |
| `i18n/` | String store with English and Chinese translations. |
| `tools/` | Concrete tool implementations: `bash_tool.py`, `file_tools.py` (read/write), `edit_tools.py` (inline edit), `glob_tool.py`, `grep_tool.py`, `web_tools.py`, `plan_tools.py` (todo_write, enter/exit_plan_mode), `ask_tool.py`, `convert.py` (tool schema → API format). |

### Mode System (Shift+Tab cycles)

| Mode | Auto-allowed | Ask | Denied |
|------|-------------|-----|--------|
| 0 Normal | read, glob, grep, todo, ask_user | write, edit, bash, web, plan | — |
| 1 Auto-edit | read, write, edit, glob, grep, todo, ask_user | bash, web, plan | — |
| 2 Yolo | all | — | — |
| 3 Plan | read, glob, grep, todo, ask_user, plan | bash, web | write, edit |

Modes are enforced at two levels: proactively via system prompt (`prompt_assembler.py`) and reactively via `PermissionContext` in `ToolExecutor`.

### Permission System

`ToolExecutor.execute()` runs a three-layer gate:
1. **Skill guards** (`evaluate_skill_guards`) — turn-level constraints from loaded skills
2. **Mode policy** (`_tool_allowed`) — allowed/ask/deny sets from `PermissionContext`
3. **Tool self-check** (`tool.requires_permission()`) — input-level risk assessment (e.g., bash inspects the command)

Denied tools return `PERMISSION_REQUIRED` which triggers a user-facing dialog in the TUI. Approved tools proceed via `execute_approved()`. The executor also maintains a `command_auto_allowlist` (seeded with read-only commands) and `_auto_allow_tools` set (for MCP tools).

### Storage Format

Both config and chat use flat JSON files with atomic writes (write temp → `os.replace`). Key paths:
- `~/.flyinchat/config.json` — LLM channels, models, app settings, MCP server configs
- `<project>/.flyinchat/chat.json` — conversations and messages

The `list_active_messages()` function returns only messages after the last compaction boundary, skipping compacted history.

### Provider Support

- **Anthropic**: Native Messages API with thinking blocks and streaming via SSE
- **OpenAI-compatible**: Standard chat completions API with reasoning support
- **DeepSeek**: Configured as preset using Anthropic-compatible endpoint (`PROVIDER_PRESETS`)

Message format conversion happens in `api_client.py`:
- Anthropic: system prompt separated from messages, tool results grouped into user content blocks, `validate_tool_pairing()` ensures valid tool_use/tool_result interleaving
- OpenAI: tool calls as `tool_calls[]` array, reasoning content in `reasoning_content` field, tool results as role `tool`

### Skill System

Skills are loaded from `<workspace>/.flyinchat/skills/` (glob: `*.md`, `*.skill.md`). Each skill defines modes, constraints, workflows, and verification checklists. Per turn, `SkillResolver` matches the user query against the skill catalog, and `SkillCompiler` produces:
- **Planning injection**: injected into the system prompt as active skill guidance
- **Runtime guards**: per-tool constraints enforced in `ToolExecutor.execute()`

### Internationalization

String keys are defined in `i18n/keys.py` as a `TKey` enum. Translations live in `i18n/en.py` and `i18n/zh.py`. Access via `I18nStore.t(TKey.KEY_NAME)`. The `/language` command toggles between EN and ZH.

## Project Dependencies

- **textual** — TUI framework
- **httpx** — async HTTP client for LLM APIs
- **mcp** — Model Context Protocol Python SDK for tool server integration
