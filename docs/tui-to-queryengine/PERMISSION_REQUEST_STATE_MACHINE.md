# 权限请求状态机设计（给 AI 直接实现）

## 1. 目标

把“工具权限询问”做成可执行、可追溯、可恢复的系统能力。

设计目标：
- 把 allow / deny / ask 统一成状态机，而不是散落 if-else
- 审批过程可落盘（重启后不丢）
- 审批结果可回写会话消息链（便于回放与审计）

---

## 2. 适用范围

适用于会触发系统副作用的工具调用，典型如：
- 文件写入/编辑
- Shell 命令执行
- 外部资源访问
- 远程或后台任务操作

不适用于：
- 普通业务澄清提问（那是 AskUserQuestionTool 路线）

---

## 3. 核心概念

### 3.1 Permission Decision
- allow：直接执行
- deny：直接拒绝
- ask：进入审批流程

### 3.2 Permission Request
一次“待用户审批”的权限请求实体，必须可持久化。

建议字段：
- request_id
- session_id
- turn_id
- tool_call_id
- tool_name
- args_preview（脱敏后的参数摘要）
- risk_level（low/medium/high）
- reason（为何需要审批）
- status（见下文状态机）
- created_at / expires_at / resolved_at
- resolved_by（user/system）
- resolution（approve/deny/timeout/cancel）

---

## 4. 状态机定义

状态集合：
- CREATED（已创建）
- PENDING_USER_APPROVAL（等待用户审批）
- APPROVED（已批准）
- DENIED（已拒绝）
- EXPIRED（超时）
- CANCELLED（被取消，例如会话中断）
- EXECUTED（批准后已执行完成）
- FAILED_AFTER_APPROVAL（批准了但执行失败）

状态迁移：
1) CREATED -> PENDING_USER_APPROVAL
2) PENDING_USER_APPROVAL -> APPROVED（用户批准）
3) PENDING_USER_APPROVAL -> DENIED（用户拒绝）
4) PENDING_USER_APPROVAL -> EXPIRED（超时）
5) PENDING_USER_APPROVAL -> CANCELLED（会话取消）
6) APPROVED -> EXECUTED（工具执行成功）
7) APPROVED -> FAILED_AFTER_APPROVAL（工具执行失败）

约束：
- DENIED/EXPIRED/CANCELLED 为终态，不可再执行
- APPROVED 后只能执行一次（防重放）

---

## 5. 与 QueryEngine 的集成点

在 QueryEngine 工具调用前，按顺序处理：

1) pre-exposure filter
- 工具是否对当前会话可见

2) runtime permission gate
- match allow/deny/ask

3) 分支：
- allow：直接执行工具
- deny：写 denial 消息并结束该工具调用
- ask：创建 PermissionRequest，进入 PENDING_USER_APPROVAL，暂停该工具调用

4) 收到审批结果后：
- approve：恢复该工具调用执行
- deny/timeout/cancel：回写拒绝结果，模型继续（或结束本轮）

关键：
- ask 分支必须支持“异步等待 + 恢复”
- request_id 与 tool_call_id 必须关联

---

## 6. 消息链落盘规范（必须）

每次权限流程都要进 transcript，建议用 system 子类型消息：

1) permission_request_created
- 记录 request_id、tool_name、args_preview、risk_level

2) permission_request_resolved
- 记录 resolution（approved/denied/timeout/cancel）

3) permission_effect_applied
- approved 后工具执行成功/失败结果摘要

示例字段：
- role=system
- subtype=permission_event
- permission_metadata={request_id, status, resolution, tool_call_id, reason}

这样你能在回放时完整看到：
“为什么问、谁批了、最后执行结果是什么”。

---

## 7. 审批 UI 与交互约束

UI 需要展示：
- 工具名
- 风险级别
- 参数摘要（脱敏）
- 可选动作（Approve / Deny）
- 过期倒计时

安全要求：
- 默认焦点在 Deny（可选策略）
- 高风险工具必须显示二次确认文案
- 不允许模型文本伪造审批结果，审批结果只能来自 UI 事件

---

## 8. 超时与中断策略

推荐默认：
- 审批超时 60~180 秒（按场景）
- 超时后状态转 EXPIRED
- QueryEngine 收到 EXPIRED 后按 deny 分支处理

会话中断：
- 中断时将 pending 请求转 CANCELLED
- resume 后不得自动恢复执行，必须重新发起请求

---

## 9. 审计与可观测性

每个请求至少记录日志字段：
- session_id
- turn_id
- request_id
- tool_name
- decision_path（allow/deny/ask）
- final_status
- elapsed_ms

指标建议：
- ask_rate（触发审批比例）
- approval_rate
- deny_rate
- timeout_rate
- failed_after_approval_rate

---

## 10. 最小实现清单（AI 执行）

1) 数据模型
- PermissionRequest
- PermissionDecision

2) 状态机模块
- transition(current, event) -> next
- 非法迁移抛错

3) 持久化
- request create/update/query
- 与 session_id/tool_call_id 索引

4) QueryEngine 集成
- 工具调用前 permission gate
- ask 分支暂停与恢复

5) transcript 事件写入
- request_created / resolved / effect_applied

6) 基础测试
- 正常批准执行
- 用户拒绝
- 超时过期
- 会话取消
- 批准后执行失败

---

## 11. 和 AskUserQuestionTool 的职责边界

Permission Request：
- 用于“是否允许执行高风险动作”
- 属于安全控制面

AskUserQuestionTool：
- 用于“业务澄清/方案选择”
- 属于任务协作面

二者绝不能混用。

---

## 12. 一句话结论

把权限请求做成状态机并落盘，是你从“能跑工具”走向“可控工程代理”的分水岭。