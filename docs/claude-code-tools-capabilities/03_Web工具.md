# 03｜Web 工具（内容细化版）

说明：以下内容按文章正文提炼，面向两类读者：你本人 + 实现代码的 AI。
每个工具都包含：要点、设计细节、实现要求、常见误区。

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
