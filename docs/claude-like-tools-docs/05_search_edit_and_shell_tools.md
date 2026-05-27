# 05｜Search/Edit/Shell（M2 实施版）

## 1. SearchFilesTool
文件：`src/tools/search_files.py`

接口：
- pattern: str
- target: 'content'|'files' (default content)
- file_glob: str|None
- limit: int<=200
- context: int<=5

建议实现：先用 ripgrep CLI 包装；无 rg 时降级 Python 扫描。

## 2. FilePatchTool
文件：`src/tools/file_patch.py`

最小能力：
- old_string/new_string 精准替换
- replace_all false 默认唯一命中
- 输出 unified diff 摘要

## 3. BashTool（高危）
文件：`src/tools/bash_tool.py`

参数：
- command: str
- timeout: int (default 180, max 600)
- background: bool (default false)

安全策略（必须）：
- deny 列表：`rm -rf /`, fork bomb, `:(){ :|:& };:` 等
- ask 列表：网络下载执行、系统级改动
- 输出上限 50KB，超限标记 `truncated=true`

## 4. 测试
- unit: command policy 命中
- integration: search->patch->bash(pytest)
命令：
- `pytest tests/unit/test_bash_policy.py -q`
- `pytest tests/integration/test_edit_loop.py -q`
