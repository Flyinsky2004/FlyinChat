# Compact 实现设计（面向你的自研 Claude-like 系统）

## 1. 目标与约束

目标：
- 在“工具调用轮次很多、工具输出很大”的情况下保持会话可持续。
- 尽量延后信息损失：先局部瘦身，再全局摘要。
- 压缩后仍可 resume，并能知道哪些历史被总结、哪些被保留。

约束：
- 你当前还没有 `/compact` 命令与高级工具，不影响先做自动 compact 管线。
- 当前阶段先做“最小可用版本（MVP）”，后续再补 microcompact/collapse 高级策略。


## 2. 参考机制（来自调研）

从专题调研到的核心链路（query.ts 思路）：
1) `applyToolResultBudget`
2) `snip`
3) `microcompact`
4) `context collapse`
5) `autocompact`
6) `reactive compact`（报错兜底）

关键设计点：
- 压缩不是一次性摘要，而是分层升级。
- `buildPostCompactMessages` 会重建压缩后的消息链。
- `compact_boundary` 作为系统消息写入会话，作为恢复锚点。
- 会话层还维护 collapse commit/snapshot 等元信息。


## 3. 你这套系统的落地架构

新增 4 个组件：

1) `ConversationStore`
- 负责持久化消息链与 compact 边界

2) `CompactionEngine`
- 负责执行多阶段 compact 管线

3) `TokenEstimator`
- 粗估消息体量（先用字符数近似，后续可接 tokenizer）

4) `CompactionPolicy`
- 统一阈值与策略开关


## 4. 消息与边界数据模型（建议）

### 4.1 Message
```json
{
  "id": "msg_xxx",
  "session_id": "s1",
  "turn_id": 12,
  "role": "user|assistant|tool|system",
  "subtype": "normal|tool_call|tool_result|compact_boundary",
  "created_at": "2026-05-26T00:00:00Z",
  "content": "...",
  "tool_call": {
    "tool_call_id": "tc_123",
    "tool_name": "file_read",
    "args": {"path": "a.py"}
  },
  "tool_result": {
    "tool_call_id": "tc_123",
    "ok": true,
    "error_code": null,
    "data": {}
  },
  "compact_metadata": null,
  "meta": {"tokens_est": 120}
}
```

### 4.2 Compact Boundary (system message)
```json
{
  "role": "system",
  "subtype": "compact_boundary",
  "content": "compaction applied",
  "compact_metadata": {
    "boundary_id": "cb_001",
    "strategy": "autocompact_v1",
    "source_range": {"from_msg_id": "msg_10", "to_msg_id": "msg_88"},
    "preserved_segment": {
      "head_msg_ids": ["msg_85", "msg_86"],
      "tail_msg_id": "msg_88"
    },
    "summary_msg_id": "msg_sum_1",
    "tokens_before": 42000,
    "tokens_after": 12000
  }
}
```


## 5. MVP Compact 管线（先实现这个）

### 阶段 A：Tool Result Budget（必须）
- 针对 `role=tool, subtype=tool_result` 的大文本做截断。
- 保留头尾 + `...[truncated N chars]` 标记。
- 对结构化 data 保留关键字段，不要全删。

### 阶段 B：Snip（必须）
- 删掉低价值重复消息（例如重复进度日志）。
- 连续工具进度消息可合并为单条摘要。

### 阶段 C：Autocompact（必须）
- 对“较早历史段”生成一条 summary system/assistant 消息。
- 形成 `post_compact_messages = [preserved recent messages + summary + boundary]`。

### 阶段 D：Reactive Compact（建议）
- 如果模型调用返回 context too long，再做一轮更激进压缩。


## 6. 触发策略

自动触发（建议先做）：
- `estimated_tokens(messages) > soft_limit * 0.85` => 执行 A/B
- `estimated_tokens(messages) > soft_limit` => 执行 A/B/C

失败兜底触发：
- API 返回 `context_length_exceeded` / `413` => 执行 Reactive Compact

手动触发（后续再做 /compact 命令）：
- 当前阶段可先暴露内部函数 `force_compact(session_id, hint=None)`。


## 7. 与工具轮次记录的关系（关键）

你要保证：
- 每次工具调用有 `tool_call_id`
- 工具请求消息（assistant tool_call）与工具结果消息（tool_result）可关联
- compact 时优先保留“调用结构”，再压缩“结果正文”

最小保留规则：
- 永远保留最近 N 轮完整对话（建议 2~4 轮）
- 历史区可摘要，但保留 tool_call 的结构索引


## 8. 接口设计（建议）

```python
class CompactionEngine:
    def compact_if_needed(self, messages: list[Message], policy: CompactionPolicy) -> CompactionOutput:
        ...

    def reactive_compact(self, messages: list[Message], reason: str) -> CompactionOutput:
        ...
```

输出：
```python
@dataclass
class CompactionOutput:
    applied: bool
    messages: list[Message]
    boundary_message: Message | None
    tokens_before: int
    tokens_after: int
    strategy: str
```


## 9. 先做什么，不做什么

先做：
- ToolResultBudget + Snip + Autocompact + CompactBoundary 落盘
- resume 时识别 boundary

暂不做：
- 复杂 `context collapse commit/snapshot` 细粒度重投影
- 真 tokenizer 精算
- 多模态媒体特例


## 10. 验证用例（必须）

1) 长工具输出压缩
- 构造 50KB tool_result
- 触发后消息长度下降，且保留 tool_call_id 关联

2) 多轮后自动 compact
- 超阈值后出现 `compact_boundary`
- `tokens_after < tokens_before`

3) resume 正确性
- 读取会话后能识别 boundary
- 最近 N 轮原样可用

4) 失败兜底
- 模拟 context too long
- reactive compact 后可继续请求


## 11. 一句话落地建议

你的系统现在最该做的是：
“先把 tool_result 大文本治理 + compact_boundary 落盘做起来”，
这两件事完成后，再补 `/compact` 命令只是 UI 入口问题，不是架构问题。