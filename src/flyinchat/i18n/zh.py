from .keys import TKey

ZH: dict[TKey, str] = {
    # ── Commands ──
    TKey.CMD_API: "/api",
    TKey.CMD_API_DESC: "LLM API 提供商设置",
    TKey.CMD_MODEL: "/model",
    TKey.CMD_MODEL_DESC: "选择主模型",
    TKey.CMD_THINKING: "/thinking",
    TKey.CMD_THINKING_DESC: "切换推理思考模式 开/关",
    TKey.CMD_REASONING: "/reasoning",
    TKey.CMD_REASONING_DESC: "设置推理努力级别（低/中/高）",
    TKey.CMD_EFFORT: "/effort",
    TKey.CMD_EFFORT_DESC: "切换思考努力级别（低/中/高/极高）",
    TKey.CMD_1M: "/1M",
    TKey.CMD_1M_DESC: "切换 1M 上下文窗口模式（125K ↔ 1M）",
    TKey.CMD_SESSIONS: "/sessions",
    TKey.CMD_SESSIONS_DESC: "打开项目会话历史",
    TKey.CMD_CLEAR: "/clear",
    TKey.CMD_CLEAR_DESC: "开始新会话",
    TKey.CMD_COMPACT: "/compact",
    TKey.CMD_COMPACT_DESC: "压缩对话历史",
    TKey.CMD_LANGUAGE: "/language",
    TKey.CMD_LANGUAGE_DESC: "切换界面语言（EN / 中文）",
    TKey.CMD_INIT: "/init",
    TKey.CMD_INIT_DESC: "生成/更新 FLYINCHAT.md 项目记忆文件",
    TKey.CMD_MCP: "/mcp",
    TKey.CMD_MCP_DESC: "查看 MCP 服务器状态与工具列表",
    TKey.CMD_SKILLS: "/skills",
    TKey.CMD_SKILLS_DESC: "查看已加载的 Agent Skills",
    TKey.CMD_LANGFUSE: "/langfuse",
    TKey.CMD_LANGFUSE_DESC: "切换 Langfuse 可观测性（开/关）",

    # ── Reasoning levels ──
    TKey.REASONING_LOW: "快速，最少推理",
    TKey.REASONING_MED: "平衡推理",
    TKey.REASONING_HIGH: "深度，全面推理",

    # ── Effort levels ──
    TKey.EFFORT_LOW: "思考关闭，最少推理",
    TKey.EFFORT_MED: "思考开启，平衡推理",
    TKey.EFFORT_HIGH: "思考开启，深度推理",
    TKey.EFFORT_XHIGH: "思考开启，最大推理",

    # ── API actions ──
    TKey.API_DEEPSEEK_TITLE: "添加 DeepSeek 预设",
    TKey.API_DEEPSEEK_DESC: "只需要 API 密钥",
    TKey.API_OPENAI_TITLE: "添加 OpenAI 兼容渠道",
    TKey.API_OPENAI_DESC: "名称、基础 URL、API 密钥、模型",
    TKey.API_ANTHROPIC_TITLE: "添加 Anthropic 渠道",
    TKey.API_ANTHROPIC_DESC: "名称、API 密钥、模型",

    # ── Role labels ──
    TKey.LABEL_YOU: "你",
    TKey.LABEL_ASSISTANT: "助手",
    TKey.LABEL_TOOL: "工具",
    TKey.LABEL_SYSTEM: "系统",
    TKey.LABEL_MESSAGE: "消息",

    # ── Placeholders ──
    TKey.PLACEHOLDER_INPUT: "向 FlyinChat 提问，或输入 / 查看命令",
    TKey.PLACEHOLDER_PERMISSION: "按 Enter 批准，n 拒绝",

    # ── Empty state ──
    TKey.EMPTY_HINT: "在下方输入框中开始项目本地的对话。",

    # ── Command menu ──
    TKey.CMENU_NO_MATCHES: "没有匹配的命令\n输入 /api、/model、/sessions 或 /clear",
    TKey.CMENU_COMMANDS: "命令",
    TKey.CMENU_FOOTER: "↑/↓ 选择，Tab 自动补全，Enter 打开。",
    TKey.FILE_MENTION_TITLE: "工作区路径",
    TKey.FILE_MENTION_FOOTER: "↑/↓ 选择，Enter 或 Tab 插入路径。",
    TKey.FILE_MENTION_NO_MATCHES: "没有匹配 @{query} 的文件或文件夹",
    TKey.FILE_MENTION_FILE: "文件",
    TKey.FILE_MENTION_DIR: "文件夹",

    # ── Panels ──
    TKey.PANEL_UNKNOWN_CMD: "未知命令",
    TKey.PANEL_UNKNOWN_CMD_BODY: "没有名为 {command} 的命令。输入 / 查看可用命令。",
    TKey.PANEL_API_SETUP_ERR: "API 设置错误",
    TKey.PANEL_API_CHANNEL_ADDED: "API 渠道已添加",
    TKey.PANEL_PRIMARY_MODEL: "主模型",
    TKey.PANEL_NO_PROVIDERS: "尚未配置 API 提供商。请使用 /api 添加。",
    TKey.PANEL_MODEL_SELECT_ERR: "模型选择错误",
    TKey.PANEL_MODEL_SELECT_USAGE: "用法：/model use <渠道> <模型>",
    TKey.PANEL_SESSION_HISTORY: "会话历史",
    TKey.PANEL_NO_SESSIONS: "尚无项目本地会话。发送消息以创建一个。",
    TKey.PANEL_NEW_SESSION: "新会话",
    TKey.PANEL_NEW_SESSION_BODY: "已准备好开始新的项目本地对话。",
    TKey.PANEL_COMPACT: "压缩",
    TKey.PANEL_NO_CONVERSATION: "没有活跃对话可压缩。",
    TKey.PANEL_NO_MODEL: "未配置模型。请使用 `/api` 添加，然后使用 `/model` 选择。",
    TKey.PANEL_COMPACT_OK: "已压缩 — {tokens}K tokens 在预算范围内（{limit}K 限制）。",
    TKey.PANEL_COMPACT_DONE: "对话已压缩",
    TKey.PANEL_COMPACT_NOT_NEEDED: "无需压缩 — 对话在 token 预算范围内。",
    TKey.PANEL_INPUT_REQUIRED: "需要输入",
    TKey.PANEL_INPUT_PROMPT: "请输入一个值以继续。",
    TKey.PANEL_ADD_API: "添加 API 渠道",
    TKey.PANEL_THINKING_MODE: "思考模式",
    TKey.PANEL_THINKING_NO_MODEL: "未配置主模型。请使用 /model 设置。",
    TKey.PANEL_REASONING_EFFORT: "推理努力",
    TKey.PANEL_REASONING_NO_MODEL: "未配置主模型。请使用 /model 设置。",
    TKey.PANEL_EFFORT_LEVEL: "努力级别",
    TKey.PANEL_EFFORT_NO_MODEL: "未配置主模型。请使用 /model 设置。",
    TKey.PANEL_CTX_WINDOW: "上下文窗口",
    TKey.PANEL_CTX_NO_MODEL: "未配置主模型。请使用 /model 设置。",
    TKey.PANEL_INIT: "项目初始化",
    TKey.PANEL_INIT_BODY: "正在探索项目结构并生成 FLYINCHAT.md...",
    TKey.PANEL_INIT_NO_MODEL: "未配置主模型。请先使用 /api 添加模型，再使用 /model 选择。",
    TKey.PANEL_INIT_DONE: "FLYINCHAT.md 已生成到工作区根目录。",
    TKey.PANEL_SKILLS: "Agent Skills",
    TKey.PANEL_SKILLS_EMPTY: "未加载任何 skill。请在工作区 `skills/**/SKILL.md` 或 `~/.flyinchat/skills` 下添加 SKILL.md 文件。",
    TKey.PANEL_NO_CONFIG: "配置文件不可用。请确保 `~/.flyinchat/config.json` 存在。",

    # ── API form ──
    TKey.FORM_DEEPSEEK_KEY: "DeepSeek API 密钥",
    TKey.FORM_OPENAI_NAME: "渠道名称",
    TKey.FORM_OPENAI_URL: "基础 URL",
    TKey.FORM_OPENAI_KEY: "API 密钥",
    TKey.FORM_OPENAI_MODELS: "模型，逗号分隔",
    TKey.FORM_ANTHROPIC_NAME: "渠道名称",
    TKey.FORM_ANTHROPIC_KEY: "API 密钥",
    TKey.FORM_ANTHROPIC_MODELS: "模型，逗号分隔",
    TKey.FORM_DEEPSEEK_TITLE: "DeepSeek 预设",
    TKey.FORM_OPENAI_TITLE: "OpenAI 兼容渠道",
    TKey.FORM_ANTHROPIC_TITLE: "Anthropic 渠道",
    TKey.FORM_STEP: "第 {step}/{total} 步：{field}",

    # ── Selection UI ──
    TKey.SEL_API_TITLE: "LLM API 提供商",
    TKey.SEL_API_HEADER: "已配置的渠道\n{channels}\n\n预设\n{presets}\n",
    TKey.SEL_API_FOOTER: "↑/↓ 选择操作，Enter 继续。",
    TKey.SEL_MODEL_TITLE: "主模型",
    TKey.SEL_MODEL_HEADER: "已配置的提供商模型",
    TKey.SEL_MODEL_FOOTER: "↑/↓ 选择模型，Enter 设为主模型。",
    TKey.SEL_THINKING_TITLE: "思考模式",
    TKey.SEL_THINKING_ON: "启用思考",
    TKey.SEL_THINKING_ON_DESC: "开启推理思考",
    TKey.SEL_THINKING_OFF: "禁用思考",
    TKey.SEL_THINKING_OFF_DESC: "关闭推理思考",
    TKey.SEL_THINKING_FOOTER: "↑/↓ 选择，Enter 切换。",
    TKey.SEL_REASONING_TITLE: "推理努力",
    TKey.SEL_REASONING_FOOTER: "↑/↓ 选择，Enter 设置。",
    TKey.SEL_EFFORT_TITLE: "努力级别",
    TKey.SEL_EFFORT_FOOTER: "↑/↓ 选择，Enter 设置。",
    TKey.SEL_SESSION_TITLE: "会话历史",
    TKey.SEL_SESSION_FOOTER: "↑/↓ 选择会话，Enter 进入。",
    TKey.SEL_MCP_TITLE: "MCP 服务器",
    TKey.SEL_MCP_FOOTER: "↑/↓ 选择服务器，Enter 查看详情。",

    # ── MCP panels ──
    TKey.PANEL_MCP_DETAIL: "MCP 服务器详情",
    TKey.PANEL_MCP_NO_SERVERS: "未配置 MCP 服务器。\n\n在 `~/.flyinchat/config.json` 的 `mcp_servers` 字段中添加服务器配置。",
    TKey.PANEL_MCP_STATUS_CONNECTED: "已连接",
    TKey.PANEL_MCP_STATUS_ERROR: "连接错误",
    TKey.PANEL_MCP_STATUS_CONNECTING: "连接中",
    TKey.PANEL_MCP_STATUS_DISCONNECTED: "已断开",
    TKey.PANEL_MCP_RECONNECT: "重新连接",
    TKey.PANEL_MCP_RECONNECTING: "正在重新连接 {name}...",
    TKey.PANEL_MCP_RECONNECT_OK: "重新连接成功，{count} 个工具已注册",
    TKey.PANEL_MCP_BACK: "返回",
    TKey.PANEL_MCP_ACTION_TITLE: "MCP 操作",

    # ── Status bar ──
    TKey.STATUS_WORKING: "正在处理",
    TKey.STATUS_COMPACTING: "⏳ 正在压缩对话历史...",
    TKey.STATUS_NO_MODEL: "未配置模型 — 请使用 /api 然后 /model",
    TKey.STATUS_THINK: "思考: {status}",
    TKey.STATUS_NO_CONV: "无对话",
    TKey.STATUS_MSGS: "{count} 条消息",
    TKey.STATUS_MODE_NORMAL: "常规",
    TKey.STATUS_MODE_AUTO_EDIT: "自动",
    TKey.STATUS_MODE_YOLO: "YOLO",
    TKey.STATUS_MODE_PLAN: "计划",
    TKey.STATUS_LANGFUSE_ON: "Langfuse: 开",
    TKey.STATUS_LANGFUSE_OFF: "Langfuse: 关",

    # ── Thinking / Effort hints ──
    TKey.HINT_THINKING_ON: "> 思考已**启用** — {channel} / {model}",
    TKey.HINT_THINKING_OFF: "> 思考已**禁用** — {channel} / {model}",
    TKey.HINT_REASONING_SET: "> 推理努力已设置为 **{effort}** — {channel} / {model}",
    TKey.HINT_EFFORT_ON: "> 努力已设置为 **思考开启，{effort}** — {channel} / {model}",
    TKey.HINT_EFFORT_OFF: "> 努力已设置为 **思考关闭（低）** — {channel} / {model}",
    TKey.HINT_CTX_SET: "> 上下文窗口已设置为 **{label}** — {channel} / {model}",
    TKey.HINT_PRIMARY_MODEL: "> 主模型已设置为 **{channel} / {model}**",
    TKey.HINT_LANGUAGE_SET: "语言已切换为中文",

    # ── Permission request ──
    TKey.PERM_TITLE: "## 需要权限\n\n**工具：** {tool}\n\n**风险：** {risk}\n\n**参数：** `{args}`\n\n**原因：** {reason}\n\n---\n按 **Enter** 批准，或按 **n** 拒绝",
    TKey.PERM_LABEL: "需要权限",
    TKey.PERM_PLACEHOLDER: "按 Enter 批准，n 拒绝",
    TKey.PERM_APPROVE: "批准 - 允许此工具执行",
    TKey.PERM_ALWAYS_APPROVE: "总是允许 - 自动批准此类命令",
    TKey.PERM_DENY: "拒绝 - 阻止此工具调用",
    TKey.PERM_ACTION_TITLE: "需要操作",
    TKey.PERM_ACTION_FOOTER: "↑/↓ 选择  |  Enter 确认  |  y=批准  a=总是允许  n=拒绝  esc=拒绝",

    # ── Risk badges ──
    TKey.RISK_LOW: "低",
    TKey.RISK_MEDIUM: "中",
    TKey.RISK_HIGH: "高",

    # ── Todo panel ──
    TKey.TODO_TITLE: "计划",
    TKey.TODO_EMPTY: "暂无计划",

    # ── Misc ──
    TKey.MISC_NO_MESSAGES: "_暂无消息_",
    TKey.MISC_NO_PROVIDERS: "尚未配置提供商。",
    TKey.MISC_NO_PROVIDERS_ADD: "尚未配置提供商。请从下方预设中选择一个添加。",
    TKey.MISC_DEFAULT_ENDPOINT: "默认端点",
    TKey.MISC_NO_MODELS: "无模型",
    TKey.MISC_CONFIGURED: "已配置",
    TKey.MISC_PRIMARY_MARKER: " [主模型]",
    TKey.MISC_MODEL_ROW: "   {ci}.{mi} {name}{marker}",
    TKey.MISC_ERROR_PREFIX: "*[错误: {error}]*",

    # ── Init prompt ──
    TKey.INIT_PROMPT: (
        "你正在执行项目初始化任务。目标是为当前工作区生成或更新一份 FLYINCHAT.md 文件，"
        "作为后续 AI 协作的项目约束文档。\n\n"
        "要求：\n"
        "1. 先通过阅读关键文件（README、包配置、源码结构、测试配置、lint 配置）探索项目再动笔，"
        "不得凭空编造命令或技术栈。\n"
        "2. FLYINCHAT.md 必须覆盖：\n"
        "   - 项目简介与目标\n"
        "   - 目录结构与关键模块\n"
        "   - 安装/启动/测试命令\n"
        "   - 代码规范与提交约定\n"
        "   - 常见风险与禁止事项\n"
        "   - 推荐工作流（如先计划后改动）\n"
        "3. 信息不确定时，明确标注\"TODO:待确认\"，并给出建议确认方式。\n"
        "4. 输出为可保存的 Markdown，直接写入工作区根目录的 FLYINCHAT.md。\n"
        "5. 保持简洁、可执行、可维护。\n"
        "6. 若 FLYINCHAT.md 已存在，请保留有效规则并做增量改进，避免无关重写。"
    ),

    # ── Compact engine ──
    TKey.COMPACT_SUMMARY_PROMPT: (
        "请将以下对话历史总结成简洁的摘要。保留：\n"
        "- 用户的主要请求和目标\n"
        "- 助手使用的工具及其关键结果\n"
        "- 重要的决策和结论\n"
        "摘要应该用中文，尽量简洁但不要丢失关键信息。"
    ),
    TKey.COMPACT_ROLE_USER: "用户",
    TKey.COMPACT_ROLE_ASSISTANT: "助手",
    TKey.COMPACT_ROLE_TOOL: "工具",
    TKey.COMPACT_ROLE_SYSTEM: "系统",
    TKey.COMPACT_CONVERSATION_HISTORY: "对话历史：",
    TKey.COMPACT_OUTPUT_SUMMARY: "请输出摘要：",
}
