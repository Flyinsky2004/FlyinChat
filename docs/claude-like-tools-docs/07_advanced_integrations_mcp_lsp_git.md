# 07｜MCP/LSP/Git（M4 实施版）

## 1. MCP Client
文件：`src/integrations/mcp_client.py`

最小接口：
```python
class McpClient:
    def list_tools(self) -> list[dict]: ...
    def list_resources(self) -> list[dict]: ...
    def read_resource(self, uri: str) -> dict: ...
    def call_tool(self, name: str, args: dict) -> dict: ...
```

## 2. LSP Client
文件：`src/integrations/lsp_client.py`

最小接口：
- get_diagnostics(file)
- goto_definition(file,line,col)
- find_references(file,line,col)

## 3. Git Tool
文件：`src/integrations/git_tool.py`

最小接口：
- status()
- diff(path=None)
- checkout(branch)
- commit(message)

## 4. 接入策略
- 先以 Tool 形式挂到 registry
- 统一走 executor + permission + audit
- MCP 动态刷新时只更新可见工具，不改主循环

## 5. 验收场景
“诊断报错 -> 定位定义 -> 修改 -> 跑测 -> 查看 diff -> 生成 commit 建议”
