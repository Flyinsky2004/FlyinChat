# QueryEngine 实施说明（给 AI 直接执行）

## 1) 这是什么

QueryEngine 不是“聊天接口封装”，而是一个会话级任务编排器。

它负责把一次用户输入，推进成完整的工程执行闭环：
- 构建上下文
- 调模型
- 处理工具调用
- 回写工具结果
- 继续推理
- 必要时压缩上下文
- 持久化会话用于恢复

一句话：
普通对话系统是“问一句答一句”；
QueryEngine 是“在一个会话里持续把任务做完”。

---

## 2) 和普通对话的核心区别

### 普通对话（Chat Loop）
- 关注点：单轮响应
- 输入输出：user -> assistant
- 工具：可有可无，通常旁路
- 状态：多为短期内存
- 上下文：超长时容易失控

### QueryEngine（Agent Loop）
- 关注点：任务完成
- 输入输出：user -> assistant(tool_call) -> tool(tool_result) -> assistant ...
- 工具：一等公民，结果必须回写主消息链
- 状态：会话级长期状态（usage、权限拒绝、文件缓存、任务态）
- 上下文：分层 compact + resume 机制

关键差异不在“模型能力”，在“运行时架构”。

---

## 3) AI 需要先做的目标（范围）

目标不是一次做完 Claude Code 全量功能，而是先完成 QueryEngine 内核 v1：

必须完成：
1. 会话消息模型（turn-based）
2. QueryEngine 主循环
3. 工具调用闭环（含 tool_call_id 关联）
4. 会话持久化与恢复（session/resume）
5. compact MVP（自动触发 + boundary 落盘）
6. 权限前置检查（至少路径与工具级）

暂不要求：
- MCP/LSP/多 Agent
- 复杂 UI 动效
- 高级 context collapse snapshot 细节

---

## 4) 应该怎么做（分阶段）

## 阶段 A：定义消息与会话模型（先做）

### A1. 定义 Message 结构
最小字段：
- id
- session_id
- turn_id
- role: user | assistant | tool | system
- subtype: normal | tool_call | tool_result | compact_boundary
- content
- created_at
- tool_call_id（可选）
- tool_call / tool_result / compact_metadata（可选）
- meta（可选）

### A2. 定义 Session 结构
- session_id
- created_at / updated_at
- current_turn
- config_snapshot（model、policy）

### A3. 定义写入规则
每轮最少会出现：
1) user
2) assistant（可能是 tool_call）
3) tool（tool_result）
4) assistant（继续/收敛）


## 阶段 B：实现 QueryEngine 主循环

伪流程：
1) 接收用户输入，写入 user message
2) 构建 messagesForQuery（系统上下文 + 会话历史）
3) 调模型
4) 若模型要求调用工具：
   - 生成 tool_call_id
   - 写 assistant/tool_call
   - 权限检查
   - 执行工具
   - 写 tool/tool_result
   - 继续下一轮模型调用
5) 若模型返回最终回答：
   - 写 assistant/final
   - 结束本轮
6) 每轮更新 usage/state

约束：
- 工具结果必须入消息链，不可只打日志
- 每次循环都可中断/超时


## 阶段 C：接入 Tool Runtime（最小）

先接 3 个工具：
- file_read
- file_write
- bash（受限）

Tool 契约：
- input_schema()
- requires_permission(input, context)
- run(input, context) -> ToolResult

ToolResult 统一：
- ok
- content
- data
- error_code
- meta


## 阶段 D：权限与安全

至少实现：
1) 工具 allow/deny
2) 路径沙箱（workspace 内）
3) bash 基础风控（先拒高危命令）

原则：
- 先审后跑
- 拒绝要可解释（reason/error_code）


## 阶段 E：compact MVP（关键）

先做自动 compact，不等 /compact 命令。

MVP 顺序：
1) ToolResultBudget：截断超长 tool_result
2) Snip：去重复低价值消息
3) Autocompact：摘要旧历史段
4) 写 system/compact_boundary（带 compact_metadata）
5) API 超限时 Reactive Compact 重试

compact_boundary 必含：
- boundary_id
- source_range
- summary_ref
- preserved_segment_anchor
- tokens_before/tokens_after


## 阶段 F：恢复（resume）

要求：
- 可按 session_id 重建会话
- 可识别 compact_boundary
- 能继续新 turn，不破坏 tool_call_id 关联


## 5) 普通对话迁移到 QueryEngine 的迁移策略

不要一次推翻，按“旁路接管”方式：

1) 保留现有 TUI 输入输出
2) 新增 QueryEngine Service
3) 把“发送消息”入口改为调用 QueryEngine.submitMessage()
4) 先在单会话模式跑通
5) 再切到多会话 + resume
6) 最后接 compact

这样风险最低，可逐步回归测试。

---

## 6) AI 实施时的验收标准（Definition of Done）

必须全部满足才算 QueryEngine v1 完成：

1. 单轮工具闭环可跑通
- user -> tool_call -> tool_result -> final assistant

2. 连续多轮会话稳定
- 至少 20 轮不丢状态

3. tool_call_id 关联完整
- 每个 tool_result 都能回溯到 tool_call

4. 权限拒绝有效
- 越权路径和禁用工具会被拦截

5. compact 自动触发有效
- 上下文超阈值后出现 compact_boundary

6. resume 可继续
- 重启后从历史恢复并继续新任务

7. 可观测性最小闭环
- 至少有 turn_id / tool_name / error_code / elapsed_ms 级日志

---

## 7) 给 AI 的执行指令模板（可直接复制）

请按以下顺序实现 QueryEngine v1：
1) 先建立消息与会话数据模型（含 turn_id/tool_call_id/compact_boundary）
2) 实现 QueryEngine 主循环（支持工具调用迭代）
3) 接入最小 Tool Runtime（file_read/file_write/bash）
4) 加入权限前置检查与路径沙箱
5) 实现 compact MVP（budget+snip+autocompact+boundary+reactive）
6) 实现 session resume
7) 补充最小回归测试与结构化日志

限制：
- 不要先做 UI 花活
- 不要先做 MCP/LSP
- 先把会话内核做对

交付时请提供：
- 模块结构图
- 主循环时序图
- 数据模型定义
- 验收清单勾选结果

---

## 8) 一句话总括

把 QueryEngine 做成之前，TUI 只是“会说话的终端”；
把 QueryEngine 做成之后，TUI 才是“可持续完成任务的工程代理界面”。