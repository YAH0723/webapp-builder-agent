# ARC-Bench 打包与提交

## B4 提交包

在仓库根目录运行：

```sh
uv run python team-tools/package-baseline.py --variant B4
```

默认输出 `releases/webapp-builder-agent-B4.zip` 和同名 JSON 摘要。可用 `--output` 指定新位置；已有发布包不会覆盖。先提交编译器改动，确保包内清单对应明确的 Git 提交。

打包工具只收集 Git 管理的编译运行文件，并检查工作区与提交一致。ZIP 根目录包含 `main.py`、`requirements.txt`、阶段脚本、`infrastructure/`、README 和文件哈希清单，不包含本地环境文件、密钥、任务数据或日志。

B0/B3 历史包使用其冻结分支或现有发布文件。本分支不会将 B4 编译器标记为历史版本。不要使用会携带 `.env` 的上游 `scripts/package.py` 提交本地配置。

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
