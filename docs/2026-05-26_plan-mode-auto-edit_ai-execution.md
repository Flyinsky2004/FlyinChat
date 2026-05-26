# Plan Mode + Auto Edit 实施文档（给 AI 执行）

> 目标读者：执行型 AI Agent
> 目标：在现有 QueryEngine/Agent 架构中新增 Plan Mode 与 Auto Edit，并保证可回滚、可验证、可审计。

## 0. 执行约束（必须遵守）

1. 先实现 Plan Mode 的“硬门禁”，再实现 Auto Edit。
2. 任何写文件/执行命令能力都必须经过统一 Tool Gate，不允许绕过。
3. 每一步改动后都要运行最小验证；失败立即回滚当前补丁。
4. 所有决策写入审计日志（mode、tool、decision、reason、turn_id）。

---

## 1. 交付物清单

1) 模式状态管理
- session_state.mode: normal | plan | auto_edit
- session_state.approval_policy: ask | auto

2) Tool Gate（统一前置鉴权）
- plan 模式只允许 read/search/list 等只读工具
- auto_edit 模式允许 edit/patch + 受控验证命令

3) Plan 输出契约
- 结构化 JSON（可转 markdown）
- 字段：title, goal, assumptions, steps[], files_to_change[], tests[], risks[], rollback

4) Auto Edit 执行器
- PatchIntent 生成
- 安全应用（基于 old_snippet 匹配）
- 验证执行
- 失败回滚

5) 审计与追踪
- decision log + patch history + rollback record

---

## 2. 数据结构（先实现）

```python
from dataclasses import dataclass, field
from typing import Literal, List, Optional, Dict, Any

Mode = Literal["normal", "plan", "auto_edit"]
Approval = Literal["ask", "auto"]

@dataclass
class SessionState:
    mode: Mode = "normal"
    approval_policy: Approval = "ask"

@dataclass
class PlanStep:
    id: str
    content: str
    done: bool = False

@dataclass
class PlanDoc:
    title: str
    goal: str
    assumptions: List[str]
    steps: List[PlanStep]
    files_to_change: List[str]
    tests: List[str]
    risks: List[str]
    rollback: List[str]

@dataclass
class PatchIntent:
    file_path: str
    old_snippet: str
    new_snippet: str
    reason: str
    risk: Literal["low", "medium", "high"] = "low"

@dataclass
class ApplyResult:
    ok: bool
    file_path: str
    backup_path: Optional[str] = None
    error: Optional[str] = None
    changed_lines: int = 0
```

---

## 3. Tool Gate 规则

### 3.1 风险分级
- read-only: read_file/search/list
- write: patch/write/edit
- exec: terminal/command
- dangerous: delete/reset/network mutation

### 3.2 决策表
1) mode=plan
- allow: read-only
- deny: write/exec/dangerous

2) mode=auto_edit
- allow: write + 允许列表中的验证命令
- ask/deny: dangerous

3) mode=normal
- 按现有策略

### 3.3 伪代码

```python
def gate(mode, tool_name, risk, approval_policy):
    if mode == "plan" and risk != "read-only":
        return (False, "PLAN_MODE_DENY")
    if mode == "auto_edit" and risk == "dangerous":
        return (approval_policy == "auto", "NEED_APPROVAL")
    return (True, "OK")
```

---

## 4. Plan Mode 实施步骤

### Task P1: 增加 mode 命令入口
- /plan on -> mode=plan
- /plan off -> mode=normal
- /autoedit on -> mode=auto_edit
- /autoedit off -> mode=normal

### Task P2: prompt 注入
- 系统提示中注入“当前模式约束”
- 注意：提示仅作软约束，真正限制在 Tool Gate

### Task P3: Plan 输出校验
- 当 mode=plan，若输出不符合 PlanDoc schema，则请求模型重试
- 最多重试 N 次，失败则返回模板并要求补全

---

## 5. Auto Edit 实施步骤

### Task A1: 生成 PatchIntent
- 模型返回 intents[]，每个 intent 必须含 file_path/old_snippet/new_snippet/reason

### Task A2: 安全应用补丁
1. 读取目标文件
2. 精确匹配 old_snippet
3. 匹配到且唯一 -> 替换
4. 匹配失败/多处命中 -> 拒绝并回传错误给模型

### Task A3: 备份与回滚
- 应用前生成备份文件（同目录 .bak + timestamp）
- 验证失败则恢复备份
- 记录 rollback 事件

### Task A4: 自动验证
- 先跑最小验证（只跑受影响测试）
- 再跑扩展验证（可选）
- 验证命令必须在 allowlist 内

---

## 6. 验收标准（必须全部通过）

1. plan 模式下，任何写操作均被 gate 拒绝。
2. plan 输出始终可解析为 PlanDoc。
3. auto_edit 能完成“改动 -> 验证 -> 成功提交结果”。
4. 验证失败时自动回滚，文件内容与改动前一致。
5. 审计日志可追踪每次 decision/apply/rollback。

---

## 7. 测试用例（最小集）

1) test_plan_mode_denies_write_tool
2) test_plan_mode_allows_read_tool
3) test_auto_edit_apply_success
4) test_auto_edit_old_snippet_not_found
5) test_auto_edit_validation_fail_triggers_rollback
6) test_audit_log_contains_gate_and_apply_events

---

## 8. 执行顺序（不要调整）

1. SessionState + mode 切换
2. Tool Gate
3. PlanDoc schema + plan 输出约束
4. PatchIntent + apply/rollback
5. 验证流水线
6. 测试补齐

---

## 9. 风险与防护

- 风险：模型给出错误 old_snippet
  - 防护：严格匹配 + 失败重试

- 风险：auto 模式误改关键文件
  - 防护：高风险路径强制 ask（如配置、迁移脚本、删除操作）

- 风险：验证命令有副作用
  - 防护：验证命令 allowlist，仅允许测试/lint/build-check

---

## 10. 完成定义（DoD）

- 所有最小测试通过。
- 人工抽查 2 个场景：
  1) plan 模式写文件被拒
  2) auto_edit 验证失败自动回滚
- 文档更新：用户说明 + 开发说明同步。
