<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/main.png" alt="FlyinChat" width="600">
</p>

<p align="center">
  <strong>终端 AI 编程助手</strong><br>
  基于 Textual TUI 的多模型 AI 对话工具，支持工具调用、MCP 服务和 Skill 技能系统。
</p>

---

## 快速开始

```bash
# 安装
pip install flyinchat

# 在项目中启动
cd my-project
flyinchat
```

首次使用：通过 `/api add` 添加模型提供商，`/model use` 选择模型，即可开始对话。

## 界面预览

<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/chat1.png" alt="FlyinChat 对话界面" width="800">
</p>

<p align="center">
  <img src="https://s3-console.pkgx.de/flyinsky/chat2.png" alt="FlyinChat Todo 面板与权限请求" width="800">
</p>

## 支持的模型提供商

- **Anthropic** — Claude 系列，支持扩展思考（extended thinking），流式输出
- **OpenAI 兼容** — DeepSeek、Groq、Ollama / vLLM 本地模型，以及任何 `/v1/chat/completions` 端点
- **DeepSeek** — 内置预设（Anthropic 兼容端点，1M 上下文）

通过 `/api add` 添加提供商，`/model use` 切换模型。

## 模式切换

按 `Shift+Tab` 切换四种模式，控制每轮对话的工具权限：

| 模式 | 行为 |
|------|------|
| **Normal** | 只读/搜索工具自动执行；写入、bash、网络工具需确认 |
| **Auto-edit** | 文件编辑/写入自动执行；bash 和网络工具仍需确认 |
| **Yolo** | 所有工具自动执行，无需确认 |
| **Plan** | 只读模式 — 仅允许分析、规划和信息收集 |

权限同时在系统提示词和工具执行层两个层面生效。

## 功能特性

- **流式对话** — 实时 token 计数与动画指示器
- **工具调用循环** — 文件读写/编辑、bash 执行、glob/grep 搜索、网页抓取/搜索
- **权限系统** — 支持单次批准、始终允许、拒绝；bash 命令白名单自动批准
- **@ 文件引用** — 输入 `@` 自动补全工作区路径
- **Todo 任务面板** — 实时展示待办/进行中/已完成任务
- **自动压缩** — 工具结果截断（软限制）+ LLM 摘要（硬限制），控制上下文在预算内
- **自动续跑** — 轮次预算耗尽时自动注入续跑提示，让模型继续完成任务
- **MCP 服务** — 接入 Model Context Protocol 服务端，工具注册为原生 FlyinChat 工具并受权限管控
- **Skill 技能系统** — 加载 `.flyinchat/skills/` 下的 `.skill.md` 文件，注入工作流指导与运行时工具守护
- **国际化** — 中英文双语支持（`/language` 切换）
- **多会话** — 通过 `/sessions` 创建和切换多个对话

## 命令列表

| 命令 | 功能 |
|---------|--------|
| `/api` | 管理 API 提供商 |
| `/model` | 选择当前使用的模型 |
| `/thinking` | 开关扩展思考模式 |
| `/reasoning` | 设置推理强度（low / medium / high） |
| `/effort` | 统一控制思考开关与推理强度 |
| `/1M` | 切换上下文窗口大小（125K ↔ 1M） |
| `/sessions` | 查看和切换对话记录 |
| `/clear` | 开始新对话 |
| `/compact` | 强制压缩上下文 |
| `/language` | 切换中英文 |
| `/mcp` | 查看和管理 MCP 服务 |
| `/skills` | 列出已加载的技能 |
| `/init` | 自动初始化项目（创建 CLAUDE.md、.gitignore 等） |

## 数据存储

- `~/.flyinchat/config.json` — LLM 渠道、模型、应用设置、MCP 服务配置
- `<项目>/.flyinchat/chat.json` — 对话历史（每个项目独立存储）

所有数据以 JSON 格式存储，使用原子写入保证数据安全。

## Langfuse 可观测性

FlyinChat 可选接入 Langfuse，按“一次用户任务 = 一个 trace”记录 agent 主循环、LLM 调用、工具调用、权限结果和质量指标。配置方式见 [docs/langfuse/langfuse-setup.md](docs/langfuse/langfuse-setup.md)。

## 开发

```bash
git clone https://github.com/FlyinSky2004/FlyinChat.git
cd FlyinChat
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 运行测试
pytest
pytest tests/test_query_engine.py -v
```

需要 Python 3.11+。基于 [Textual](https://textual.textualize.io/)、[httpx](https://www.python-httpx.org/) 和 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 构建。

## 开源协议

FlyinChat 使用 [GNU Affero General Public License v3.0](LICENSE) 开源协议 — 你可以自由使用、修改和分发本软件，前提是任何修改（包括基于网络的使用）也必须以相同协议开源。
