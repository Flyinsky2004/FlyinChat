# MCP 客户端集成实施文档（面向 ClaudeCode-like 架构）

## 1. 文档目标与适用范围

**目标**：在现有系统中，把 MCP 从“能连通”升级为“可生产运行”的能力层，确保与 Query Engine、Tool System、Permission、Session/Compact、Observability、Recovery 协同稳定。

**适用前提**：
- 有多轮 Query Engine（支持 tool loop）
- 有工具注册/执行框架
- 有权限系统（allow/ask/deny）
- 有会话存储与上下文裁剪能力（至少雏形）

**不覆盖**：
- MCP 协议基础概念科普
- 具体 UI 实现（仅给契约要求）
- 模型策略细调（仅给接口要求）

---

## 2. 设计原则（先定约束再落实现）

1. **MCP 是工具来源，不是执行内核**  
   执行内核永远是统一 Tool Runtime，MCP 只是 Provider。

2. **Query Engine 不直接耦合 transport**  
   QE 只能看到统一工具接口，不知道 stdio/http/sse 细节。

3. **所有工具调用必须可追踪、可回放、可压缩后恢复**  
   每次调用必须有 `tool_call_id`，消息链不能断。

4. **权限前置、参数前置、风险前置**  
   先决策后调用；不能“调用后再拦截”。

5. **降级优先于失败**  
   MCP 失效时不应拖死整轮对话：要么 fallback，要么给可解释失败并继续。

---

## 3. 目标架构（逻辑分层）

```text
Query Engine
  └── Tool Orchestrator (plan/call/resume loop)
        └── Tool Executor (timeout/retry/permission/audit)
              └── Tool Registry (unified descriptors)
                    ├── Native Tools Provider
                    ├── MCP Provider A (stdio)
                    ├── MCP Provider B (http/sse)
                    └── ...
Session Store / Transcript / Compact Engine
Permission Engine
Observability & Event Bus
```

### 核心边界
- **QE ↔ Tool Executor**：只通过统一 ToolCall/ToolResult
- **Tool Executor ↔ MCP Provider**：只通过 Provider Adapter
- **Permission**：在 Executor 前置，不在 Provider 内“补判断”
- **Compact**：只消费结构化 transcript，不依赖 provider 内部日志

---

## 4. 统一契约（必须冻结）

> MCP 适配必须对齐这些契约。

### 4.1 ToolDescriptor（注册时）
最少字段：
- `name`（全局唯一，建议 `mcp_<server>_<tool>`）
- `description`
- `input_schema`（JSON schema）
- `source`（native/mcp/server_id）
- `risk_level`（low/medium/high）
- `capabilities`（read/write/network/shell/data_access 等标签）

### 4.2 ToolCall（执行请求）
- `tool_call_id`（全局唯一，单轮内不可重复）
- `name`
- `args`（原始 + 规范化后）
- `invocation_context`（session_id/turn_id/user_id/model_id）

### 4.3 ToolResult（执行返回）
- `ok`（bool）
- `content`（可直接回填 LLM 的文本摘要）
- `data`（结构化载荷，供后处理）
- `error_code`（标准错误枚举）
- `meta`（latency/provider/server/token/bytes/truncated 等）

---

## 5. MCP 与 Query Engine 协同机制

### 5.1 工具循环状态机（建议固定）
`THINK -> (TOOL_CALL? yes:no) -> EXECUTE -> APPEND_RESULT -> THINK ... -> FINAL`

#### 关键要求
- Query Engine 每轮最多 N 次工具调用（防失控）
- 每次工具结果必须 append 到 transcript（不能只写日志）
- 工具失败后 QE 要能做：重试 / 改参数 / 换工具 / 给用户可解释失败

### 5.2 上下文注入策略
QE 看到的工具信息建议三层：
1. **精简 catalog**（name + one-line purpose + risk）
2. **按需展开 schema**（只对被挑中的工具提供完整 schema）
3. **调用历史摘要**（最近 K 次，带 status/error_code）

避免把完整 MCP catalog 全量注入，防止 token 爆炸和工具选择漂移。

---

## 6. MCP 与 Permission System 协同

### 6.1 决策点
在 Tool Executor 调用 Provider 前执行：
- 工具级策略（是否允许该工具）
- 参数级策略（path/url/sql/query patterns）
- 会话级策略（trusted workspace / user confirmation state）
- 风险级策略（high risk 需 ask）

### 6.2 ask 模式与人机交互约束
- ask 决策必须可持久化（至少本 turn 或本 session）
- 用户授权对象应明确到“工具 + 参数哈希/范围”
- 禁止 ask 后扩大授权范围（防权限漂移）

### 6.3 与 MCP Server 自身权限的关系
MCP server 可能也有内建安全策略，但这不替代客户端权限闸。  
**客户端权限是第一责任边界**。

---

## 7. Session Store / Compact 协同（必须提前对齐）

### 7.1 transcript 事件类型建议
- `user_message`
- `assistant_message`
- `tool_call`
- `tool_result`
- `system_event`（compact_boundary, retry_notice, fallback_notice）

### 7.2 压缩不可丢字段
compact 后必须保留：
- `tool_call_id` 链接关系
- `tool_name`、`ok/error_code`、关键摘要
- 失败原因（供后续推理避免重复错误）

### 7.3 compact boundary
每次压缩建议写 boundary 元数据：
- source range
- summary anchor
- preserved tail ids
- tokens before/after

这样 resume/replay 才可靠。

---

## 8. Registry 与 Discovery 细节

### 8.1 discovery 时机
- 启动首次发现
- server reconnect 后增量刷新
- 配置变更触发手动 refresh

### 8.2 命名与冲突
- 工具名全局唯一：`mcp_<server>_<tool>`
- 同名冲突要 deterministic（拒绝或后缀策略），不能随机覆盖

### 8.3 schema 标准化
MCP 返回 schema 可能不一致（可选字段、描述缺失等），需统一归一化：
- 填充默认 type/object
- required 规范化
- enum/format 校验兜底
- 不可解析 schema 标记为不可调用并上报

---

## 9. 可靠性与故障处理

### 9.1 错误分层（建议固定错误码族）
- `PERMISSION_DENIED`
- `VALIDATION_ERROR`
- `TRANSPORT_UNAVAILABLE`
- `PROVIDER_TIMEOUT`
- `SERVER_EXEC_ERROR`
- `RESULT_TOO_LARGE`
- `RATE_LIMITED`
- `UNKNOWN`

### 9.2 重试策略
- 仅对可重试错误（网络抖动/超时）重试
- 不对权限错误、参数错误重试
- 指数退避 + 最大尝试次数 + budget 上限

### 9.3 fallback 策略
- 同功能替代工具（若存在）
- 降级为“无工具回答 + 说明不足”
- 标准化用户提示：说明失败、已尝试、下一步建议

---

## 10. 可观测性（上线后能定位问题的最低要求）

### 10.1 指标
- 工具调用总量 / 成功率 / 错误率（按 tool/server 维度）
- P50/P95/P99 延迟
- 平均结果大小与截断率
- 权限拒绝率（allow/ask/deny 分布）
- Query Engine 每轮工具调用次数分布

### 10.2 日志事件（结构化）
- `tool.start`：call_id, tool, args_hash, risk
- `tool.complete`：ok, latency_ms, bytes, truncated
- `tool.error`：error_code, provider_stage, retry_count
- `mcp.connection_state`：connected/disconnected/retrying
- `compact.applied`：tokens_before/after, boundary_id

### 10.3 追踪链路
统一 trace id：`session_id + turn_id + tool_call_id`  
保证从用户请求可追到具体 MCP 调用与返回。

---

## 11. 安全与治理要点（生产必做）

1. **最小暴露原则**：只注册需要的 MCP servers/tools
2. **参数脱敏日志**：token/password/path secrets 不落明文
3. **结果大小上限**：过大结果截断 + 摘要 + 原始保留策略（可选）
4. **执行超时硬限制**：避免 server 卡死拖垮 turn
5. **租户隔离（若多用户）**：会话与权限上下文不能串
6. **供应链治理**：第三方 MCP server 版本锁定与审计

---

## 12. 与现有模块的协同验收矩阵（建议直接做成测试清单）

### 12.1 QE × MCP
- 模型选择工具 -> 成功调用 -> 结果回填 -> 最终回答
- 连续多工具调用链路可收敛
- 工具失败后 QE 可自愈（重试/替代/降级）

### 12.2 Permission × MCP
- deny 正确阻断，不触发 provider 调用
- ask 授权只作用于预期范围
- 参数越界可阻断并回传可解释错误

### 12.3 Session/Compact × MCP
- 历史压缩后仍能保持 tool_call/tool_result 语义
- resume 后模型能读懂历史工具结论
- boundary 存在且可用于恢复

### 12.4 Registry/Discovery × MCP
- server 上下线、工具增删后可稳定刷新
- 命名冲突行为可预测且可观测
- schema 异常不会污染整个运行时

---

## 13. 分阶段落地路线（可直接套用）

### Phase 1：契约冻结
- 冻结 ToolDescriptor/ToolCall/ToolResult
- 冻结错误码与事件模型

### Phase 2：执行内核对齐
- MCP provider 接入统一 Executor
- 权限前置、超时与重试策略接管

### Phase 3：会话与压缩打通
- transcript 增加 tool_call/tool_result
- compact 保留调用链语义与 boundary

### Phase 4：可观测性与灰度
- 完整指标/日志/trace
- 小流量灰度 + 回滚开关 + 故障演练

### Phase 5：策略优化
- tool selection prompt tuning
- catalog 精简与动态展开
- 失败模式收敛与性能优化

---

## 14. 常见反模式（明确避免）

1. MCP 直接暴露给 QE（跳过统一 Executor）
2. 工具结果只写普通文本，不写结构化事件
3. compact 丢掉调用关联 id
4. permission 只做工具名，不做参数审计
5. 失败直接中断 turn，不给 QE 继续推理机会
6. 把所有 MCP tool schema 全量塞进 prompt

---

## 15. 结论（可作为设计文档摘要）

系统已有 Query Engine / Tool / Permission 是良好基础。  
MCP 的关键不是“能调用”，而是：

- **统一协议化**（MCP Provider 只是插件源）
- **执行可治理**（权限、超时、重试、错误码、审计）
- **会话可持续**（结构化回填、compact 不断链、可恢复）

做到这三点，MCP 才是稳定生产能力，而不是 demo 能力。
