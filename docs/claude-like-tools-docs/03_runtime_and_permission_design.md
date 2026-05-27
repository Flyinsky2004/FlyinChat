# 03｜运行时与权限（类设计+流程）

## 1. Registry
```python
# src/core/registry.py
class ToolRegistry:
    def __init__(self): self._tools = {}
    def register(self, tool):
        if tool.meta.name in self._tools:
            raise ValueError('duplicate tool')
        self._tools[tool.meta.name] = tool
    def get(self, name): return self._tools.get(name)
    def list_names(self): return sorted(self._tools)
```

## 2. Permission Engine
```python
# src/security/permission.py
from dataclasses import dataclass
from typing import Literal

Decision = Literal['allow','deny','ask']

@dataclass
class PermissionDecision:
    decision: Decision
    reason: str = ''
```

决策顺序：
1) 工具暴露前过滤（feature/env）
2) denied_tools 命中 -> deny
3) allowed_tools 非空且未命中 -> deny
4) risk_level=high 且 mode=ask -> ask
5) 默认按 mode

## 3. Executor 主流程
```python
# src/core/executor.py
class ToolExecutor:
    def __init__(self, registry, permission_engine, audit_store): ...

    def execute(self, tool_name: str, args: dict, ctx) -> ToolResult:
        # 1 lookup
        # 2 emit tool.start
        # 3 permission precheck
        # 4 run tool
        # 5 normalize errors
        # 6 audit + emit complete/error
```

## 4. 审计记录格式
```json
{
  "session_id":"...",
  "turn_id":"...",
  "tool":"bash",
  "args_summary":"pytest -q",
  "decision":"allow|deny|ask",
  "ts":"..."
}
```

## 5. 验收测试
- duplicate register 抛错
- deny 路径返回 PERMISSION_DENIED
- ask 路径进入 pending_approval
- executor 对异常统一映射 INTERNAL_ERROR
