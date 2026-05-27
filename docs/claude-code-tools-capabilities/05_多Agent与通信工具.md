# 05｜多 Agent 与通信工具（内容细化版）

说明：以下内容按文章正文提炼，面向两类读者：你本人 + 实现代码的 AI。
每个工具都包含：要点、设计细节、实现要求、常见误区。

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
