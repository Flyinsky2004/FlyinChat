# Claude-like 工具系统设计（从定义到实现）

## 1. 设计目标
- 让模型“可控地执行能力”，而不是直接执行任意指令。
- 统一工具协议，避免每个工具返回/权限/日志风格不一致。
- 默认安全：最小权限、路径沙箱、显式 deny 规则。
- 可扩展：后续可平滑接入 Bash、Grep、Web、MCP、子 Agent。

## 2. 统一定义标准（建议固定为硬约束）

### 2.1 工具元信息标准
每个工具必须定义：
- `name`：唯一标识（kebab/snake 均可，但全局统一）
- `description`：给模型与人看的能力描述
- `version`：工具版本（便于兼容）
- `input_schema`：结构化 JSON Schema（type/properties/required）
- `risk_level`：`low|medium|high`

### 2.2 输入标准
- 输入必须是对象（`type: object`）
- 参数必须可枚举（`properties`）
- 关键参数必须 `required`
- 参数要有语义描述，禁止“裸字符串万能入参”

### 2.3 输出标准
统一 `ToolResult`：
- `ok: bool`
- `content: str`（可读摘要）
- `data: dict | None`（结构化数据）
- `error_code: str | None`
- `meta: dict`（耗时、token、截断标记等）

### 2.4 执行上下文标准
统一 `ToolContext`（每个工具都拿到）：
- 会话 id / 用户 id
- `workspace_root`（沙箱根目录）
- feature flags
- 权限上下文（allow/deny/path policies）
- 中断控制（abort signal）
- 运行日志 emitter

### 2.5 权限标准
前置权限检查 `requires_permission(input, context)`：
- Tool 级 allow/deny
- 路径级 allow/deny（读写分离）
- 危险动作二次确认（后续给 BashTool 用）

### 2.6 生命周期事件标准
统一事件：
- `tool.start`
- `tool.progress`（可选）
- `tool.complete`
- `tool.error`

统一事件能保证 UI、日志、可观测性、回放机制可复用。

## 3. 核心架构

### 3.1 组件
1) Tool Protocol（接口层）
2) Tool Registry（注册与查询）
3) Permission Engine（预检查）
4) Tool Executor（生命周期编排）
5) Tools（具体实现：FileRead/FileWrite...）

### 3.2 执行流程
1. 模型决定调用某工具（name + args）
2. Registry 查找工具
3. Executor 触发 `tool.start`
4. Permission Engine 预检查（拒绝则直接 error）
5. 调用 tool.run()
6. 标准化结果为 `ToolResult`
7. 触发 `tool.complete` / `tool.error`
8. 结果回写消息流

## 4. 为什么先做 FileRead / FileWrite
- 文件是代码任务的基础载体；没读写就无法形成闭环。
- 比 Bash 更安全、语义更清晰、便于先打通主循环。
- 可以先验证“协议 + 权限 + 事件”三件核心基础设施。

## 5. 基础文件工具实现标准

### 5.1 FileReadTool
输入：
- `path: str`
- `offset: int=1`
- `limit: int=200`

行为要求：
- 路径必须落在 `workspace_root` 内
- 默认 UTF-8 文本读取
- 返回带行号内容（便于后续 patch/edit）
- 超大读取限制（防止一次返回过量）

### 5.2 FileWriteTool
输入：
- `path: str`
- `content: str`
- `create_dirs: bool=true`
- `overwrite: bool=true`

行为要求：
- 路径必须落在 `workspace_root` 内
- 支持自动创建父目录
- 可配置覆盖策略
- 返回 bytes_written、path

## 6. 最小可运行实现说明
参考 `src/tool_core.py` + `src/file_tools.py` + `src/demo.py`：
- 已实现统一协议、注册、执行器、权限与路径沙箱
- 已实现 FileReadTool / FileWriteTool
- 可直接运行 demo 验证闭环

## 7. 后续扩展顺序（建议）
1) GlobTool / GrepTool（先解决检索效率）
2) BashTool（加命令白名单 + 审批）
3) FileEditTool（精细改动）
4) Todo/Task 工具（长任务可控）
5) AgentTool / MCP / LSP（高级能力）

## 8. 关键工程守则
- 先协议后工具：接口不稳，后续全返工。
- 先安全再能力：权限检查要在 run 前。
- 先可观测再优化：事件和错误码先统一。
- 先小闭环再扩张：读-写-验证跑通后再加复杂工具。

## 9. 会话记录与工具轮次存储标准（新增）

为了支持后续 compact，工具系统必须与会话存储统一设计。

### 9.1 记录模型
- 消息作为主存储单元，按 `turn_id` 递增。
- 每轮允许多条消息：
  1) user
  2) assistant（可能含 tool_call）
  3) tool（tool_result）
  4) assistant（基于工具结果继续回答）

### 9.2 工具调用关联键
- 每个工具调用分配 `tool_call_id`。
- `assistant.tool_call` 与 `tool.tool_result` 必须共享同一个 `tool_call_id`。
- compact 时允许压缩正文，但不可丢失调用关联键。

### 9.3 建议消息字段
- `id`, `session_id`, `turn_id`, `role`, `subtype`, `content`, `created_at`
- `tool_call`（name/args/tool_call_id）
- `tool_result`（ok/error_code/data/tool_call_id）
- `meta`（tokens_est/elapsed_ms/truncated）

## 10. Compact 集成设计（新增）

### 10.1 设计原则
- 先局部压缩，再全局摘要，最后失败兜底。
- 先压 `tool_result` 大文本，尽量保留结构化调用关系。

### 10.2 MVP 压缩阶段
1) Tool Result Budget：截断超长工具输出（保留头尾+truncated 标记）
2) Snip：清理重复/低价值消息
3) Autocompact：把较早历史段汇总成 summary 消息
4) Reactive Compact：API 超限时报错后兜底压缩

### 10.3 Compact 边界消息
压缩成功后写入一条 `system/compact_boundary` 消息，至少包含：
- `boundary_id`
- `source_range`（被压缩的消息范围）
- `preserved_segment`（保留段锚点）
- `summary_msg_id`
- `tokens_before/after`

该边界消息是 resume 的关键锚点，不是 UI 提示。

### 10.4 触发条件建议
- `estimated_tokens > soft_limit * 0.85`：执行预算裁剪 + snip
- `estimated_tokens > soft_limit`：执行 autocompact
- API 返回 `context too long/413`：执行 reactive compact

## 11. 立即执行路线（在你当前代码基线上）

1) 新增 `conversation_store.py`（消息持久化）
2) 新增 `compaction_engine.py`（A/B/C 三阶段）
3) 在 `ToolExecutor.execute()` 结果回写前后接入会话写入
4) 增加 compact 验证用例：
   - 长 tool_result 被裁剪
   - 超阈值后出现 compact_boundary
   - 压缩前后 token 估算下降
