# 07｜MCP 与 LSP 工具（内容细化版）

说明：以下内容按文章正文提炼，面向两类读者：你本人 + 实现代码的 AI。
每个工具都包含：要点、设计细节、实现要求、常见误区。

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
