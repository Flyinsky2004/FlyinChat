# Python TUI Chat Agent 集成 Langfuse 可观测性与质量评估方法论

## 目标

为当前 Python TUI Chat Agent 接入 Langfuse，实现：

1. 完整 Trace 采集
2. LLM 调用记录
3. 工具调用记录
4. Agent 任务级指标采集
5. 根据 AWS Agent 质量评估思路落地必要指标
6. 敏感配置通过 `.env` 管理
7. 提供 `.env.example`
8. 确保真实密钥不会上传仓库

核心原则：

> 不只是“接入 Langfuse SDK”，而是让每次 Agent 执行都可以被回放、评估、归因和对比。

---

# 1. 整体设计原则

## 1.1 一次用户任务 = 一个 Trace

每当 TUI 中用户输入一条新的任务请求时，创建一个新的 Langfuse Trace。

Trace 应该代表：

```text
用户目标 → Agent 决策 → LLM 调用 → 工具调用 → 环境反馈 → 最终回答 → 评估指标
```

不要把整个 TUI 进程当作一个 Trace。  
一个长期 TUI session 可以对应多个 Trace。

建议映射：

```text
TUI session_id        = 一次终端会话
user request / task   = 一个 Langfuse trace
agent loop            = agent span
llm call              = generation span
tool call             = tool span
final metrics         = trace scores
```

---

## 1.2 观测数据和业务日志分层

不要把所有数据都塞进 Langfuse。

建议分两层：

### Langfuse 负责

- Trace
- Span
- Generation
- Tool call
- Token
- Latency
- Cost
- Score
- Error
- Metadata
- 回放与调试

### 本地 Eval DB / JSONL 负责

- 完整原始日志
- 大型 tool result
- 文件内容快照
- Git diff
- 测试输出全文
- 大体积 artifact
- 长期离线分析数据

Langfuse 中只保留：

- 摘要
- Preview
- Hash
- 文件路径
- 截断后的输出
- 指标结果

---

# 2. 必须采集的 Trace 结构

## 2.1 Trace 级 Metadata

每个 Trace 必须记录：

```text
trace_id
session_id
task_id
user_id 可选
agent_version
model_name
prompt_version
tool_version
workspace
git_branch
git_commit_before
agent_mode
permission_mode
started_at
ended_at
```

如果当前项目还没有版本体系，也至少要保留：

```text
agent_version = unknown 或 git commit
prompt_version = default
tool_version = default
```

---

## 2.2 Agent Span

Agent 主循环应作为顶层 observation / span。

记录：

```text
user_input
final_answer
status
error_message
total_steps
total_tool_calls
total_llm_calls
total_latency_ms
```

Agent Span 的作用是把一次任务完整包起来。

---

## 2.3 LLM Generation

每次模型调用都应该记录为 generation。

记录：

```text
model
input_messages
output_message
temperature
top_p
max_tokens
stop
input_tokens
output_tokens
total_tokens
latency_ms
cost
finish_reason
```

注意：

- 如果 messages 很长，需要记录截断版本
- 同时记录原始 messages 的 hash
- 不要记录敏感密钥、私有 token、`.env` 内容

---

## 2.4 Tool Span

每次工具调用都应该记录为 tool span。

必须记录：

```text
tool_call_id
tool_name
tool_args
tool_result_preview
tool_result_hash
status
error_type
error_message
latency_ms
risk_level
requires_approval
approval_status
```

对于 Claude Code 类 Agent，重点工具包括：

```text
read_file
write_file
edit_file
search_files
bash
git_diff
run_tests
list_files
ask_user
web_search
```

尤其是以下工具，要额外记录安全信息：

```text
bash
write_file
edit_file
git
network
deploy
```

---

# 3. 根据 AWS Agent 评估思路落地指标

AWS Agent 质量评估强调 Agent 评估不能只看文本回答，而要关注：

- 任务完成率
- 决策准确率
- 工具调用准确率
- 平均任务耗时
- 平均交互轮数
- 安全与合规
- Progress Rate
- Grounding Accuracy
- Error Breakdown
- 失败归因
- 成本与效率

对 Claude Code 类 Agent，可以按下面方式实现。

---

## 3.1 Task Completion Rate / 任务完成率

### 指标名称

```text
task_success
```

### 含义

这次用户任务是否最终成功完成。

### 判断依据

优先使用客观信号：

```text
tests_pass
lint_pass
typecheck_pass
build_pass
patch_apply_success
issue_resolved
no_unexpected_file_change
no_unsafe_side_effect
```

不要只相信 Agent 自己说“完成了”。

### 采集方式

任务结束后写入 trace score：

```text
task_success = 0 / 1
```

---

## 3.2 Progress Rate / 进度率

### 指标名称

```text
progress_rate
```

### 含义

任务未完全成功时，Agent 完成了多少子目标。

### Claude Code 类 Agent 的子目标拆分

一个 coding task 可以拆成：

```text
1. 理解用户需求
2. 找到相关文件
3. 定位问题原因
4. 完成代码修改
5. 新增或更新测试
6. 运行验证命令
7. 根据失败反馈修复
8. 给出最终总结
```

Progress Rate 示例：

```text
完成 6 / 8 = 0.75
```

### 采集方式

每个关键阶段更新 progress。

最终写入：

```text
progress_rate = 0.0 - 1.0
```

---

## 3.3 Tool Call Accuracy / 工具调用准确率

### 指标名称

```text
tool_call_accuracy
```

### 含义

Agent 是否选择了正确工具，并传入了正确参数。

### 注意

不要只看工具是否执行成功。

AWS 评估文章提到 Grounding Accuracy 的局限：

> 工具不报错，不代表工具选得对。

所以工具调用要拆成几个字段：

```text
tool_execution_success
tool_needed
tool_choice_correct
tool_args_valid
tool_args_correct
tool_result_useful
tool_call_redundant
```

### Claude Code 场景示例

```text
用户要求修测试失败
Agent 调用 run_tests：正确
Agent 调用 read_file 读取相关文件：正确
Agent 反复读取同一文件 5 次：冗余
Agent 用 bash cat 文件而不是 read_file：视工具规范判断
Agent 未看文件直接 edit_file：高风险
```

最终可计算：

```text
tool_call_accuracy =
正确工具调用数 / 总工具调用数
```

---

## 3.4 Grounding Accuracy / 动作落地准确率

### 指标名称

```text
grounding_accuracy
```

### 含义

Agent 生成的动作是否真实可执行、格式合法、参数合法。

### 判断标准

```text
工具 schema 校验通过
工具可以执行
没有格式错误
没有参数缺失
没有路径错误
没有权限错误
```

例如：

```text
read_file(path="不存在的文件") → grounding 失败
bash(command=空字符串) → grounding 失败
edit_file(old_string 匹配不到) → grounding 失败
```

计算方式：

```text
grounding_accuracy =
合法可执行动作数 / 总动作数
```

---

## 3.5 Decision Accuracy / 决策准确率

### 指标名称

```text
decision_accuracy
```

### 含义

Agent 在关键节点是否做出正确决策。

Claude Code 类 Agent 的关键决策包括：

```text
是否需要先读文件
是否需要搜索代码
是否需要运行测试
是否需要修改代码
是否需要请求用户确认
是否需要停止而不是继续乱改
是否需要回滚
是否需要扩大调查范围
```

### 采集方式

可以先通过规则 + 人工抽检实现，后续用 LLM-as-Judge 辅助。

记录每个 decision event：

```text
decision_id
decision_point
chosen_action
expected_action 可选
is_correct
reason
```

---

## 3.6 Average Time / 平均任务耗时

### 指标名称

```text
task_latency_ms
```

### 采集内容

```text
trace_started_at
trace_ended_at
total_latency_ms
llm_latency_ms
tool_latency_ms
test_latency_ms
idle_latency_ms
```

最终统计：

```text
average_task_latency_ms
```

---

## 3.7 Average Steps / 平均交互轮数

### 指标名称

```text
total_steps
average_steps
```

Claude Code 场景中 step 可以定义为：

```text
一次 LLM 决策
一次工具调用
一次用户追问
一次错误恢复
```

建议至少记录：

```text
llm_call_count
tool_call_count
agent_loop_iterations
user_turn_count
```

---

## 3.8 Rule Compliance Rate / 规则遵循率

### 指标名称

```text
rule_compliance
```

### Claude Code 类 Agent 需要遵守的规则

例如：

```text
修改文件前必须读取文件
执行高风险命令前必须请求确认
不得上传私有代码到外部服务
不得读取或输出 .env 密钥
不得执行 rm -rf 等危险命令
不得在未验证时声称测试通过
不得伪造命令输出
不得越权访问 workspace 外文件
```

每次违反记录：

```text
rule_violation_count
rule_violation_type
rule_violation_detail
```

最终：

```text
rule_compliance = 0 / 1 或 0.0 - 1.0
```

---

## 3.9 Error Breakdown / 错误归因

### 指标名称

```text
failure_stage
failure_reason
```

失败时必须归因。

推荐枚举：

```text
intent_understanding_error
planning_error
tool_selection_error
tool_argument_error
tool_execution_error
file_edit_error
test_failure
environment_error
permission_error
context_loss
overengineering
timeout
unknown
```

每个失败 Trace 都要写：

```text
failure_stage
failure_reason
root_cause
recoverable
suggested_fix
```

---

## 3.10 Cost / Token 指标

AWS 评估思路中，效率和成本也必须纳入评估。

必须采集：

```text
input_tokens
output_tokens
total_tokens
total_cost
cost_per_successful_task
llm_call_count
```

---

# 4. Claude Code 类 Agent 的额外必采指标

除了通用 Agent 质量指标，Claude Code 类 Agent 还应该采集 coding-agent 专属指标。

---

## 4.1 Git Diff 指标

任务结束时采集：

```text
files_changed
lines_added
lines_deleted
git_diff_hash
unexpected_files_changed
```

Langfuse 中只存 diff 摘要，不建议存完整大 diff。

完整 diff 可以存在本地 artifact 中，然后在 Langfuse metadata 里放路径或 hash。

---

## 4.2 测试指标

采集：

```text
tests_run
tests_pass
tests_failed
test_command
test_exit_code
test_latency_ms
test_output_preview
```

如果没有运行测试，也要记录：

```text
tests_run = false
reason = "no test command found" 或 "agent skipped"
```

---

## 4.3 修改质量指标

可以用 LLM-as-Judge 或人工评估：

```text
patch_quality_score
minimal_change_score
code_style_score
test_quality_score
regression_risk_score
```

---

## 4.4 安全指标

采集：

```text
unsafe_action_count
dangerous_command_attempted
permission_request_count
permission_denied_count
sensitive_file_access_count
secret_redaction_count
external_network_call_count
```

---

## 4.5 Context / Compact 指标

如果 Agent 后续有 compact / resume：

```text
context_tokens_before
context_tokens_after
compact_triggered
compact_boundary_id
compact_loss_detected
resume_success
duplicate_work_count
```

---

# 5. 必须实现的数据脱敏策略

Langfuse 是观测平台，不应该无脑上传所有内容。

Claude Code 必须实现统一 sanitizer。

---

## 5.1 敏感 Key 脱敏

凡是 key 名包含以下字段，value 必须替换：

```text
password
passwd
secret
token
api_key
apikey
authorization
cookie
private_key
access_key
refresh_token
client_secret
```

替换为：

```text
[REDACTED]
```

---

## 5.2 敏感文件脱敏

以下文件内容不得上传 Langfuse：

```text
.env
.env.*
*.pem
*.key
id_rsa
id_ed25519
credentials.json
secrets.yaml
```

只允许记录：

```text
path
size
hash
redacted = true
```

---

## 5.3 Tool Result 截断

所有工具输出必须限制长度。

建议：

```text
普通工具输出：最多 8k chars
测试失败输出：最多 20k chars
文件读取输出：最多 8k chars
git diff：最多 12k chars
```

超出则记录：

```text
truncated = true
original_length
preview
hash
```

---

# 6. `.env` 和 `.env.example` 要求

## 6.1 必须创建 `.env.example`

仓库中应该提交 `.env.example`，示例：

```text
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

AGENT_ENV=development
AGENT_VERSION=local
LANGFUSE_ENABLED=true
LANGFUSE_DEBUG=false
```

如果使用自部署 Langfuse，可以在注释中说明：

```text
# For self-hosted Langfuse:
# LANGFUSE_HOST=https://your-langfuse.example.com
```

---

## 6.2 必须创建或更新 `.gitignore`

确保 `.env` 不会被提交：

```text
.env
.env.*
!.env.example
```

如果项目已经有 `.gitignore`，只追加，不破坏已有规则。

---

## 6.3 `.env` 只在本地创建，不提交

Claude Code 可以创建本地 `.env`，但必须满足：

```text
不得写入真实密钥到 git tracked 文件
不得将 .env 加入 git
不得在日志中打印 LANGFUSE_SECRET_KEY
不得把 .env 内容上传 Langfuse
```

---

## 6.4 启动时加载 `.env`

Python 项目建议使用：

```text
python-dotenv
```

启动时加载：

```text
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_HOST
LANGFUSE_ENABLED
LANGFUSE_DEBUG
```

如果缺少 Langfuse key：

```text
不要让 Agent 崩溃
只禁用 Langfuse tracing
打印友好提示
```

---

# 7. 建议的模块边界

不要把 Langfuse 调用散落全项目。

建议新增独立 observability 模块：

```text
observability/
  config
  client
  tracing
  sanitize
  metrics
  scoring
```

---

## 7.1 config

负责：

```text
读取环境变量
判断 LANGFUSE_ENABLED
校验 key 是否存在
```

---

## 7.2 client

负责：

```text
初始化 Langfuse client
flush
shutdown
```

---

## 7.3 tracing

负责：

```text
trace_agent_run
trace_llm_generation
trace_tool_call
trace_event
```

---

## 7.4 sanitize

负责：

```text
脱敏
截断
hash
敏感路径识别
```

---

## 7.5 metrics

负责：

```text
统计 token
统计步骤
统计工具调用
统计耗时
统计错误
```

---

## 7.6 scoring

负责：

```text
写入 task_success
progress_rate
tool_call_accuracy
grounding_accuracy
rule_compliance
failure_stage
```

核心原则：

> 业务逻辑不要直接依赖 Langfuse SDK，应该依赖自己的 observability 抽象层。

这样以后如果换成 LangSmith / OpenTelemetry，不用重构整个 Agent。

---

# 8. 建议的集成阶段

## Phase 1：基础 Trace

目标：

```text
能在 Langfuse 看到一次用户请求完整开始和结束
```

实现：

```text
trace
agent span
final answer
error
flush
```

验收：

```text
TUI 输入一次问题后，Langfuse 出现一个 trace
trace 中包含 user_input 和 final_answer
异常时 trace 标记 error
```

---

## Phase 2：LLM Generation

目标：

```text
每次模型调用都可见
```

实现：

```text
messages
model
model parameters
output
token usage
latency
```

验收：

```text
Langfuse 中可以看到 generation
能看出每次 LLM 输入输出
能统计 token
```

---

## Phase 3：Tool Call

目标：

```text
每次工具调用都可回放
```

实现：

```text
tool_name
tool_args
tool_result_preview
status
error
latency
risk_level
```

验收：

```text
read_file / bash / edit_file 等工具在 Langfuse 中可见
工具报错时 span 标记 error
敏感内容被脱敏
长结果被截断
```

---

## Phase 4：AWS 指标采集

目标：

```text
按 Agent 质量评估要求采集核心指标
```

实现 score：

```text
task_success
progress_rate
tool_call_accuracy
grounding_accuracy
decision_accuracy
rule_compliance
task_latency_ms
total_steps
failure_stage
failure_reason
```

验收：

```text
每个 trace 结束后都有 scores
失败任务有 failure_reason
工具调用准确率可以计算
```

---

## Phase 5：Coding Agent 工程指标

目标：

```text
评估 Agent 是否真的完成代码任务
```

实现：

```text
git diff summary
tests_pass
lint_pass
typecheck_pass
files_changed
unsafe_action_count
patch_quality_score
```

验收：

```text
Agent 完成任务后能看到测试结果
能看到改了几个文件
能看到是否触发危险命令
```

---

# 9. 验收标准

## 9.1 配置与安全

```text
.env.example 已创建
.gitignore 已确保忽略 .env 和 .env.*
.env 不被 git 跟踪
缺少 Langfuse key 时程序不崩溃
密钥不会打印到日志
密钥不会上传 Langfuse
```

---

## 9.2 Trace

```text
每次用户请求生成一个 trace
trace 有 session_id / task_id / agent_version / model
trace 有最终状态 success/error
trace 结束时 flush
```

---

## 9.3 LLM

```text
每次 LLM 调用生成 generation
记录 model / input / output / token / latency
长 prompt 有截断或摘要
```

---

## 9.4 Tool

```text
每次工具调用生成 tool span
记录 tool_name / args / result / status / latency
工具错误被记录
敏感结果被脱敏
长结果被截断
```

---

## 9.5 Metrics

```text
每个 trace 至少有 task_success
每个 trace 有 total_steps
每个 trace 有 tool_call_count
每个 trace 有 task_latency_ms
失败 trace 有 failure_stage / failure_reason
```

---

## 9.6 Coding Agent 专属

```text
如果发生代码修改，记录 files_changed
如果运行测试，记录 tests_pass / test_exit_code
如果执行 bash，记录 risk_level
如果触发危险命令，记录 unsafe_action_count
```

---

# 10. 不要做的事

明确禁止：

```text
不要把 Langfuse SDK 调用散落在业务代码各处
不要上传完整 .env 内容
不要上传私钥、token、cookie
不要把完整大型文件内容塞进 Langfuse
不要只记录最终回答而不记录工具轨迹
不要只用 task_success，不记录失败归因
不要把工具执行成功等同于工具调用正确
不要在没有 key 时让 TUI 启动失败
不要提交 .env
```

---

# 11. 最终交付物

Claude Code 应该最终交付：

```text
1. observability 抽象模块
2. Langfuse client 初始化逻辑
3. Trace / generation / tool span 包装
4. sanitizer 脱敏与截断逻辑
5. metrics / scoring 逻辑
6. .env.example
7. .gitignore 更新
8. 文档说明如何配置 Langfuse
9. 简单验证方式
```

文档中必须说明：

```text
如何开启 Langfuse
如何关闭 Langfuse
需要哪些环境变量
哪些内容会被上传
哪些内容会被脱敏
如何在 Langfuse 中查看 trace
```

---

# 12. 可直接交给 Claude Code 的任务说明

```text
请为当前 Python TUI Chat Agent 设计并实现 Langfuse 可观测性集成。

要求：

1. 不要把 Langfuse SDK 调用散落在业务逻辑中，新增独立 observability 模块。

2. 每次用户请求创建一个 trace。

3. Agent 主循环记录为 agent span。

4. 每次 LLM 调用记录为 generation。

5. 每次工具调用记录为 tool span。

6. 根据 AWS Agent 质量评估思路采集并写入 scores：
   - task_success
   - progress_rate
   - tool_call_accuracy
   - grounding_accuracy
   - decision_accuracy
   - rule_compliance
   - task_latency_ms
   - total_steps
   - failure_stage
   - failure_reason

7. 对 coding agent 额外采集：
   - files_changed
   - tests_pass
   - lint_pass
   - typecheck_pass
   - unsafe_action_count
   - git_diff_summary

8. 实现统一 sanitizer：
   - 脱敏 token/password/secret/api_key/authorization/cookie/private_key 等字段
   - 不上传 .env、私钥、credentials 文件内容
   - 长 tool result 截断并记录 hash

9. 创建 .env.example，包含：
   - LANGFUSE_PUBLIC_KEY
   - LANGFUSE_SECRET_KEY
   - LANGFUSE_HOST
   - LANGFUSE_ENABLED
   - LANGFUSE_DEBUG

10. 更新 .gitignore：
   - 忽略 .env 和 .env.*
   - 保留 !.env.example

11. 缺少 Langfuse 配置时，Agent 不应崩溃，应自动禁用 tracing。

12. 任务结束时 flush，程序退出时 shutdown。

13. 提供文档说明如何配置、开启、关闭和验证 Langfuse。

14. 注意不要提交真实密钥，不要在日志或 trace 中输出敏感信息。
```

---

# 13. 总结

本次集成的目标不是简单接入 Langfuse SDK，而是建立一套面向 Claude Code 类 Agent 的观测基础设施：

```text
Agent 运行轨迹
+ LLM 调用记录
+ 工具调用记录
+ 任务成功率
+ 进度率
+ 工具调用准确率
+ 动作落地准确率
+ 安全合规
+ 失败归因
+ 成本与效率
+ 敏感数据保护
```

最终效果应该是：

> 每次 Agent 执行后，都能清楚回答：它做了什么、为什么这么做、哪里失败、成本多少、是否真的完成任务，以及下个版本应该优化哪里。
