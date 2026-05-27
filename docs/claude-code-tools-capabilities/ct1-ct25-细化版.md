# ct1-ct25 全工具细化（正文还原版）

本文件不放外链，只保留从文章提炼的可实现信息。

### ct1｜AgentTool：子 Agent 调度器
工具要点：
- 这个工具到底解决什么问题
- 先看它的输入长什么样
- 它在工具池里的位置非常特殊
设计细节（文章信息还原）：
- 一张图看它在系统里的位置
- 它不是“再开一个模型”这么简单
- 子 Agent 为什么不会变成“失控副本”
- 误解一：AgentTool 就是多轮聊天
- 误解二：子 Agent 和主线程完全一样
- 很多 AI 工具只有一个主线程模型一直往下跑，而 Claude Code 明确支持： 研究型子任务 后台执行 多 Agent 协作 本地 / 远程子 Agent 先看它的输入长什么样 tools/AgentTool/AgentTool.tsx 一上来就把核心参数暴露出来了： const baseInputSchema = z.
关键动作/字段（页面高频信息）：
- 研究型子任务
- 后台执行
- 多 Agent 协作
- 本地 / 远程子 Agent
- description：给子任务一个简短标题
- prompt：真正交给子 Agent 的工作内容
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 与任务系统联动时，要处理运行中/已停止/超时等状态。
常见误区（文章强调）：
- 误解一：AgentTool 就是多轮聊天
- 误解二：子 Agent 和主线程完全一样
- 误解三：AgentTool 只是“更高级的 prompt”

### ct2｜BashTool：Shell 执行器
工具要点：
- 这个工具为什么是核心中的核心
- 先看它依赖了多少子模块
- 它不是“万能入口”，而是受约束的执行器
设计细节（文章信息还原）：
- 它会主动理解命令类型
- 一张图看 BashTool 的执行链
- 安全检查不是装饰，而是主干逻辑
- 误解一：BashTool 就是越多用越强
- 误解二：BashTool 只是执行层，不涉及产品逻辑
- 配合 bashPermissions.ts 、 destructiveCommandWarning.ts 、 readOnlyValidation.ts 这些模块，Claude Code 其实在做一件事： 尽量把 Shell 执行变成一种可被审计和约束的行为 这也是为什么 Claude Code 在工程上比“AI 帮你跑终端”那种粗糙做法强很多。
关键动作/字段（页面高频信息）：
- 跑测试
- 跑构建
- 看 Git 状态
- 调用编译器、包管理器、脚本
- 启动开发服务
- 执行系统命令
实现要求（给代码实现 AI 的硬约束）：
- 执行前需经过权限或沙箱判断，高风险动作不可默认放行。
- 优先将 Bash 用于验证和环境动作，不替代专用文件工具。
常见误区（文章强调）：
- 误解一：BashTool 就是越多用越强
- 误解二：BashTool 只是执行层，不涉及产品逻辑
- 误解三：BashTool 的价值只是“能跑命令”

### ct3｜FileReadTool：读取文件
工具要点：
- 它为什么比 cat 更重要
- 先看它的 prompt 怎么定义自己
- 它不只读文本，还读多模态内容
设计细节（文章信息还原）：
- 一张图看读取链路
- 它为什么会影响后续写入
- 默认读 2000 行这件事很有意思
- 误解一：Read 只是为了方便展示
- 误解二：既然有 Bash，就没必要有 Read
- 先看它的 prompt 怎么定义自己 tools/FileReadTool/prompt.ts ： export const DESCRIPTION = 'Read a file from the local filesystem.' return `Reads a file from the local filesystem.
关键动作/字段（页面高频信息）：
- 给模型稳定读取项目文件的入口
- 让读取结果结构化、可追踪
- 为后续编辑建立“已读状态”
- 路径必须可确定
- 长文件默认有上限
- 文件和目录分开处理
实现要求（给代码实现 AI 的硬约束）：
- 涉及文件时优先绝对路径，并在调用前确认目标路径有效。
常见误区（文章强调）：
- 误解一：Read 只是为了方便展示
- 误解二：既然有 Bash，就没必要有 Read
- 误解三：Read 只适合源码文件

### ct4｜FileEditTool：编辑文件
工具要点：
- 这个工具解决的不是“能改文件”，而是“怎么安全地改”
- 看源码，它的依赖明显比想象中重
- 先看工具本体定义
设计细节（文章信息还原）：
- 一张图看编辑链路
- 它最关键的一点：要求先读文件
- 它不是直接覆盖，而是 patch 驱动
- 误解一：Edit 和 Bash sed 没本质区别
- 误解二：Edit 是文本工具，不涉及工程状态
关键动作/字段（页面高频信息）：
- 先确认文件读过
- 再确认文件没被别人改过
- 再确认当前编辑权限允许
- 最后才生成 patch 并写回
- diff
- Git 视角
实现要求（给代码实现 AI 的硬约束）：
- 执行前需经过权限或沙箱判断，高风险动作不可默认放行。
- 编辑前先读取最新内容，避免基于过期上下文写回。
常见误区（文章强调）：
- 误解一：Edit 和 Bash sed 没本质区别
- 误解二：Edit 是文本工具，不涉及工程状态
- 误解三：Edit 只是“更安全的替换”

### ct5｜FileWriteTool：写入文件
工具要点：
- 它解决的是“整文件写入”问题
- 源码里最关键的输入定义
- 它的输出比你想的更丰富
设计细节（文章信息还原）：
- 一张图看写入链路
- 它也会检查文件是否过期
- 它为什么还要接入 diff 和 Git
- 误解一：Write 只是“更方便的 echo > file”
- 误解二：Write 比 Edit 更强，所以更应该优先用
- 源码里最关键的输入定义 tools/FileWriteTool/FileWriteTool.ts ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- 新建一个文件
- 用一整块新内容覆盖一个现有文件
- 写到哪里
- 写什么内容
- 这是创建还是更新
- 原文件是什么
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 涉及文件时优先绝对路径，并在调用前确认目标路径有效。
- 整文件写入后要保留变更视图，便于审计与回滚。
常见误区（文章强调）：
- 误解一：Write 只是“更方便的 echo > file”
- 误解二：Write 比 Edit 更强，所以更应该优先用
- 误解三：Write 只适合新文件

### ct6｜GlobTool：查找文件
工具要点：
- 这个工具看起来简单，但位置非常关键
- 先看它的输入定义
- 它是读操作，而且是并发安全的
设计细节（文章信息还原）：
- 一张图看它在搜索链里的位置
- 它不是简单的 find
- 它会校验 path 不是乱填的
- 误解一：有 Bash 的 find，Glob 就没必要
- 误解二：Glob 只是 UI 更好看
- 先看它的输入定义 tools/GlobTool/GlobTool.ts ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- pattern：用来表达“想找什么”
- path：用来限制搜索范围
- 只读
- 可并行
- 明确属于“搜索”类工具
- 搜索结果结构化
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 该工具定位为只读能力，不应承担写入副作用。
- 支持并发，但仍要控制输出规模与调用频次。
- 先缩小检索范围再深读，避免上下文噪声。
常见误区（文章强调）：
- 误解一：有 Bash 的 find，Glob 就没必要
- 误解二：Glob 只是 UI 更好看
- 误解三：它只是小工具，不重要

### ct7｜GrepTool：搜索内容
工具要点：
- 它是 Claude Code 最常用的“找线索”工具之一
- 看它的 schema，就知道它不是简单字符串搜索
- 它的底层就是 ripgrep，但不是裸暴露
设计细节（文章信息还原）：
- 一张图看它的常见链路
- 它在设计上很重视“结果控量”
- 它不只是“返回命中内容”，还区分三种模式
- 误解一：直接 Bash 跑 rg 就够了
- 误解二：Grep 只是“搜字符串”
- 看它的 schema，就知道它不是简单字符串搜索 tools/GrepTool/GrepTool.ts ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- 先 Grep
- 再 Read
- 再判断要不要 Edit
- 搜文件名过滤
- 搜文件类型过滤
- 只看命中文件
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 该工具定位为只读能力，不应承担写入副作用。
- 支持并发，但仍要控制输出规模与调用频次。
- 先缩小检索范围再深读，避免上下文噪声。
常见误区（文章强调）：
- 它和 GlobTool 的边界
- 误解一：直接 Bash 跑 rg 就够了
- 误解二：Grep 只是“搜字符串”

### ct8｜NotebookEditTool：编辑 Notebook
工具要点：
- 它为什么不是普通版 FileEditTool
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 实现重点
- 一次典型使用路径
- 它和相邻工具的关系
- 误解一：Notebook 反正是 JSON，直接 Edit 就行
- 误解二：它只是换了个文件扩展名
- 关键源码 tools/NotebookEditTool/NotebookEditTool.ts ： export const inputSchema = z.
关键动作/字段（页面高频信息）：
- 一组有顺序的 cell
- 混合了 code / markdown
- 带输出、元数据、语言信息
- 结构被破坏，文件打不开
- 只想改一个 cell，却误伤整个 notebook
- 强制要求目标文件是 .ipynb
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 编辑前先读取最新内容，避免基于过期上下文写回。
常见误区（文章强调）：
- 最容易误解它的地方
- 误解一：Notebook 反正是 JSON，直接 Edit 就行
- 误解二：它只是换了个文件扩展名

### ct9｜WebFetchTool：抓取网页
工具要点：
- 这个工具到底做什么
- 它的输入为什么只有两个字段
- 一张图看它的完整链路
设计细节（文章信息还原）：
- 它不是直接把网页全文塞回主模型
- 这也是它和浏览器工具最大的不同
- 权限系统不是按“整个互联网”放行，而是按域名做
- 中文理解
- 误解一：它就是一个 HTTP GET
- Tools 工具组 0 0 WebFetchTool：抓取网页 这个工具到底做什么 WebFetchTool 负责抓取一个 已经知道 URL 的网页 ，把网页内容转成 Claude Code 更容易处理的文本，再根据传入的 prompt 提炼结果。
关键动作/字段（页面高频信息）：
- WebSearchTool：帮模型去网上找结果
- WebFetchTool：拿着确定的 URL 去读具体页面
- 先把网页内容抓回来
- 再根据 prompt 提炼想要的信息
- 抓网页
- 转成 markdown
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 执行前需经过权限或沙箱判断，高风险动作不可默认放行。
常见误区（文章强调）：
- 误解一：它就是一个 HTTP GET
- 误解二：它能代替浏览器
- 误解三：它和 WebSearchTool 差不多

### ct10｜WebSearchTool：联网搜索
工具要点：
- 这个工具到底做什么
- 它的 schema 很简单，但能力很强
- 它不是 Bash 调搜索引擎，而是接 Anthropic 的 Web Search 能力
设计细节（文章信息还原）：
- 一张图看搜索链路
- 它的核心调用方式很值得研究
- 它为什么不是直接把结果返回，而是要先解析内容块
- 误解一：WebSearchTool 就是搜索引擎 API 包装
- 误解二：有了 WebSearchTool 就不需要 WebFetchTool
- 它的 schema 很简单，但能力很强 tools/WebSearchTool/WebSearchTool.ts ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- WebSearchTool：找信息源
- WebFetchTool：读指定页面
- 搜什么
- 只搜哪些域名
- 排除哪些域名
- 它自己重新发起了一次模型调用
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
常见误区（文章强调）：
- 误解一：WebSearchTool 就是搜索引擎 API 包装
- 误解二：有了 WebSearchTool 就不需要 WebFetchTool
- 误解三：它总能搜到最新内容

### ct11｜TodoWriteTool：待办清单
工具要点：
- 它不是普通 checklist，而是会话内任务外显
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 实现重点
- 一次典型使用路径
- 它和相邻工具的关系
- 你可以把它理解成： TodoWriteTool ：轻量、会话内、快速追踪 TaskCreateTool 系列：结构化、正式任务系统 关键源码 tools/TodoWriteTool/TodoWriteTool.ts ： const inputSchema = z.
- strictObject ({ todos : TodoListSchema ().
关键动作/字段（页面高频信息）：
- TodoWriteTool：轻量、会话内、快速追踪
- TaskCreateTool 系列：结构化、正式任务系统
- 所有 todo 都完成时，会直接把列表清空
- 如果结束的是一个 3 项以上的复杂任务，而且没有验证步骤，会提醒生成 verification nudge
- 用户给一个中等复杂任务
- 模型先写 3-5 个 todo
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 整文件写入后要保留变更视图，便于审计与回滚。

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

### ct14｜EnterPlanModeTool：进入 Plan Mode
工具要点：
- 它的本质是状态切换，不是提示词切换
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 为什么它不能在 agent context 里随便用
- 它和 AskUserQuestionTool 的关系
- 小结
- Tools 工具组 0 0 EnterPlanModeTool：进入 Plan Mode 它的本质是状态切换，不是提示词切换 EnterPlanModeTool 的作用不是“让模型多想一会儿”，而是把当前会话切到一种新的运行状态： plan 。
- setAppState ( prev => ({ ...prev, toolPermissionContext : applyPermissionUpdate ( prepareContextForPlanMode (prev.
关键动作/字段（页面高频信息）：
- 权限模式
- 会话目标
- 用户交互预期
实现要求（给代码实现 AI 的硬约束）：
- 执行前需经过权限或沙箱判断，高风险动作不可默认放行。

### ct15｜ExitPlanModeTool：退出 Plan Mode
工具要点：
- 它不是“结束规划”，而是“提交规划”
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 它和 AskUserQuestionTool 的边界
- 它为什么重要
- 小结
- Tools 工具组 0 0 ExitPlanModeTool：退出 Plan Mode 它不是“结束规划”，而是“提交规划” ExitPlanModeTool 的名字容易让人误会。
- 所以它代表的是 Plan Mode 的 交付节点 ，不是随便离开规划态。
关键动作/字段（页面高频信息）：
- 先写 plan file
- 再调用这个工具
- 让用户审批
- 不确定需求：AskUserQuestionTool
- 计划写完求批准：ExitPlanModeTool
- 写一堆计划
实现要求（给代码实现 AI 的硬约束）：
- 遵循“先发现/读取，再执行修改”的顺序，确保动作可解释。
常见误区（文章强调）：
- 它和 AskUserQuestionTool 的边界

### ct16｜TaskCreateTool：创建任务
工具要点：
- 它把待办项升级成正式任务对象
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- Tools 工具组 0 0 TaskCreateTool：创建任务 它把待办项升级成正式任务对象 TaskCreateTool 不是简单往列表里插一行文本，而是把一个工作项创建成正式任务对象： 有 id 有 subject 有 description 有状态 可被后续更新、阻塞、归属 这说明 Claude Code 的任务系统已经不是展示层小功能，而是真正的运行时对象系统。
- 小结 TaskCreateTool 代表的是 Claude Code 从“todo 文本”到“正式任务对象”的那一步。
关键动作/字段（页面高频信息）：
- 有 id
- 有 subject
- 有 description
- 有状态
- 可被后续更新、阻塞、归属
实现要求（给代码实现 AI 的硬约束）：
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct17｜TaskGetTool：读取任务
工具要点：
- 它是任务系统里的单点查询入口
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- Tools 工具组 0 0 TaskGetTool：读取任务 它是任务系统里的单点查询入口 TaskGetTool 的职责很纯粹：按 ID 读取单个任务。
- 关键源码 const task = await getTask (taskListId, taskId) 返回内容除了标题和状态，还包括： description blocks blockedBy 这说明它查询的不是“列表项”，而是带依赖关系的任务对象。
关键动作/字段（页面高频信息）：
- description
- blocks
- blockedBy
实现要求（给代码实现 AI 的硬约束）：
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct18｜TaskUpdateTool：更新任务
工具要点：
- 它是任务系统的主写入口
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- Tools 工具组 0 0 TaskUpdateTool：更新任务 它是任务系统的主写入口 TaskUpdateTool 负责修改任务对象本身。
- 如果说 TaskCreateTool 是创建节点，那 TaskUpdateTool 就是任务流真正推进的主干工具。
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct19｜TaskListTool：列出任务
工具要点：
- 它给主线程提供全局任务视图
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- Tools 工具组 0 0 TaskListTool：列出任务 它给主线程提供全局任务视图 TaskListTool 的作用是让模型重新看到“现在有哪些任务、谁卡住了谁、哪些还没完成”。
- 关键源码 const allTasks = ( await listTasks (taskListId)).
实现要求（给代码实现 AI 的硬约束）：
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct20｜TaskStopTool：停止任务
工具要点：
- 它负责中断后台执行，不是删除任务记录
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- Tools 工具组 0 0 TaskStopTool：停止任务 它负责中断后台执行，不是删除任务记录 TaskStopTool 的目标很明确： 停止一个正在运行的后台任务。
- 这通常对应两类来源： BashTool 启动的后台 shell AgentTool 启动的后台 agent 关键源码 const result = await stopTask (id, { getAppState, setAppState, }) 在此之前它会先校验： 任务存在 任务当前确实是 running 调用链 加载图表中...
关键动作/字段（页面高频信息）：
- BashTool 启动的后台 shell
- AgentTool 启动的后台 agent
- 任务存在
- 任务当前确实是 running
实现要求（给代码实现 AI 的硬约束）：
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct21｜TaskOutputTool：读取任务输出
工具要点：
- 它把后台任务输出统一成同一种可读结果
- 关键源码
- 它还有一个很有意思的现状
设计细节（文章信息还原）：
- 调用链
- 小结
- Tools 工具组 0 0 TaskOutputTool：读取任务输出 它把后台任务输出统一成同一种可读结果 TaskOutputTool 用来读取后台任务的输出。
- 关键源码 输入定义： const inputSchema = z.
关键动作/字段（页面高频信息）：
- shell 任务输出
- 本地 agent 输出
- 远程 agent 输出
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 与任务系统联动时，要处理运行中/已停止/超时等状态。

### ct22｜SendMessageTool：Agent 通信
工具要点：
- 它是多 Agent 模式下的通信总线
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 它支持的不只是 teammate 名称
- 小结
- 关键源码 tools/SendMessageTool/SendMessageTool.ts ： const inputSchema = z.
关键动作/字段（页面高频信息）：
- * 广播
- uds:<socket-path>
- bridge:<session-id>
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。

### ct23｜ListMcpResourcesTool：列出 MCP 资源
工具要点：
- 它让模型先获得“资源发现能力”
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 小结
- 关键源码 tools/ListMcpResourcesTool/ListMcpResourcesTool.ts ： const inputSchema = z.
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 先做资源发现，再做资源读取，处理外部服务不可用场景。

### ct24｜ReadMcpResourceTool：读取 MCP 资源
工具要点：
- 它是 MCP 世界里的远程 Read
- 关键源码
- 二进制资源也能处理
设计细节（文章信息还原）：
- 调用链
- 小结
- 关键源码 输入定义： export const inputSchema = z.
- request ( { method : 'resources/read' , params : { uri }, }, ReadResourceResultSchema , ) 二进制资源也能处理 源码里有一段很关键： if (!( 'blob' in c) || typeof c.
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 先做资源发现，再做资源读取，处理外部服务不可用场景。

### ct25｜LSPTool：语言服务接入
工具要点：
- 它让 Claude Code 获得 IDE 级代码智能
- 关键源码
- 调用链
设计细节（文章信息还原）：
- 它为什么比 GrepTool 高一级
- 它也有严格的输入和文件校验
- 一张图看它和其他搜索工具的关系
- 关键源码 tools/LSPTool/LSPTool.ts ： const inputSchema = z.
- strictObject ({ operation : z.
关键动作/字段（页面高频信息）：
- go to definition
- find references
- hover
- document symbol
- call hierarchy
- GrepTool：字符串匹配
实现要求（给代码实现 AI 的硬约束）：
- 输入必须按结构化参数传递，避免自由文本参数。
- 依赖语言服务状态，结果与索引、工作区配置一致性相关。
