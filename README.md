# WebApp Builder Agent

根据结构化需求与参考图片生成 React + Express + SQLite 网站的 Agent，基于 [Requirement Compilation Structure](https://github.com/code-philia/requirement-compilation-structure)。使用 ARC-Bench 评测，BookStack 是其中一个任务。

当前输入为包含 `requirements.yaml` 和引用图片的目录；自然语言需求入口尚未实现。

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

编译报告保存在生成目录的 `.arc/compilation.json`。当前 CLI 在部分阶段失败时仍可能返回退出码 0，应同时检查报告中的阶段状态。

## 代码结构

| 路径 | 内容 |
|---|---|
| `main.py`、`00_*.py`–`12_*.py` | 完整编译入口及 13 个阶段入口 |
| `infrastructure/compiler.py` | 编译流程调度 |
| `infrastructure/stages/` | 需求、数据库、后端、前端处理 |
| `infrastructure/shared/` | 模型、检索、编辑循环、项目模板 |
| `tests/` | 编译器及工具测试 |
| `team-tools/package-baseline.py` | B0 / B3 干净打包工具 |

## 提交与协作

- [ARC-Bench 打包与提交](docs/submission.md)
- [贡献指南](CONTRIBUTING.md)
- [B3 成组流程实现与成本控制](docs/b3-flow-batches.md)

参考实现固定版本：`d3da23e9897db84cfd37ce04a4ab5b38424ef399`。本分支为基于 B0 编译器的 B3 候选：保留独立最终验收，成组实现相关前后端流程，并加入精确去重、权限一致的工具提示及有限修复。实际综合分与费用收益需平台评测验证。
