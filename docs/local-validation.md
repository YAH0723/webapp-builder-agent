# 本地单步检查

先用平台导出的应用，或已有 Agent 生成的应用作为本地工作区。应用需包含
`.arc` 元数据、源码、测试和已安装的 Node 依赖；执行生成结果的代码前确认其来源。
以下检查不会创建模型客户端，不使用 API Key，不重新跑 13 个生成阶段。
浏览器测试使用真实本地服务和隔离测试数据库。构建会写入应用自己的产物目录。

将 `APPLICATION_DIR` 替换为生成应用的绝对路径，在 Agent 仓库执行：

```sh
# 列出预期后端测试，不运行 Node
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 08 --list

# 只检查一个 API 的 TypeScript
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 08 --id API_ID --checks typecheck

# 后端真实 HTTP 测试
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 08 --checks tests --report releases/local-backend.json

# 检查完整 UI 设计 / 确定性接口绑定
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 09
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 11

# 单页真实浏览器检查
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 10 --id PAGE_ID --checks typecheck tests

# 单条需求的独立端到端验收
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 12 --id REQUIREMENT_ID --checks typecheck tests

# 最终完整本地验收：分别执行所有后端、UI、E2E 目标
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 08
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 10
uv run python team-tools/check-stage.py --workspace APPLICATION_DIR --stage 12
```

`--id` 可重复。未提供时检查该阶段所有预期目标；缺少任意预期测试文件会失败，
不会仅扫描剩余文件并报告通过。结果标明 `selected_targets` 或 `all_stage_targets`，
逐项保留耗时和错误，失败返回退出码 1。仅运行类型检查或某条需求不代表全量通过。
`--list` 返回 `LISTED_NOT_TESTED`。没有目标不会伪报 GREEN。

修改 Agent 编排时，先运行不需要模型和 Node 的机制回归：

```sh
uv run python -m unittest discover -s tests -p test_b4_batching.py
uv run python -m unittest discover -s tests -p test_b3_flow_batches.py
```

这些测试覆盖批量漏项、共享 API 多需求方、权限、有限拆分、失败回滚和局部检查。
脚本模型可验证编排行为；真实本地 HTTP/浏览器回放可验证运行和故障修复。
两者不能预测真实模型生成质量、实际 API 费用或平台隐藏测试结果。
本地验证通过后，再对同一组改动做一次平台评测，固定任务版本、模型和推理配置。
