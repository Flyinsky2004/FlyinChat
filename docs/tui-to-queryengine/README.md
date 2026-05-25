# TUI 对话系统改造为 QueryEngine 模型（架构设计文档）

## 1. 文档目标

本文档用于指导你把“简单 TUI 对话窗口”升级成“Claude Code 风格的 QueryEngine 会话系统”。
重点是架构设计思路与运行原理，不涉及具体代码实现细节。

核心目标：
- 从“单次问答”升级到“会话级任务编排”
- 从“模型直聊”升级到“模型 + 工具 + 状态 +安全 + 压缩”闭环
- 从“UI 驱动逻辑”升级到“Engine 驱动 UI”

---

## 2. 先统一心智模型

### 2.1 旧模型（简单 TUI）
典型路径：
- 用户输入 -> 调模型 -> 输出文本

问题：
- 工具调用难接入或不可控
- 多轮状态脆弱
- 长会话会爆上下文
- 恢复能力弱

### 2.2 新模型（QueryEngine）
典型路径：
- 用户输入 -> QueryEngine 启动一轮任务
- 构建上下文 -> 调模型
- 若模型发起工具调用 -> 权限校验 -> 执行工具 -> 结果回写消息链
- 循环直到该轮完成
- 必要时触发 compact
- 持久化会话可 resume

这不是“聊天窗口增强”，而是“会话运行时重构”。

---

## 3. 目标架构（六层）

### A. Presentation Layer（TUI）
职责：
- 输入输出、状态展示、命令输入
- 渲染消息流和工具进度

原则：
- UI 不直接调用工具
- UI 不拼接上下文
- UI 只和 QueryEngine/API 交互

### B. Session & App State Layer
职责：
- 会话列表、当前会话、任务状态
- 权限弹窗状态、通知队列、UI 模式状态

原则：
- 状态可序列化（便于恢复）
- 状态分层（UI 状态 != 会话消息状态）

### C. QueryEngine Layer（核心）
职责：
- 一轮任务编排
- 模型调用循环
- 工具调用闭环
- 压缩触发与边界管理

原则：
- One QueryEngine per conversation
- 所有“任务推进逻辑”都在这一层

### D. Tool Runtime Layer
职责：
- 工具注册、权限预检、执行、结果标准化

原则：
- 统一 Tool 协议
- 生命周期事件一致
- 工具结果可追踪、可回放

### E. Storage Layer
职责：
- 消息链存储
- compact 边界存储
- 会话索引与恢复

原则：
- 存“结构化消息”，不只存展示文本
- 支持按 session/turn/tool_call_id 查询

### F. Policy & Security Layer
职责：
- 工具权限策略
- 路径沙箱策略
- 命令风险控制
- 审批/拒绝策略

原则：
- 先检查再执行
- 默认拒绝高风险能力

---

## 4. QueryEngine 的运行原理

每次用户提交输入，会触发一个“轮次任务（turn run）”。

标准流程：
1) 读取会话与系统状态
2) 构建本轮上下文（system + project + recent messages）
3) 调模型
4) 若模型返回工具调用：
   - 生成 tool_call_id
   - 记录 assistant/tool_call 消息
   - 权限校验
   - 执行工具
   - 记录 tool_result 消息
   - 回到步骤 3（继续推理）
5) 若模型返回最终文本：
   - 记录 assistant/final
   - 本轮结束
6) 若接近上限或报超长：触发 compact

核心点：
- 工具调用不是旁路动作，必须写回同一条消息链
- QueryEngine 持有跨轮状态（usage、权限拒绝记忆、文件缓存等）

---

## 5. 消息存储模型（必须先定）

建议消息最小结构：
- id
- session_id
- turn_id
- role: user | assistant | tool | system
- subtype: normal | tool_call | tool_result | compact_boundary
- content
- created_at
- tool_call（可选）
- tool_result（可选）
- compact_metadata（可选）
- meta（可选）

关键关联：
- tool_call 与 tool_result 用同一个 tool_call_id 关联
- compact 后写 system/compact_boundary 消息作为恢复锚点

---

## 6. 工具系统与 QueryEngine 的契约

QueryEngine 依赖工具系统提供 5 件事：
1) 可枚举工具清单（注册中心）
2) 结构化输入 schema
3) 统一执行结果 ToolResult
4) 权限前置检查
5) 生命周期事件

没有这 5 件事，QueryEngine 无法稳定编排。

---

## 7. Compact 原理与接入点

compact 本质是“会话内存管理”，不是一个普通命令。

建议先做 MVP 分层：
1) Tool Result Budget（先裁 tool_result 大输出）
2) Snip（去重复低价值消息）
3) Autocompact（历史段摘要）
4) Reactive Compact（API 超限后兜底）

接入原则：
- CompactEngine 由 QueryEngine 调用
- 压缩后必须生成 compact_boundary 并落盘
- Resume 依赖 boundary 识别“已总结区”和“保留段”

---

## 8. 从 TUI 到 QueryEngine 的分阶段改造路线

### 阶段 1：拆分职责
- 把“调模型/调工具/写消息”的逻辑从 TUI 抽离到 Engine 服务层
- TUI 仅保留交互与渲染

### 阶段 2：先立消息模型与存储
- 先做 session + turn + tool_call_id 的结构化持久化
- 没有这一步，后面 compact 与恢复都不成立

### 阶段 3：接入最小工具闭环
- FileRead/FileWrite/Bash(受限)
- 实现 tool_call -> tool_result 回写

### 阶段 4：接入权限与审批
- 工具 allow/deny
- 路径沙箱
- 高风险动作策略

### 阶段 5：接入 compact MVP
- 先自动 compact，不要求先有 /compact 命令
- 实现 compact_boundary 落盘

### 阶段 6：命令系统与会话控制
- /help /clear /resume /status /compact
- 将命令映射到 Engine 控制操作

### 阶段 7：扩展能力
- Glob/Grep -> FileEdit -> MCP/LSP -> 子 Agent

---

## 9. 关键设计原则（避免返工）

1) 先定义协议，再堆工具
2) 先做结构化存储，再做花哨 UI
3) 先保证可恢复，再追求高并发
4) 先做安全前置，再开放执行能力
5) 先做 compact 基础设施，再做 /compact 交互入口

---

## 10. 完成标准（你可以用来验收架构是否成型）

达到以下 8 条，说明你已经从“聊天框”跨到“Claude Code 类系统”：
1) QueryEngine 驱动每轮执行
2) 工具调用全链路可回放（tool_call_id 可追踪）
3) 多轮会话可持续，不丢状态
4) 权限拒绝可记录可解释
5) 长会话有自动 compact
6) compact 后可 resume
7) UI 不承载业务编排
8) 出问题能定位到“哪轮、哪工具、哪策略”

---

## 11. 你当前最优先的两件事

结合你现在进度，优先级建议：
1) 先把消息存储模型 + turn/tool_call_id 落地
2) 再把 compact MVP 接进 QueryEngine（哪怕先不暴露 /compact）

一句话总结：
先把“会话内核”做对，再把“工具外壳”做大。