# 08｜测试矩阵、验收门槛、发布回滚

## 1. 测试矩阵

### 单元测试
- tool schema 校验
- permission 决策
- path guard 边界
- error code 映射

### 集成测试
- M1: file read/write
- M2: search/edit/shell
- M3: compact + boundary restore
- M4: mcp/lsp/git tool path

## 2. 建议命令
```bash
pytest tests/unit -q
pytest tests/integration/test_file_mvp.py -q
pytest tests/integration/test_edit_loop.py -q
pytest tests/integration/test_compact_pipeline.py -q
```

## 3. 上线门槛（Go/No-Go）
- 工具成功率 >= 99%
- PERMISSION false-allow = 0
- compact 后任务成功率下降 < 2%
- P95 tool latency 在预算内（自定义）

## 4. 灰度策略
- stage0: 本地 flag
- stage1: 内部 10%
- stage2: 50%
- stage3: 全量

## 5. 回滚策略
- feature flag 一键关新工具组
- compact engine 可降级到仅 budget 裁剪
- 兼容旧会话 schema（至少 1 个版本）

## 6. 发布检查单
- [ ] 审批链路覆盖高危工具
- [ ] 审计日志可检索（session/turn/tool）
- [ ] 异常可观测（error_code 聚合）
- [ ] 回滚演练通过
