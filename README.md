# WebApp Builder Agent

根据结构化需求与参考图片生成 React + Express + SQLite 网站的 Agent，基于 [Requirement Compilation Structure](https://github.com/code-philia/requirement-compilation-structure)。使用 ARC-Bench 评测，BookStack 是其中一个任务。

当前输入为包含 `requirements.yaml` 和引用图片的目录；自然语言需求入口尚未实现。

本分支为 **B6 通用运行库与少轮完整应用生成实验**。默认联合规划、独立编写验收测试、联合生成前后端，并复用通用存储、请求、导航、表单、列表与确认弹窗。保留 `--pipeline classic` 运行此前 B5.1 的十三阶段流程。机制和限制见 [B6 说明](docs/b6-reusable-runtime.md)；实际费用和官方正确率尚未实测。

## 环境

- Python 3.11+、[uv](https://docs.astral.sh/uv/)
- Node.js 22.12+、npm、Git、Bash
- 支持代码中模型及图像输入的 OpenAI Chat Completions 兼容 API

在仓库根目录安装依赖：

```sh
uv sync --frozen
uv run playwright install chromium
```

将 `.env.example` 复制为本地 `.env`，配置 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `MODEL`。默认模型为 `deepseek-flash`；视觉模型可通过 `VISUAL_MODEL` 单独指定。不要提交 `.env` 或真实密钥。

## 运行

仓库的 `input/` 提供示例需求。完整评测任务需单独获取，并替换输入路径。

```sh
uv run python main.py input --output-dir outputs/demo
```

启动生成的网站：

```sh
cd outputs/demo
npm run db:init
npm run build
npm start
```

默认访问地址为 `http://localhost:3000`。通过 `main.py --help` 查看参数；`--model-log` 开启详细模型日志，`--port` 设置应用端口。

编译报告保存在生成目录的 `.arc/compilation.json`。B6 对无法构建或启动的失败返回非零退出码；内部验收失败但构建和启动通过时，保留失败状态与 `evaluation_ready` 证据，允许正式评测部分成果。classic 路线在部分阶段失败时仍可能返回退出码 0，不能仅看退出码判断验收是否通过。

## 代码结构

| 路径 | 内容 |
|---|---|
| `main.py`、`00_*.py`–`12_*.py` | 完整编译入口及 13 个阶段入口 |
| `infrastructure/compiler.py` | 编译流程调度 |
| `infrastructure/compact/` | B6 少轮完整应用生成、通用运行库与独立验收 |
| `infrastructure/stages/` | 需求、数据库、后端、前端处理 |
| `infrastructure/shared/` | 模型、检索、编辑循环、项目模板 |
| `tests/` | 编译器及工具测试 |
| `team-tools/package-baseline.py` | 当前 B6 干净打包工具；旧版本使用对应分支 |
| `team-tools/check-stage.py` | 不调用模型的本地单阶段检查 |
| `team-tools/check-compact.py` | 不调用模型的 B6 构建与浏览器验收复查 |

## 提交与协作

- [ARC-Bench 打包与提交](docs/submission.md)
- [贡献指南](CONTRIBUTING.md)
- [B3 成组流程实现与成本控制](docs/b3-flow-batches.md)
- [B4 批量生成与单套独立验收](docs/b4-batched-generation.md)
- [本地单步检查](docs/local-validation.md)
- [B4.1 本地回放与 UI 设计恢复](docs/b41-local-replay.md)
- [B4.2 通用接口接线生成](docs/b42-contract-codegen.md)
- [B4.3 环境恢复与全局停损](docs/b43-environment-guards.md)
- [B5 场景覆盖与连续用户流程](docs/b5-scenario-coverage.md)
- [B5.1 任务级推理与完整请求预算](docs/b51-model-budget.md)
- [B6 通用运行库与少轮完整应用生成](docs/b6-reusable-runtime.md)

参考实现固定版本：`d3da23e9897db84cfd37ce04a4ab5b38424ef399`。B6 继承环境保护及文本请求预算，默认使用新的 compact 流程；classic 保留 B5.1。实际正确率、综合分与费用收益需平台评测验证。
