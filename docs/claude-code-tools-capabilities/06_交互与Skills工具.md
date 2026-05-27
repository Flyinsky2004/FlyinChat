# 06｜交互与 Skills 工具（内容细化版）

说明：以下内容按文章正文提炼，面向两类读者：你本人 + 实现代码的 AI。
每个工具都包含：要点、设计细节、实现要求、常见误区。

### ct12｜AskUserQuestionTool：向用户提问
工具要点：
- 这个工具为什么比“直接问一句话”更高级
- 源码先看 schema
- 它甚至支持选项预览
设计细节（文章信息还原）：
- 一张图看它在执行流程里的位置
- 它和 Plan Mode 的关系尤其重要
- 它会严格约束问题结构
- 中文含义
- 误解一：这只是个 UI 小工具
- 这对于 Agent 产品特别重要，因为它关系到： 需求澄清 多选决策 方案比较 Plan Mode 中的信息补全 源码先看 schema tools/AskUserQuestionTool/AskUserQuestionTool.tsx ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- 需求澄清
- 多选决策
- 方案比较
- Plan Mode 中的信息补全
- 方案 A / 方案 B 对比
- UI 草图对比
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
常见误区（文章强调）：
- 一张图看它和相邻工具的边界
- 误解一：这只是个 UI 小工具
- 误解二：所有需要问用户的事都该用它

### ct13｜SkillTool：执行 Skills
工具要点：
- 它不是命令别名，而是技能运行时
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 它还兼容 MCP skills
- 一次典型使用路径
- 它和相邻工具的关系
- Tools 工具组 0 0 SkillTool：执行 Skills 它不是命令别名，而是技能运行时 很多人第一次看到 /commit 、 /verify 、 /update-config 这类 skill，会以为它们只是更长 prompt 的快捷方式。
- ): Promise < ToolResult < Output >> { ...
关键动作/字段（页面高频信息）：
- 找到 skill 对应的 command
- 解析参数
- 处理本地 skill 和 MCP skill
- 必要时 fork 一个子 Agent 去跑
- 用户输入 /commit
- SkillTool 找到这个 skill 的 command
实现要求（给代码实现 AI 的硬约束）：
- 遵循“先发现/读取，再执行修改”的顺序，确保动作可解释。
