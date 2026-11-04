# ARC-Bench 打包与提交

## B0 基础包

在仓库根目录运行：

```sh
uv run python team-tools/package-baseline.py
```

默认输出 `releases/webapp-builder-agent-B0.zip` 和同名 JSON 摘要。可用 `--output` 指定其他位置。

打包工具只收集 Git 管理的编译运行文件，并检查其与参考提交一致。ZIP 根目录包含 `main.py`、`requirements.txt`、阶段脚本、`infrastructure/`、README 和文件哈希清单，不包含本地环境文件、密钥、任务数据或日志。

默认 B0 要求编译器与固定参考版本一致；B1 使用 `--variant B1` 打包，并在清单中记录当前源码提交号。编译运行代码须先提交，避免包内容与提交号不一致。不要使用会携带 `.env` 的上游 `scripts/package.py` 提交本地配置。

B2 分支使用 `--variant B2`，生成 `releases/webapp-builder-agent-B2.zip`。B0/B1 应在各自冻结版本重新打包；B2 的 profile 与单项开关见 [工作流说明](acceptance-first.md)。

通用契约索引版本使用 `--variant B2.1`，生成 `releases/webapp-builder-agent-B2.1.zip`。已发布的 B2 同样保持冻结；B2.1 使用 B2 profile，并默认启用 `ARC_B2_CONTRACT_REGISTRY`，见 [契约说明](contracts.md)。

共享 API 协调版本使用 `--variant B2.2`，生成 `releases/webapp-builder-agent-B2.2.zip`。B2.1 保持冻结；B2.2 默认使用 B2 profile 并启用 `ARC_B2_API_COORDINATION`，见 [设计恢复说明](api-design-recovery.md)。

失败证据与通用骨架版本使用 `--variant B2.3`，生成 `releases/webapp-builder-agent-B2.3.zip`。B2.2 保持冻结；新增两层可分别关闭，见 [证据与骨架说明](evidence-runtime.md)。

## 平台运行协议

平台提供需求目录和应用输出目录，调用方式为：

```sh
python3 /workspace/submission/main.py REQUIREMENTS_DIR --output-dir /workspace/template
```

平台安装 Python 依赖，生成应用后通过 `deploy.sh` 构建并启动。运行环境还需要 Node.js、npm、Git 和 Bash。

## 模型配置

提交页面填写 Base URL 和 API Key；Agent 使用运行环境注入的 `OPENAI_BASE_URL`、`OPENAI_API_KEY`，包括平台可能提供的代理地址与临时凭据。凭据不要写入代码或打包文件。

B0 默认模型为 `deepseek-flash`，视觉分析也使用该默认值。提交页面填写地址和 Key 不会自动改变代码默认模型；需要切换时配置 `MODEL` / `VISUAL_MODEL` 或发布新的代码版本，并确认 API 支持相应能力。

## 提交记录

上传 ZIP，选择 Python runtime，保存提交后选择任务运行。保留代码提交号、ZIP 摘要、任务版本、模型配置、run ID、最终测试结果、耗时与实际成本。编译状态以 `.arc/compilation.json` 和最终评测报告共同核对。
