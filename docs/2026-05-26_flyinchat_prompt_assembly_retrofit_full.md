FlyinChat 提示词系统改造总文档（给你 + 给 AI Agent）
版本：v1.0
日期：2026-05-26

====================
0. 文档目的
====================
本文件整合以下内容到一处：
1) 现状与缺陷分析
2) 改造目标与架构
3) 面向 AI Agent 的实施步骤
4) 验收标准、风险、回滚
5) 可直接落地的提示词模板与伪代码

目标：让 FlyinChat 从“仅靠权限门禁兜底”升级为“提示词前置约束 + 门禁兜底”的双保险系统。


====================
1. 现状确认（基于你提供的信息）
====================
1) 新对话发送给 LLM 的消息结构：
- messages: 只有用户原始消息
- tools: 文件读取 / 文件写入 / bash
- 没有默认 system prompt

2) 唯一 system 消息来源：compact_summary（对话压缩摘要）
- 触发：预估 token 超 soft_limit（上下文窗口约 85%）
- 生成：compact.py 用摘要提示词压缩历史
- 存储：role=system, type=compact_summary
- 发送：message_utils 转为 API system 消息
- API 差异：Anthropic 放 body["system"]，OpenAI 兼容保留 messages 中

3) 当前模式（Plan/Auto Edit/YOLO/Normal）
- 只在前端/权限层生效（_apply_mode_permissions）
- 模型本身不知道当前模式
- 结果：模型先调用，再收到 PERMISSION_DENIED


====================
2. 核心缺陷
====================
缺陷1：无基础系统提示词（Base System Prompt）
影响：角色、任务边界、安全边界不稳定。

缺陷2：模式信息未注入模型上下文
影响：Plan 模式仍尝试编辑/执行，产生大量无效调用。

缺陷3：compact_summary 被动承担 system 角色
影响：它只描述“历史”，不能表达“当前策略/模式约束”。

缺陷4：缺少提示词分层装配机制
影响：无法根据运行时状态动态拼接，扩展成本高。

缺陷5：当前是事后纠错而非事前引导
影响：token 浪费、回合增多、体验变差。


====================
3. 改造目标
====================
目标A：建立分层提示词架构（不是一条超长静态 prompt）。
目标B：模式规则前置注入模型，让模型先遵守再行动。
目标C：保留并强化权限门禁，形成软硬双约束。
目标D：让 compact_summary 回归“历史摘要”定位，不承担策略主控。


====================
4. 目标架构（Prompt Assembler）
====================
每轮请求发送前，统一装配：

Final Prompt Context =
  BaseSystem
+ RuntimeModeSection
+ SafetyPolicySection
+ ContextSection（环境/Git/用户偏好/工作目录）
+ CompactSummarySection（可选）
+ UserMessage
+ ToolSchemas

说明：
- BaseSystem：稳定身份与行为总纲
- RuntimeModeSection：当前模式规则（normal/plan/auto_edit/yolo）
- SafetyPolicySection：工具使用优先级、审批边界
- CompactSummarySection：仅保留历史，不写策略


====================
5. 实施步骤（按优先级）
====================
阶段1：MVP（必须先做）
1) 增加 Base System Prompt（固定存在，即使无 compact）
2) 每轮注入 Mode Section（让模型提前知道约束）
3) 保留现有 Permission Gate（兜底拒绝）
4) 增加最小回归测试（Plan 模式违规调用下降）

阶段2：结构化升级
5) 新建 PromptAssembler 模块
6) 引入 Prompt Sections（可开关、可排序、可限长）
7) provider 适配统一语义（Anthropic/OpenAI）

阶段3：可观测与稳定性
8) 指标埋点：
   - permission_denied_rate
   - plan_mode_edit_attempt_rate
   - avg_turns_to_completion
   - compact_after_mode_consistency
9) 回归套件扩展到多 provider + 压缩场景


====================
6. 代码改造点（按你现有模块）
====================
1) query_engine.py
- 在构建 messages 前调用 PromptAssembler
- 输入 mode / approval_policy / compact_summary / env_context

2) message_utils.py
- 支持多来源 system 内容拼接
- 顺序建议：base -> mode -> safety -> context -> compact

3) api_client.py
- Anthropic：组装到 body["system"]（按其协议）
- OpenAI：system 保留在 messages
- 要求：语义一致，格式可不同

4) compact.py
- 继续只产出历史摘要
- 不注入模式策略，避免摘要语义污染

5) 权限层 _apply_mode_permissions()
- 逻辑保留
- 增加 deny 标准码与可读 reason（便于模型纠偏）


====================
7. 模式规则模板（可直接用）
====================
7.1 Base System Prompt（建议）
你是 FlyinChat 的工程任务代理。你的首要目标是在保证安全、可验证、可回滚的前提下完成用户任务。
行为原则：
1. 先理解目标，再行动；不确定时说明假设。
2. 优先最小改动，不做无关重构。
3. 每次有副作用的操作前，先检查是否被当前模式允许。
4. 优先使用专用工具，避免不必要的通用命令执行。
5. 输出要可执行、可验证、可追踪。

7.2 Mode Section: normal
当前模式：NORMAL
- 你可以进行正常分析与执行。
- 执行前先评估风险与必要性，优先最小变更。
- 若操作有潜在破坏性，先给出简短风险提示与回滚方案。

7.3 Mode Section: plan
当前模式：PLAN
强约束：
- 只允许分析、规划、方案比较。
- 禁止修改文件、禁止执行写操作命令、禁止破坏性操作。
输出要求：
- 给出结构化计划：目标、假设、步骤、影响文件、验证、风险、回滚。

7.4 Mode Section: auto_edit
当前模式：AUTO_EDIT
执行策略：
- 按计划分步修改。
- 每步必须：生成补丁 -> 应用 -> 验证 -> 记录结果。
- 验证失败必须立即回滚并报告失败原因。
- 高风险改动需要显式确认或走审批策略。

7.5 Mode Section: yolo
当前模式：YOLO
说明：
- 允许更高自动化执行，但仍需遵守底层安全门禁。
- 每步执行后必须输出：改动内容、验证结果、失败回滚状态。
- 即使在 YOLO 模式，也不能跳过关键验证与审计记录。


====================
8. Safety Policy Section 模板（建议）
====================
工具使用策略：
1) 先用专用工具，再考虑通用 shell。
2) 读/搜类工具优先于写/执行类工具。
3) 若当前模式禁止某操作，不要尝试调用该工具。
4) 若收到权限拒绝，立即调整方案，不要重复同类违规调用。

输出规范：
- 对每个执行步骤给出“目的 -> 动作 -> 结果 -> 下一步”。
- 对失败步骤给出“原因 -> 回滚状态 -> 替代方案”。


====================
9. Prompt Assembler 伪代码（Python）
====================
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class RuntimeState:
    mode: str  # normal|plan|auto_edit|yolo
    approval_policy: str  # ask|auto
    language: Optional[str] = None

@dataclass
class PromptSections:
    base: str
    mode: str
    safety: str
    context: str
    compact: str


def build_mode_section(mode: str) -> str:
    mapping = {
        "normal": MODE_NORMAL,
        "plan": MODE_PLAN,
        "auto_edit": MODE_AUTO_EDIT,
        "yolo": MODE_YOLO,
    }
    return mapping.get(mode, MODE_NORMAL)


def build_context_section(env_info: dict, git_info: dict, user_prefs: dict) -> str:
    parts = []
    if env_info:
        parts.append(f"环境信息: {env_info}")
    if git_info:
        parts.append(f"Git信息: {git_info}")
    if user_prefs:
        parts.append(f"用户偏好: {user_prefs}")
    return "\n".join(parts)


def assemble_system_prompt(state: RuntimeState,
                           compact_summary: Optional[str],
                           env_info: dict,
                           git_info: dict,
                           user_prefs: dict) -> str:
    sections = [
        BASE_SYSTEM_PROMPT.strip(),
        build_mode_section(state.mode).strip(),
        SAFETY_POLICY_PROMPT.strip(),
        build_context_section(env_info, git_info, user_prefs).strip(),
    ]
    if compact_summary:
        sections.append(("历史摘要（compact）:\n" + compact_summary).strip())
    return "\n\n".join([s for s in sections if s])


# query_engine.py 使用方式示意
# system_prompt = assemble_system_prompt(...)
# messages = [{"role": "system", "content": system_prompt}, ...history..., user_message]


====================
10. 与权限门禁的协同策略
====================
原则：提示词引导在前，门禁兜底在后。

门禁拒绝返回建议标准化：
- error_code: PLAN_MODE_DENY_WRITE
- error_code: MODE_DENY_EXEC
- error_code: APPROVAL_REQUIRED

并在 error message 中包含：
- 当前模式
- 被拒绝工具
- 推荐替代动作（例如“请改为输出计划”）

这样模型可快速自我纠偏，减少重复违规调用。


====================
11. 测试与验收标准
====================
11.1 最小测试用例
1) test_new_session_has_base_system_prompt
2) test_plan_mode_prompt_injected
3) test_plan_mode_reduces_edit_attempts
4) test_compact_summary_and_mode_coexist
5) test_provider_semantic_consistency_anthropic_openai
6) test_permission_denied_has_standard_error_code

11.2 验收标准（必须全部满足）
1) 无 compact 的新对话也带 system prompt。
2) Plan 模式下模型主动减少编辑类工具调用。
3) permission_denied_rate 明显下降（建议目标 >= 30%）。
4) compact 前后模式语义一致，不丢失。
5) Anthropic 与 OpenAI 链路语义一致。


====================
12. 风险、防护与回滚
====================
风险1：system 过长，挤占上下文
- 防护：各 section 限长；context/compact 做预算裁剪。

风险2：provider 差异导致行为漂移
- 防护：同用例双 provider 回归测试。

风险3：提示词规则与门禁规则不一致
- 防护：建立单一 mode policy registry，prompt 与 gate 共用一套规则源。

回滚方案：
- 增加 feature flag: enable_prompt_assembler
- 关闭后回退到旧链路（仅门禁模式）
- 保留新增日志与测试，不回滚


====================
13. 建议的上线顺序（稳态优先）
====================
第1批（当天可上）：
- Base System Prompt
- Mode Section 注入
- message_utils 拼装顺序固定

第2批：
- PromptAssembler 模块化
- 标准化拒绝码
- 指标埋点

第3批：
- section 动态预算
- 复杂上下文治理（Git/偏好/摘要权重）


====================
14. 完成定义（DoD）
====================
- 功能：模式信息已稳定注入模型。
- 安全：门禁策略无回归。
- 质量：最小测试集全部通过。
- 体验：Plan 模式无效工具调用显著减少。
- 运维：有可观测指标和可回滚开关。


====================
15. 一句话总括
====================
FlyinChat 现在缺的不是“更严门禁”，而是“门禁前的提示词治理层”。
先让模型知道规则，再让门禁兜底，才能把稳定性和效率一起拉起来。