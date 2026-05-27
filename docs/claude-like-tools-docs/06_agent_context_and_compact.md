# 06｜会话模型与 Compact（M3 实施版）

## 1. Message 数据模型
文件：`src/session/message_store.py`
```python
@dataclass
class Message:
    id: int
    session_id: str
    turn_id: str
    role: str               # user/assistant/tool/system
    subtype: str            # tool_call/tool_result/compact_boundary
    content: str
    tool_call_id: str|None = None
    created_at: str = ''
```

## 2. CompactEngine 接口
文件：`src/session/compact_engine.py`
```python
class CompactEngine:
    def run(self, session_id: str) -> dict:
        # stage1 budget
        # stage2 snip
        # stage3 microcompact
        # stage4 collapse
        # stage5 autocompact
        # stage6 reactive compact
```

## 3. Boundary 持久化
文件：`src/session/boundary_store.py`
保存字段：
- boundary_id
- source_start_id/source_end_id
- summary_message_id
- preserved_tail_ids
- tokens_before/tokens_after

## 4. 触发规则（建议）
- soft threshold: 70% token
- hard threshold: 90% token -> 触发 reactive compact

## 5. 验收
- 人工构造 500+ 消息会话
- 验证压缩后仍可查到最近 tool_call_id 对应结果
