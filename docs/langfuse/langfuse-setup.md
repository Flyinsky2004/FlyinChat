# Langfuse 可观测性配置与验证

FlyinChat 的 Langfuse 集成以"一次用户任务 = 一个 trace"为边界：每次在 TUI 中发送一条用户请求，都会记录 agent 主循环、LLM generation、工具调用、权限结果、质量 scores 与工程指标。

所有 Langfuse 配置均存储于 `~/.flyinchat/config.json` 的 `app_settings` 字段中，无需 `.env` 文件。

## 开启 Langfuse

1. 编辑 `~/.flyinchat/config.json`，在 `app_settings` 中添加：

   ```json
   {
     "app_settings": {
       "langfuse_enabled": "true",
       "langfuse_public_key": "pk-lf-...",
       "langfuse_secret_key": "sk-lf-...",
       "langfuse_host": "https://cloud.langfuse.com",
       "langfuse_debug": "false",
       "agent_env": "development",
       "agent_version": "local"
     }
   }
   ```

2. 也可以在 TUI 中使用 `/langfuse` 命令快速切换 `langfuse_enabled`（需要先在 config.json 中填入 key）。

3. 启动 FlyinChat：

   ```bash
   python -m flyinchat
   ```

## 关闭 Langfuse

任选一种方式：

- 在 TUI 中输入 `/langfuse` 切换
- 或手动编辑 `~/.flyinchat/config.json`，将 `langfuse_enabled` 设为 `"false"`
- 或删除 `langfuse_public_key` / `langfuse_secret_key`

缺少 key 或 SDK 初始化失败时，FlyinChat 会自动使用 noop observability client，不会阻止 TUI 启动或任务执行。状态栏会显示 `Langfuse: OFF`。

## 会上传哪些内容

FlyinChat 只上传便于回放和评估的摘要信息：

- trace metadata：`session_id`、`task_id`、workspace、git branch、git commit、agent mode、model、版本信息。
- agent span：用户输入、最终回答、状态、错误、总步数、LLM/tool 调用次数、总耗时。
- LLM generation：脱敏和截断后的 messages、输入 hash、输出摘要、模型参数、token usage、latency、错误信息。
- tool span：工具名、脱敏参数、结果 preview/hash、状态、错误、latency、risk level、权限审批状态。
- scores：`task_success`、`progress_rate`、`tool_call_accuracy`、`grounding_accuracy`、`decision_accuracy`、`rule_compliance`、`task_latency_ms`、`total_steps`。
- coding-agent 指标：`files_changed`、`lines_added`、`lines_deleted`、`git_diff_hash`、测试/ lint / typecheck 命令结果、权限与 unsafe action 计数。

## 会脱敏哪些内容

统一 sanitizer 会处理：

- key 名包含以下片段的字段值：`password`、`passwd`、`secret`、`token`、`api_key`、`apikey`、`authorization`、`cookie`、`private_key`、`access_key`、`refresh_token`、`client_secret`。
- 敏感文件内容：`.env`、`.env.*`、`*.pem`、`*.key`、`id_rsa`、`id_ed25519`、`credentials.json`、`secrets.yaml`。
- 长 tool result：默认最多 8k chars；测试输出最多 20k chars；git diff 最多 12k chars，并附带 hash、原始长度和 truncated 标记。

敏感文件不会上传内容，只记录路径、hash、长度与 `redacted=true`。

## 如何在 Langfuse 中查看

1. 打开 Langfuse 项目。
2. 进入 Traces 页面。
3. 搜索 trace name：`flyinchat.user_task`。
4. 展开 trace：
   - `agent.loop` 是一次用户任务的主 span。
   - `llm.agent_turn` 是每次 agent loop 的模型调用。
   - `llm.compaction_summary` 是自动/手动压缩产生的摘要调用。
   - `tool.<tool_name>` 是每次工具调用。
5. 查看 trace scores，确认任务成功率、进度率、工具准确率和耗时指标。

## 简单验证方式

1. 在 `~/.flyinchat/config.json` 的 `app_settings` 中设置 `langfuse_enabled: "true"` 并填入 key。
2. 运行 `python -m flyinchat`，状态栏应显示 `Langfuse: ON`。
3. 发送一条普通问题，Langfuse 中应出现 `flyinchat.user_task` trace。
4. 发送一个会触发 `file_read` 的请求，trace 中应出现 `tool.file_read` span。
5. 发送一个需要 bash 权限的请求，trace 中应记录 `requires_approval=true` 和最终 `approval_status`。
6. 使用 `/langfuse` 命令切换关闭，确认状态栏变为 `Langfuse: OFF`，FlyinChat 仍能正常运行。