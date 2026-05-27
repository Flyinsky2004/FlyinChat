# 01｜总览与实施范围（可执行版）

## 1. 目标
在现有“File Read/Write”基础上，4 个里程碑渐进实现 Claude Code 风格工具系统，要求：
- 可持续长会话
- 可控高风险执行
- 可扩展外部能力（MCP/LSP）
- 每阶段可验收、可回滚

## 2. 代码目录（建议直接采用）
```
project/
  src/
    core/
      tool_types.py
      registry.py
      executor.py
      events.py
    security/
      permission.py
      path_guard.py
      policy.py
    tools/
      file_read.py
      file_write.py
      search_files.py
      file_patch.py
      bash_tool.py
    session/
      message_store.py
      compact_engine.py
      boundary_store.py
    integrations/
      mcp_client.py
      lsp_client.py
      git_tool.py
  tests/
    unit/
    integration/
  docs/claude-like-tools/
```

## 3. 里程碑与交付件
- M1（底座+文件工具）
  - core/security/tools(file)
  - 单元测试 + 集成测试（最小闭环）
- M2（search/edit/shell）
  - search/patch/bash + 安全审批
- M3（会话压缩）
  - message_store + compact_engine + boundary
- M4（集成与生产化）
  - MCP/LSP/Git + 灰度与回滚机制

## 4. 来源对齐（xuanyuancode）
- cc3：分层架构与启动装配
- cc5：QueryEngine 面向“会话状态”
- cc6：Tool 协议 + tools 注册表
- cc8b：多阶段 compact 管线
- cc10：权限多层防线
- cc11/cc14：MCP/LSP 扩展与 Bash 风险控制

## 5. 完成定义（DoD）
- 新工具接入不改 executor 主流程
- 任意高危操作具备审批与审计记录
- 长会话触发压缩后仍可继续任务
