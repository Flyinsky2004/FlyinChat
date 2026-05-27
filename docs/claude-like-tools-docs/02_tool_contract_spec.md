# 02｜Tool 契约规范（接口签名版）

## 1. Python 类型定义（必须落地）
```python
# src/core/tool_types.py
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol

RiskLevel = Literal['low', 'medium', 'high']

@dataclass
class ToolMeta:
    name: str
    description: str
    version: str
    risk_level: RiskLevel

@dataclass
class ToolResult:
    ok: bool
    content: str
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PermissionContext:
    mode: Literal['allow', 'deny', 'ask']
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    allowed_read_roots: List[str] = field(default_factory=list)
    allowed_write_roots: List[str] = field(default_factory=list)

@dataclass
class ToolContext:
    session_id: str
    turn_id: str
    workspace_root: str
    permission: PermissionContext
    emit: Callable[[str, Dict[str, Any]], None]

class Tool(Protocol):
    meta: ToolMeta
    def input_schema(self) -> Dict[str, Any]: ...
    def run(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult: ...
```

## 2. 统一错误码
- INVALID_INPUT
- PERMISSION_DENIED
- PATH_OUT_OF_WORKSPACE
- TOOL_TIMEOUT
- TOOL_NOT_FOUND
- INTERNAL_ERROR

## 3. 输入 Schema 规范
- 必须 `type: object`
- 必须声明 `properties`
- `additionalProperties: false`
- 必须显式 `required`

## 4. 生命周期事件
- tool.start: {tool, turn_id}
- tool.progress: {tool, step, detail}
- tool.complete: {tool, ok, ms}
- tool.error: {tool, error_code, detail}

## 5. 验收
- 任一 Tool 类实现上述 Protocol 即可被执行器调用
- 返回值必须是 ToolResult（禁止裸 dict/异常透传）
