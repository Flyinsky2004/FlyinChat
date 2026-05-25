# Claude-like Tool System: 设计与最小实现

## 交付内容
- `tool_system_design.md`：完整系统设计（协议、标准、权限、生命周期）
- `src/tool_core.py`：统一 Tool 协议、注册中心、权限与执行器
- `src/file_tools.py`：基础文件工具（FileReadTool / FileWriteTool）
- `src/demo.py`：最小运行示例

## 快速运行
```bash
cd /root/.hermes/artifacts/claude_like_tool_system/src
python3 demo.py
```

## 目标
为“自研 Claude Code 类 Agent”提供：
1) 一套统一 tools 定义标准
2) 可扩展的工具注册与过滤机制
3) 基础系统文件读写工具实现（带路径沙箱与安全约束）
