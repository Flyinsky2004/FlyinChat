<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/main.png" alt="FlyinChat" width="600">
</p>

<p align="center">
  <strong>Terminal-first AI coding assistant</strong><br>
  A Textual TUI for multi-provider LLM conversations with tool-use, MCP servers, and skills.
</p>

---

## Quick Start

```bash
# Install
pip install flyinchat

# Launch in your project
cd my-project
flyinchat
```

First run: use `/api add` to configure an API provider, `/model use` to pick a model, then start chatting.

## Screenshots

<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/chat1.png" alt="FlyinChat Chat Session" width="800">
</p>

<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/chat2.png" alt="FlyinChat with Todo Panel and Permissions" width="800">
</p>

## Supported Providers

- **Anthropic** — Claude models with extended thinking, streaming
- **OpenAI-compatible** — DeepSeek, Groq, local models via Ollama / vLLM, and any `/v1/chat/completions` endpoint
- **DeepSeek** — Built-in preset (Anthropic-compatible endpoint, 1M context)

Add providers with `/api add` and switch models with `/model use`.

## Modes

Toggle with `Shift+Tab` to control tool permissions per conversation:

| Mode | Behavior |
|------|----------|
| **Normal** | Read/search tools auto-run; write, bash, web tools require approval |
| **Auto-edit** | File edit/write auto-run; bash and web still ask |
| **Yolo** | All tools run without prompts |
| **Plan** | Read-only — analyze, plan, gather context only |

Permissions are enforced in the system prompt **and** at the tool execution layer.

## Features

- **Streaming chat** with real-time token counter and spinner
- **Tool-use loop** — file read/write/edit, bash, glob, grep, web fetch/search
- **Permission system** — approve once, always allow, or deny; command allowlist for bash auto-approval
- **@ file mentions** — type `@` to autocomplete workspace paths
- **Todo tracking** — live panel showing pending/in-progress/completed tasks
- **Auto-compaction** — tool result truncation (soft limit) and LLM summarization (hard limit) keep context under budget
- **Auto-continue** — automatically extends the turn budget when the model needs more iterations
- **MCP servers** — connect Model Context Protocol servers; tools register as native FlyinChat tools with permission gating
- **Skills** — load `.skill.md` files from `.flyinchat/skills/` with workflow guidance and runtime tool guards
- **i18n** — English and Chinese (`/language` to toggle)
- **Multiple sessions** — create and switch between conversations with `/sessions`

## Commands

| Command | Action |
|---------|--------|
| `/api` | Manage API providers |
| `/model` | Select active model |
| `/thinking` | Toggle extended thinking on/off |
| `/reasoning` | Set reasoning effort (low / medium / high) |
| `/effort` | Unified thinking + effort control |
| `/1M` | Toggle context window (125K ↔ 1M) |
| `/sessions` | List and switch conversations |
| `/clear` | Start a new session |
| `/compact` | Force context compaction |
| `/language` | Toggle English / Chinese |
| `/mcp` | View and manage MCP servers |
| `/skills` | List loaded skills |
| `/init` | Auto-initialize the project (creates CLAUDE.md, .gitignore, etc.) |

## Storage

- `~/.flyinchat/config.json` — LLM channels, models, app settings, MCP server configs
- `<project>/.flyinchat/chat.json` — conversation history (one file per project)

All data is persisted as JSON with atomic writes.

## Development

```bash
git clone https://github.com/FlyinSky2004/FlyinChat.git
cd FlyinChat
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest
pytest tests/test_query_engine.py -v
```

Python 3.11+ required. Built with [Textual](https://textual.textualize.io/), [httpx](https://www.python-httpx.org/), and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## License

FlyinChat is licensed under the [GNU Affero General Public License v3.0](LICENSE) — you may use, modify, and distribute this software freely, provided that any modifications you make and distribute (including network-based use) are also released under the same license.
