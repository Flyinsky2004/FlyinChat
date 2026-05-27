# 04｜File 工具 MVP（可直接编码）

## 1. FileReadTool
文件：`src/tools/file_read.py`
```python
class FileReadTool:
    meta = ToolMeta('file_read','Read text file','0.1.0','low')
    def input_schema(self): ...
    def run(self, args, ctx):
        # validate path/offset/limit
        # guard read root
        # read utf-8
        # return line-numbered text
```

Schema:
- path: string (required)
- offset: integer >=1 (default 1)
- limit: integer [1,2000] (default 200)

## 2. FileWriteTool
文件：`src/tools/file_write.py`

Schema:
- path: string (required)
- content: string (required)
- create_dirs: bool (default true)
- overwrite: bool (default true)

实现要求：
- realpath + write root 校验
- 原子写入（tempfile + replace）
- meta 返回 `bytes_written`

## 3. Path Guard
文件：`src/security/path_guard.py`
```python
def ensure_in_roots(path: str, roots: list[str]) -> str:
    # returns resolved path or raise PermissionError
```

## 4. 集成用例
`tests/integration/test_file_mvp.py`
- test_write_then_read_ok
- test_read_outside_workspace_denied
- test_write_outside_workspace_denied

命令：
- `pytest tests/integration/test_file_mvp.py -q`
