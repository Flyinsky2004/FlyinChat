from .keys import TKey

EN: dict[TKey, str] = {
    # ── Commands ──
    TKey.CMD_API: "/api",
    TKey.CMD_API_DESC: "LLM API provider settings",
    TKey.CMD_MODEL: "/model",
    TKey.CMD_MODEL_DESC: "Choose the primary model",
    TKey.CMD_THINKING: "/thinking",
    TKey.CMD_THINKING_DESC: "Toggle reasoning thinking mode on/off",
    TKey.CMD_REASONING: "/reasoning",
    TKey.CMD_REASONING_DESC: "Set reasoning effort level (low/medium/high)",
    TKey.CMD_EFFORT: "/effort",
    TKey.CMD_EFFORT_DESC: "Switch thinking effort level (low/medium/high/xhigh)",
    TKey.CMD_1M: "/1M",
    TKey.CMD_1M_DESC: "Toggle 1M context window mode (125K ↔ 1M)",
    TKey.CMD_SESSIONS: "/sessions",
    TKey.CMD_SESSIONS_DESC: "Open project session history",
    TKey.CMD_CLEAR: "/clear",
    TKey.CMD_CLEAR_DESC: "Start a new session",
    TKey.CMD_COMPACT: "/compact",
    TKey.CMD_COMPACT_DESC: "Compact conversation history",
    TKey.CMD_LANGUAGE: "/language",
    TKey.CMD_LANGUAGE_DESC: "Switch interface language (EN / 中文)",
    TKey.CMD_INIT: "/init",
    TKey.CMD_INIT_DESC: "Generate/update FLYINCHAT.md project memory file",
    TKey.CMD_MCP: "/mcp",
    TKey.CMD_MCP_DESC: "View MCP server status and tool list",
    TKey.CMD_SKILLS: "/skills",
    TKey.CMD_SKILLS_DESC: "View loaded Agent Skills",

    # ── Reasoning levels ──
    TKey.REASONING_LOW: "Fast, minimal reasoning",
    TKey.REASONING_MED: "Balanced reasoning",
    TKey.REASONING_HIGH: "Deep, thorough reasoning",

    # ── Effort levels ──
    TKey.EFFORT_LOW: "Thinking off, minimal reasoning",
    TKey.EFFORT_MED: "Thinking on, balanced reasoning",
    TKey.EFFORT_HIGH: "Thinking on, deep reasoning",
    TKey.EFFORT_XHIGH: "Thinking on, maximum reasoning",

    # ── API actions ──
    TKey.API_DEEPSEEK_TITLE: "Add DeepSeek preset",
    TKey.API_DEEPSEEK_DESC: "Only asks for an API key",
    TKey.API_OPENAI_TITLE: "Add OpenAI-compatible channel",
    TKey.API_OPENAI_DESC: "Name, base URL, API key, models",
    TKey.API_ANTHROPIC_TITLE: "Add Anthropic channel",
    TKey.API_ANTHROPIC_DESC: "Name, API key, models",

    # ── Role labels ──
    TKey.LABEL_YOU: "You",
    TKey.LABEL_ASSISTANT: "Assistant",
    TKey.LABEL_TOOL: "Tool",
    TKey.LABEL_SYSTEM: "System",
    TKey.LABEL_MESSAGE: "Message",

    # ── Placeholders ──
    TKey.PLACEHOLDER_INPUT: "Ask FlyinChat anything, or type / for commands",
    TKey.PLACEHOLDER_PERMISSION: "Press Enter to approve, n to deny",

    # ── Empty state ──
    TKey.EMPTY_HINT: "Start a project-local conversation from the prompt below.",

    # ── Command menu ──
    TKey.CMENU_NO_MATCHES: "No matching commands\nType /api, /model, /sessions, or /clear",
    TKey.CMENU_COMMANDS: "Commands",
    TKey.CMENU_FOOTER: "Use ↑/↓ to select, Tab to autocomplete, Enter to open.",
    TKey.FILE_MENTION_TITLE: "Workspace paths",
    TKey.FILE_MENTION_FOOTER: "Use ↑/↓ to select, Enter or Tab to insert the path.",
    TKey.FILE_MENTION_NO_MATCHES: "No matching files or folders for @{query}",
    TKey.FILE_MENTION_FILE: "file",
    TKey.FILE_MENTION_DIR: "directory",

    # ── Panels ──
    TKey.PANEL_UNKNOWN_CMD: "Unknown command",
    TKey.PANEL_UNKNOWN_CMD_BODY: "No command named {command}. Type / to see available commands.",
    TKey.PANEL_API_SETUP_ERR: "API setup error",
    TKey.PANEL_API_CHANNEL_ADDED: "API channel added",
    TKey.PANEL_PRIMARY_MODEL: "Primary model",
    TKey.PANEL_NO_PROVIDERS: "No API providers configured yet. Add one with /api.",
    TKey.PANEL_MODEL_SELECT_ERR: "Model selection error",
    TKey.PANEL_MODEL_SELECT_USAGE: "Usage: /model use <channel> <model>",
    TKey.PANEL_SESSION_HISTORY: "Session history",
    TKey.PANEL_NO_SESSIONS: "No project-local sessions yet. Send a message to create one.",
    TKey.PANEL_NEW_SESSION: "New session",
    TKey.PANEL_NEW_SESSION_BODY: "Ready for a new project-local conversation.",
    TKey.PANEL_COMPACT: "Compact",
    TKey.PANEL_NO_CONVERSATION: "No active conversation to compact.",
    TKey.PANEL_NO_MODEL: "No model configured. Add one with `/api`, then `/model`.",
    TKey.PANEL_COMPACT_OK: "Already compacted — {tokens}K tokens is within budget ({limit}K limit).",
    TKey.PANEL_COMPACT_DONE: "Conversation compacted",
    TKey.PANEL_COMPACT_NOT_NEEDED: "Compaction not needed — conversation is within token budget.",
    TKey.PANEL_INPUT_REQUIRED: "Input required",
    TKey.PANEL_INPUT_PROMPT: "Please enter a value to continue.",
    TKey.PANEL_ADD_API: "Add API channel",
    TKey.PANEL_THINKING_MODE: "Thinking mode",
    TKey.PANEL_THINKING_NO_MODEL: "No primary model configured. Set one with /model.",
    TKey.PANEL_REASONING_EFFORT: "Reasoning effort",
    TKey.PANEL_REASONING_NO_MODEL: "No primary model configured. Set one with /model.",
    TKey.PANEL_EFFORT_LEVEL: "Effort level",
    TKey.PANEL_EFFORT_NO_MODEL: "No primary model configured. Set one with /model.",
    TKey.PANEL_CTX_WINDOW: "Context window",
    TKey.PANEL_CTX_NO_MODEL: "No primary model configured. Set one with /model.",
    TKey.PANEL_INIT: "Project Initialization",
    TKey.PANEL_INIT_BODY: "Exploring project structure and generating FLYINCHAT.md...",
    TKey.PANEL_INIT_NO_MODEL: "No primary model configured. Please add one with /api first, then select it with /model.",
    TKey.PANEL_INIT_DONE: "FLYINCHAT.md has been generated in the workspace root.",
    TKey.PANEL_SKILLS: "Agent Skills",
    TKey.PANEL_SKILLS_EMPTY: "No skills loaded. Add SKILL.md files under `skills/**/SKILL.md` in the workspace or `~/.flyinchat/skills`.",

    # ── API form ──
    TKey.FORM_DEEPSEEK_KEY: "DeepSeek API key",
    TKey.FORM_OPENAI_NAME: "Channel name",
    TKey.FORM_OPENAI_URL: "Base URL",
    TKey.FORM_OPENAI_KEY: "API key",
    TKey.FORM_OPENAI_MODELS: "Models, comma separated",
    TKey.FORM_ANTHROPIC_NAME: "Channel name",
    TKey.FORM_ANTHROPIC_KEY: "API key",
    TKey.FORM_ANTHROPIC_MODELS: "Models, comma separated",
    TKey.FORM_DEEPSEEK_TITLE: "DeepSeek preset",
    TKey.FORM_OPENAI_TITLE: "OpenAI-compatible channel",
    TKey.FORM_ANTHROPIC_TITLE: "Anthropic channel",
    TKey.FORM_STEP: "Step {step}/{total}: {field}",

    # ── Selection UI ──
    TKey.SEL_API_TITLE: "LLM API providers",
    TKey.SEL_API_HEADER: "Configured channels\n{channels}\n\nPresets\n{presets}\n",
    TKey.SEL_API_FOOTER: "Use ↑/↓ to choose an action, Enter to continue.",
    TKey.SEL_MODEL_TITLE: "Primary model",
    TKey.SEL_MODEL_HEADER: "Configured provider models",
    TKey.SEL_MODEL_FOOTER: "Use ↑/↓ to choose a model, Enter to set primary.",
    TKey.SEL_THINKING_TITLE: "Thinking mode",
    TKey.SEL_THINKING_ON: "Enable thinking",
    TKey.SEL_THINKING_ON_DESC: "Turn reasoning thinking on",
    TKey.SEL_THINKING_OFF: "Disable thinking",
    TKey.SEL_THINKING_OFF_DESC: "Turn reasoning thinking off",
    TKey.SEL_THINKING_FOOTER: "Use ↑/↓ to choose, Enter to toggle.",
    TKey.SEL_REASONING_TITLE: "Reasoning effort",
    TKey.SEL_REASONING_FOOTER: "Use ↑/↓ to choose, Enter to set.",
    TKey.SEL_EFFORT_TITLE: "Effort level",
    TKey.SEL_EFFORT_FOOTER: "Use ↑/↓ to choose, Enter to set.",
    TKey.SEL_SESSION_TITLE: "Session history",
    TKey.SEL_SESSION_FOOTER: "Use ↑/↓ to choose a session, Enter to select.",
    TKey.SEL_MCP_TITLE: "MCP Servers",
    TKey.SEL_MCP_FOOTER: "Use ↑/↓ to choose a server, Enter to view details.",

    # ── MCP panels ──
    TKey.PANEL_MCP_DETAIL: "MCP Server Detail",
    TKey.PANEL_MCP_NO_SERVERS: "No MCP servers configured.\n\nAdd servers to the `mcp_servers` field in `~/.flyinchat/config.json`.",
    TKey.PANEL_MCP_STATUS_CONNECTED: "Connected",
    TKey.PANEL_MCP_STATUS_ERROR: "Connection error",
    TKey.PANEL_MCP_STATUS_CONNECTING: "Connecting",
    TKey.PANEL_MCP_STATUS_DISCONNECTED: "Disconnected",
    TKey.PANEL_MCP_RECONNECT: "Reconnect",
    TKey.PANEL_MCP_RECONNECTING: "Reconnecting {name}...",
    TKey.PANEL_MCP_RECONNECT_OK: "Reconnected successfully, {count} tools registered",
    TKey.PANEL_MCP_BACK: "Back",
    TKey.PANEL_MCP_ACTION_TITLE: "MCP Action",

    # ── Status bar ──
    TKey.STATUS_WORKING: "Working",
    TKey.STATUS_COMPACTING: "Compacting conversation history...",
    TKey.STATUS_NO_MODEL: "No model configured — use /api then /model",
    TKey.STATUS_THINK: "Think: {status}",
    TKey.STATUS_NO_CONV: "No conversation",
    TKey.STATUS_MSGS: "{count} msgs",
    TKey.STATUS_MODE_NORMAL: "NORMAL",
    TKey.STATUS_MODE_AUTO_EDIT: "AUTO EDIT",
    TKey.STATUS_MODE_YOLO: "YOLO",
    TKey.STATUS_MODE_PLAN: "PLAN",

    # ── Thinking / Effort hints ──
    TKey.HINT_THINKING_ON: "> Thinking is now **enabled** for {channel} / {model}",
    TKey.HINT_THINKING_OFF: "> Thinking is now **disabled** for {channel} / {model}",
    TKey.HINT_REASONING_SET: "> Reasoning effort set to **{effort}** for {channel} / {model}",
    TKey.HINT_EFFORT_ON: "> Effort set to **think on, {effort}** for {channel} / {model}",
    TKey.HINT_EFFORT_OFF: "> Effort set to **think off (low)** for {channel} / {model}",
    TKey.HINT_CTX_SET: "> Context window set to **{label}** for {channel} / {model}",
    TKey.HINT_PRIMARY_MODEL: "> Primary model set to **{channel} / {model}**",
    TKey.HINT_LANGUAGE_SET: "Language set to English",

    # ── Permission request ──
    TKey.PERM_TITLE: "## Permission Required\n\n**Tool:** {tool}\n\n**Risk:** {risk}\n\n**Args:** `{args}`\n\n**Reason:** {reason}\n\n---\nPress **Enter** to approve, or **n** to deny",
    TKey.PERM_LABEL: "Permission required",
    TKey.PERM_PLACEHOLDER: "Press Enter to approve, n to deny",
    TKey.PERM_APPROVE: "Approve - allow this tool to execute",
    TKey.PERM_ALWAYS_APPROVE: "Always Allow - auto-approve this command type",
    TKey.PERM_DENY: "Deny - block this tool call",
    TKey.PERM_ACTION_TITLE: "Action required",
    TKey.PERM_ACTION_FOOTER: "↑/↓ select  |  Enter confirm  |  y=approve  a=always allow  n=deny  esc=deny",

    # ── Risk badges ──
    TKey.RISK_LOW: "LOW",
    TKey.RISK_MEDIUM: "MEDIUM",
    TKey.RISK_HIGH: "HIGH",

    # ── Todo panel ──
    TKey.TODO_TITLE: "Plan",
    TKey.TODO_EMPTY: "No active plan",

    # ── Misc ──
    TKey.MISC_NO_MESSAGES: "_No messages_",
    TKey.MISC_NO_PROVIDERS: "No providers configured yet.",
    TKey.MISC_NO_PROVIDERS_ADD: "No providers configured yet. Select a preset below to add one.",
    TKey.MISC_DEFAULT_ENDPOINT: "default endpoint",
    TKey.MISC_NO_MODELS: "No models",
    TKey.MISC_CONFIGURED: "configured",
    TKey.MISC_PRIMARY_MARKER: " [primary]",
    TKey.MISC_MODEL_ROW: "   {ci}.{mi} {name}{marker}",
    TKey.MISC_ERROR_PREFIX: "*[Error: {error}]*",

    # ── Init prompt ──
    TKey.INIT_PROMPT: (
        "You are executing a project initialization task. Your goal is to generate or update "
        "a FLYINCHAT.md file in the workspace root, which will serve as the project constraint "
        "document for future AI collaboration.\n\n"
        "Requirements:\n"
        "1. First, explore the project by reading key files (README, package config, source "
        "structure, test config, lint config) before writing anything. Do NOT fabricate commands "
        "or tech stack.\n"
        "2. The FLYINCHAT.md must cover:\n"
        "   - Project overview and goals\n"
        "   - Directory structure and key modules\n"
        "   - Install/run/test commands\n"
        "   - Code conventions and commit conventions\n"
        "   - Common risks and prohibited actions\n"
        "   - Recommended workflow (e.g., plan first, then change)\n"
        "3. Mark uncertain information clearly as \"TODO:待确认\" and suggest how to verify it.\n"
        "4. Output as clean, well-structured Markdown saved to FLYINCHAT.md in the workspace root.\n"
        "5. Keep it concise, actionable, and maintainable.\n"
        "6. If FLYINCHAT.md already exists, preserve valid rules and make incremental improvements "
        "rather than rewriting everything."
    ),

    # ── Compact engine ──
    TKey.COMPACT_SUMMARY_PROMPT: (
        "Please summarize the following conversation history into a concise summary. Preserve:\n"
        "- The user's main requests and goals\n"
        "- The tools used by the assistant and their key results\n"
        "- Important decisions and conclusions\n"
        "The summary should be concise but should not lose key information."
    ),
    TKey.COMPACT_ROLE_USER: "User",
    TKey.COMPACT_ROLE_ASSISTANT: "Assistant",
    TKey.COMPACT_ROLE_TOOL: "Tool",
    TKey.COMPACT_ROLE_SYSTEM: "System",
    TKey.COMPACT_CONVERSATION_HISTORY: "Conversation history:",
    TKey.COMPACT_OUTPUT_SUMMARY: "Please output the summary:",
}
