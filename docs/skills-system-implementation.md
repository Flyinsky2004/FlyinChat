# Skills 系统实施文档（面向 ClaudeCode-like 架构）

## 1. 文档目标与适用范围

**目标**：在现有 Query Engine / Tool System / Permission System 基础上，实现可生产化的 Skills 系统，使其具备：
- 稳定的技能检索与决策能力
- 与规划/执行环节的强协同（不止 prompt 拼接）
- 可观测、可审计、可版本治理
- 可与 Session/Compact 共存并可恢复

**适用前提**：
- 已有多轮 Query Engine（tool loop）
- 已有统一 Tool Executor
- 已有 Permission Gate
- 已有会话存储与上下文压缩机制（至少可扩展）

**不覆盖**：
- 具体 UI 交互细节
- 向量数据库选型争论
- 模型微调策略

---

## 2. 设计原则

1. **Skill 是过程知识，不是工具定义**  
   Tool 负责“能做什么”，Skill 负责“什么时候、按什么流程做”。

2. **Skill 不是纯文本提示词**  
   技能中的硬约束必须可下沉到运行时（Permission/Executor Guard）。

3. **Skill 选择是显式决策**  
   必须记录 why selected / why skipped，便于审计和回放。

4. **Skill 与会话生命周期绑定版本**  
   同一会话中固定 skill@version，避免中途漂移。

5. **最少注入原则**  
   每轮仅注入必要技能（1~3 个），避免上下文污染与工具误选。

---

## 3. 总体架构与模块边界

```text
User Query
  -> Intent Router
  -> Skill Resolver (retrieve/rank/select)
  -> Skill Compiler (prompt fragments + runtime guards)
  -> Query Engine Planner
  -> Tool Executor Loop
  -> Session Store / Compact Engine

Cross-cutting:
- Permission System
- Observability / Audit
- Skill Registry / Version Manager
```

### 核心职责
- **Skill Registry**：存储、版本、索引、依赖关系
- **Skill Resolver**：召回与排序，输出候选与决策理由
- **Skill Compiler**：把 Skill 转成“规划提示 + 运行时约束”
- **Query Engine**：消费编译结果，执行 plan/call/resume
- **Permission**：执行 Skill 派生的强约束
- **Session/Compact**：保留 skill 选择与执行阶段状态

---

## 4. Skill 数据模型与文件格式（契约冻结）

## 4.1 Skill 文件格式（推荐：SKILL.md + YAML Frontmatter）
建议采用单技能目录结构：

```text
skills/
  <category>/
    <skill-name>/
      SKILL.md
      references/   # 可选：长篇背景资料
      templates/    # 可选：模板
      scripts/      # 可选：脚本
      assets/       # 可选：静态资源
```

`SKILL.md` 推荐形态：

```markdown
---
name: example-skill
description: Use when ...
version: 1.0.0
category: software-development
author: Team
metadata:
  tags: [tag1, tag2]
  related_skills: [another-skill]
---

# Title

## Overview
...

## When to Use
...

## Workflow
...

## Pitfalls
...

## Verification Checklist
...
```

### 格式约束（建议设为校验器规则）
- 文件必须以 frontmatter `---` 开始并闭合
- frontmatter 必须是 YAML object
- 必填：`name`, `description`
- 建议必填：`version`, `category`, `metadata.tags`
- 正文必须非空
- `name` 使用小写 slug（`[a-z0-9-_]`）且全局唯一
- `description` 控制长度（例如 <= 1024）

## 4.2 Skill Manifest（逻辑字段）
- `name`: 唯一标识（slug）
- `description`: 建议以 "Use when ..." 开头
- `version`: 语义版本
- `category`: domain 分类
- `triggers`: 关键词与意图标签
- `constraints`: 硬约束（可映射到 runtime guard）
- `workflow`: 建议步骤（可选）
- `pitfalls`: 常见错误
- `verification`: 验收检查项
- `related_skills`: 依赖/互补技能
- `priority`: 冲突时默认优先级
- `source`: repo/user/plugin
- `updated_at`, `author`

## 4.3 运行时结构
- `SkillDecision`:
  - `selected`: [skill@version]
  - `rejected`: [{skill, reason}]
  - `confidence`
  - `policy_overrides`
- `SkillRuntimeState`:
  - `active_phase`（discover/apply/verify 等）
  - `guards_applied`
  - `last_transition_at`
- `LoadedSkill`:
  - `manifest`
  - `content_sections`（overview/workflow/pitfalls...）
  - `linked_resources`（references/templates/scripts 索引）
  - `checksum`（用于缓存失效）

## 4.4 Skill 内容解析建议
解析阶段把 markdown 分段为结构化 section，避免运行时反复正则切分：
- `overview`
- `when_to_use`
- `workflow`
- `pitfalls`
- `verification_checklist`

若缺失 section，不应直接报错；可降级为“仅文本技能”，但在质量报告中标记。
---

## 5. Skill 加载机制（Loader / Cache / Refresh）

## 5.1 加载来源与优先级
建议支持多来源，并定义固定优先级（高 -> 低）：
1. session 临时注入技能（实验/调试）
2. 项目内技能（repo）
3. 用户本地技能（user-local）
4. 插件技能（plugin）

同名冲突按优先级覆盖，并写入冲突日志。

## 5.2 启动加载流程
1. 扫描技能目录并构建文件索引
2. 读取 SKILL.md frontmatter 与正文
3. 执行 schema/格式校验
4. 解析正文 section（overview/workflow/...）
5. 构建倒排索引与语义索引（可选）
6. 生成 `LoadedSkill` 缓存（含 checksum）

若某个技能校验失败：
- 标记为 `invalid`
- 不进入可用索引
- 产出诊断报告（文件、行、原因）

## 5.3 热更新与缓存失效
推荐策略：
- 开发模式：watch 文件变更，增量刷新
- 生产模式：定时刷新或管理命令触发刷新
- 以 `checksum(path+content)` 判断缓存是否失效

刷新时要保证原子切换：
- 新索引构建成功后一次性替换旧索引
- 构建失败保持旧索引可用（避免服务抖动）

## 5.4 会话一致性
- 会话创建时固化 `skill@version` 引用
- 刷新后不影响进行中的会话（除非显式允许）
- 新会话使用新索引

## 5.5 依赖技能加载
若 `related_skills` 被标记为“强依赖”：
- 主技能可加载前先验证依赖存在
- 缺依赖时降级或拒绝加载（按策略）

默认建议 `related_skills` 仅用于推荐，不做强依赖，避免脆弱耦合。

## 5.6 失败与降级
加载链路失败时：
- 维持上一个可用索引
- Resolver 降级为关键词规则匹配
- 记录告警并附带错误摘要

---

## 6. Skill Resolver 实现细节

## 6.1 检索流程
1. 意图分类（配置/排障/编码/文档/运营等）
2. 候选召回（关键词 + 语义检索混合）
3. 规则重排（上下文、风险、历史成功率）
4. Top-k 选择（建议 k=1~3）

## 6.2 排序信号（建议）
- query 与 skill description 的语义相似度
- 触发标签匹配度（hard/soft）
- 当前会话上下文匹配（项目类型、任务阶段）
- 历史效果分（成功率、用户纠正率）
- 冲突惩罚分（与已选 skill 约束冲突）

## 6.3 冲突消解
优先级建议：
1. 安全策略相关 skill
2. 任务领域强相关 skill
3. 通用流程 skill

处理策略：
- 保留胜出 skill
- 对被抑制 skill 记录 `rejected_reason`
- 不把冲突 skill 同时注入执行层

---

## 6. Skill Compiler：从“文本”到“可执行约束”

Skill Compiler 需要产出两类内容：

1. **Planning Injection**（给 Query Engine 的规划提示）
   - 推荐阶段顺序（如 discover -> validate -> apply -> verify）
   - 推荐工具类型（非具体 transport）
   - 明确禁止动作（如未验证前禁止写入）

2. **Runtime Guards**（给 Executor/Permission 的约束）
   - 前置条件（必须先执行某类检查）
   - 参数约束（路径、URL、目标资源范围）
   - 风险门槛（高风险动作需 ask）

> 关键：Guard 是机器可判定规则，不应仅停留在自然语言。

---

## 7. 与 Query Engine 的协同

## 7.1 状态机扩展
在现有工具循环前加入 skill 决策阶段：

`INTENT -> SKILL_RESOLVE -> PLAN -> EXECUTE_TOOLS -> VERIFY -> FINAL`

## 7.2 Query Engine 侧必备能力
- 能接收 SkillDecision
- 能在 plan 步骤标记 `derived_from_skill`
- 能在运行中执行阶段转移（phase transition）
- 工具失败时根据 skill workflow 决定下一步（重试/替代/回滚）

## 7.3 失败回退
- Skill 不匹配或置信度低：降级为基础 planner
- Skill 约束过严导致阻塞：触发 “guard override with reason” 流程（需审计）

---

## 8. 与 Tool System / MCP 的协同

1. Skill 只描述“推荐工具能力类型”，不绑定具体工具实例。
2. Tool Registry 根据当前可用工具（native/mcp）做能力映射。
3. 若某 skill 推荐能力不可用：
   - 优先替代能力
   - 无替代则回退并记录能力缺口

### 能力映射示例（概念）
- `capability: read_docs` -> `web_fetch` 或 `mcp_docs_search`
- `capability: edit_config` -> `file_edit` 或 `mcp_fs_write`

---

## 9. 与 Permission System 的协同

## 9.1 Skill 派生策略
Skill 可生成临时策略（仅当前会话/当前任务生效）：
- `must_confirm_actions`
- `blocked_patterns`
- `required_prechecks`

## 9.2 执行顺序
`Skill Guard Check` 必须在 `Provider Call` 前执行。

## 9.3 授权边界
- ask 授权要绑定动作范围（工具 + 参数模式）
- 禁止宽泛升级（例如“本会话全部放行”）除非显式管理员策略

---

## 10. 与 Session Store / Compact 的协同

## 10.1 必存元数据
- `applied_skills`: [name@version]
- `skill_decision_reason`
- `active_phase`
- `guards_applied`

## 10.2 compact 保留策略
压缩时至少保留：
- 已选 skills 与版本
- 关键约束摘要
- 当前 phase
- 关键失败经验（避免重复错误）

## 10.3 resume 恢复
恢复会话时先恢复 SkillRuntimeState，再进入 Query Engine 继续执行。

---

## 11. 可观测性与审计

## 11.1 指标
- skill 命中率、选择率、放弃率
- 按 skill 的任务成功率与平均耗时
- skill 导致的权限拒绝率
- skill 应用后的重试率/回滚率
- 用户纠正率（skill 质量核心信号）

## 11.2 事件日志
- `skill.resolve.start/complete`
- `skill.selected`
- `skill.rejected`
- `skill.guard.applied`
- `skill.guard.blocked`
- `skill.phase.transition`

## 11.3 审计要求
任何 guard override 都必须记录：
- 谁触发（user/system）
- 覆盖了哪条约束
- 原因与上下文
- 时间戳与会话标识

---

## 12. 版本治理与发布策略

## 12.1 版本策略
- `major`: 约束语义改变或不兼容流程
- `minor`: 新增步骤/扩展覆盖
- `patch`: 描述修复、坑位补充

## 12.2 会话版本锁
- 会话启动时确定 `skill@version`
- 会话中不自动切换到新版
- 新版在新会话灰度

## 12.3 灰度发布
- 小流量试运行
- 监控纠正率与失败率
- 达标后全量

---

## 13. 测试与验收矩阵

## 13.1 功能正确性
- 技能可被正确检索与选择
- 冲突技能可稳定消解
- 技能约束可转成 runtime guards

## 13.2 协同正确性
- QE 能消费 skill phase 并按流程执行
- Permission 能执行 skill guard
- Tool/MCP 可按能力映射替换

## 13.3 可恢复性
- compact 后 skill 状态不丢失
- resume 后 phase 与 guard 正确恢复

## 13.4 稳定性
- 高并发下 resolver 延迟可控
- skill 索引损坏有降级路径
- provider 不可用时可平稳回退

---

## 14. 分阶段实施路线（建议）

### Phase 1：契约与索引
- 冻结 Skill Manifest 与 RuntimeState 模型
- 建立 Registry + 索引（关键词优先）

### Phase 2：Resolver 与编译器
- 实现召回/排序/冲突消解
- 实现 Skill Compiler（planning + guards）

### Phase 3：QE/Permission 接入
- QE 引入 SKILL_RESOLVE 阶段
- Permission 执行 skill guards

### Phase 4：Session/Compact 打通
- 写入 skill 元数据与 phase
- compact 保留关键 skill 状态

### Phase 5：观测与治理
- 指标 + 日志 + 审计闭环
- 版本锁与灰度发布

---

## 15. 常见反模式

1. 把 Skill 当长 prompt 拼接，未做 runtime 约束化
2. 同时注入过多技能导致规划失焦
3. 未记录选择理由，后续无法调试
4. 不做版本锁，会话中行为漂移
5. compact 丢失 skill phase，resume 后流程错位
6. 忽视冲突消解，多个技能互相打架

---

## 16. 上线前 P0/P1 清单

## P0（必须）
- [ ] Skill schema 冻结并有校验器
- [ ] Resolver 有 deterministic 行为
- [ ] Skill guards 在 Provider 调用前执行
- [ ] 会话可记录 applied_skills 与 phase
- [ ] compact 后可恢复关键 skill 状态
- [ ] 审计日志覆盖 selected/rejected/override

## P1（强烈建议）
- [ ] 混合召回（关键词 + 语义）
- [ ] 版本锁 + 灰度发布机制
- [ ] skill 质量指标看板
- [ ] 失败回退与能力缺口上报

---

## 17. 给 AI 实现者的“Skill 是什么”定义（必须内置到系统提示）

为了让你的 AI 不再“把 skill 当普通文本”，建议在系统层给出明确运行时定义：

> Skill 是一份带版本的过程知识单元，包含触发条件、执行流程、风险约束和验收规则。Skill 由 Resolver 选择、由 Compiler 编译为 Planning Injection + Runtime Guards，最终由 Query Engine 与 Permission/Executor 协同执行。

AI 必须遵守：
1. 未经 Resolver 选中，不得假设某 skill 已生效。
2. 选中 skill 后，必须在计划中体现其 phase（discover/validate/apply/verify）。
3. skill 的硬约束必须转换为 guard，不能只写在自然语言里。
4. 每次回答要带上 `applied_skills` 与 `reason`（内部元数据即可，不一定展示给最终用户）。

---

## 18. 端到端加载与组合流程（AI 可直接照此实现）

## 18.1 启动时（Boot Phase）
1. `SkillRegistry.scan_sources()`：扫描 repo/user/plugin/session 四类来源。
2. `SkillParser.parse(file)`：解析 frontmatter + body section。
3. `SkillValidator.validate(manifest, body)`：格式/字段/长度校验。
4. `SkillIndexer.build()`：构建关键词索引 + 可选语义索引。
5. `SkillCache.swap_atomically(new_index)`：原子替换索引。

输出：`SkillCatalogSnapshot(version, loaded_skills, invalid_skills, checksum)`

## 18.2 每轮请求时（Request Phase）
1. `IntentRouter.classify(query, context)`
2. `SkillResolver.retrieve(intent, query, catalog)`
3. `SkillResolver.rank_and_select(top_k<=3)`
4. `SkillCompiler.compile(selected_skills)`
5. `QueryEngine.plan(compiled_plan_hints)`
6. `Executor.run(..., compiled_runtime_guards)`
7. `SessionStore.append(skill_decision/phase_transition/tool_events)`

输出：`TurnArtifact{applied_skills, guards, plan, tool_calls, final_answer}`

## 18.3 热更新时（Refresh Phase）
1. 检测文件变化（watcher/cron/manual）
2. 增量重建新索引
3. 校验通过后原子替换
4. 进行中会话继续使用旧 snapshot（或按策略切换）

---

## 19. 模块接口契约（建议直接做成代码接口）

## 19.1 SkillRegistry
- 输入：source paths
- 输出：`SkillCatalogSnapshot`
- 行为：list/get/by_name/by_tag/by_source

## 19.2 SkillResolver
- 输入：`query`, `intent`, `session_context`, `catalog_snapshot`
- 输出：`SkillDecision`
- 保证：deterministic（同输入同输出）

## 19.3 SkillCompiler
- 输入：`SkillDecision.selected`, `session_context`
- 输出：
  - `planning_injection`
  - `runtime_guards`
  - `phase_model`

## 19.4 QueryEngine 协作点
- `before_plan`: 接收 `planning_injection`
- `before_tool_call`: 检查 `runtime_guards`
- `after_tool_result`: 触发 `phase_transition`
- `before_finalize`: 跑 `verification_checklist`

## 19.5 PermissionSystem 协作点
- 接收 `runtime_guards`
- 返回 `allow/ask/deny` + `reason`
- 支持 guard override（必须审计）

## 19.6 SessionStore 协作点
必须记录：
- `applied_skills`（name@version）
- `skill_decision_reason`
- `active_phase`
- `guard_decisions`
- `verification_result`

---

## 20. 组合策略：Skill 如何与其他模块一起工作

## 20.1 与 Query Engine 组合
- Skill 决定“怎么做”（流程）
- Query Engine 决定“这轮先做哪一步”（调度）
- 二者通过 phase 机协同，禁止各自绕过

## 20.2 与 Tool System / MCP 组合
- Skill 描述 capability，不绑定具体工具名
- Tool Mapper 将 capability 映射到当前可用工具（native 或 MCP）
- 工具不可用时，走替代映射或降级

## 20.3 与 Permission 组合
- Skill 提供高风险动作提示
- Permission 执行最终门禁
- 所有 deny/ask 必须回传给 QE 作为下一步决策依据

## 20.4 与 Compact 组合
- compact 时保留 `applied_skills + active_phase + hard_guards`
- resume 先恢复 skill runtime state，再继续 tool loop

## 20.5 与 Observability 组合
- 指标维度按 skill 聚合（成功率/耗时/纠正率）
- 可以定位“是哪个 skill 导致失败率上升”

---

## 21. 最小可运行实现（MVP）清单：让 AI 真正“知道怎么做”

### 21.1 必做文件/组件
1. `skill_schema`（manifest 与校验规则）
2. `skill_loader`（扫描、解析、校验、索引、缓存）
3. `skill_resolver`（召回 + 排序 + 冲突消解）
4. `skill_compiler`（planning_injection + runtime_guards）
5. `qe_integration`（SKILL_RESOLVE 阶段 + phase 机）
6. `permission_bridge`（guard 执行）
7. `session_bridge`（state 持久化与恢复）

### 21.2 MVP 执行序列
- 启动加载 skills
- 收到请求后选择 1~2 个 skill
- 编译出 phase 与 guards
- QE 按 phase 执行工具循环
- Permission 在每次 tool call 前判断
- 结果写回 session
- 最终输出并记录 skill 效果指标

### 21.3 MVP 验收标准
- AI 能解释“为什么选这个 skill”
- AI 能执行 skill workflow，而非只复述文档
- guard 能阻止违规动作
- compact/resume 后 skill 状态不丢
- 技能更新不会破坏进行中会话

---

## 22. 结论

在 ClaudeCode-like 架构中，Skills 的价值不在“提示词复用”，而在于把领域流程知识转成 **可执行、可治理、可恢复** 的运行时能力。

如果你已经有 Query Engine / Tool / Permission，下一步重点就是：
1. 固化 Skill 契约与 Loader/Resolver/Compiler 链路
2. 将 Skill 约束下沉到 Runtime Guards
3. 打通 Session/Compact 的状态保真
4. 建立版本、灰度与观测治理

完成这四步，Skills 才会从“经验文本”升级为“稳定生产能力”。
