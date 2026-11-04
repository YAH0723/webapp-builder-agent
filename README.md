# WebApp Builder Agent：根据用户需求生成网站的智能体

项目目标：构建能够理解用户需求、规划并生成可运行网站、执行验证并修复问题的通用 Agent。输入可以是自然语言、结构化需求和参考图；输出是可运行的网站源码、启动说明和验证报告。

BookStack 是首个基线评测任务。ARC-Bench 提供跨任务的评测环境；同一 Agent 应通过任务输入适配不同网站，业务规则不硬编码进编译核心。初期沿用 React + Express + SQLite，网站业务类型的通用性与技术栈数量分开验证。

本项目基于 [参考实现](https://github.com/code-philia/requirement-compilation-structure)，保留上游历史；初始 SHA 为 `d3da23e9897db84cfd37ce04a4ab5b38424ef399`。原始说明见 [UPSTREAM_README](docs/UPSTREAM_README.md)。

## 从这里开始

1. 阅读 [项目任务书](docs/00-项目任务书.md) 和 [优化计划](docs/01-优化计划.md)。
2. 按 [实验与运行手册](docs/03-实验与运行手册.md) 下载正式任务、复现 B0 并记录真实结果。
3. 认领 [小组协作待办](docs/05-小组协作.md)，使用分支与 PR 互审。
4. 按 [六页汇报提纲](docs/04-汇报提纲.md) 准备总计 10 分钟的展示与问答。

## 项目导航

| 目录 | 用途 |
|---|---|
| docs/ | 任务、计划、架构、实验、汇报和协作规范 |
| infrastructure/、00–12 脚本、main.py | 上游需求编译器源码，后续优化入口 |
| experiments/ | 真实运行与失败分析 CSV；raw/ 原始数据本地保留 |
| team-tools/ | GitHub 连接脚本与干净 B0 打包工具 |
| .github/ | Issue 与 PR 模板 |
| materials/（本地） | 用户提供的 PPT 模板、平台页面快照 |
| tasks/（待下载，本地） | 各评测任务的需求和图片，以及平台 Agent Template |
| outputs/（运行后，本地） | 生成应用与 .arc 编译证据 |

## 当前状态（2026-11-04）

- **B0 已打包并提交平台运行**：运行代码保持参考提交原样，采用白名单打包，排除环境文件、密钥、任务数据及本地日志。打包方式和本地检查结果见 [B0 打包说明](docs/08-基础版打包与上传.md)。
- **平台 API 故障已修复**：此前受配额错误影响的 `0/35` 不作为有效功能基线，不继续作为当前阻塞。
- **正常模型调用已恢复**：最近收到的 BookStack 运行 `534b5c47063f` 日志截至 12:04:21，处于 Stage 08 后端实现；已统计 176 次模型调用完成、0 次模型调用失败。该快照没有最终评测结果，不能据此宣称测试通过或整任务完成。
- **已观察到效率瓶颈**：后端 API 设计阶段约 13 分 22 秒；已完成模型调用的响应时间累计约 33 分 26 秒。完整运行时间、成本和最终通过率仍待报告。
- **B1 尚未实现**：先减少无效上下文读取和重复修复，再做契约检查与更大范围的调度优化。自然语言入口、跨任务泛化和优化收益均待验证。

详见 [项目进展与 B1 执行计划](docs/09-项目进展与B1执行计划.md)。同一 Agent 应通过任务输入适配不同网站，BookStack 仅作为首个开发评测任务。

## 运行和打包

本地准备 Python 环境、Node.js、npm、Git 和 Bash，安装依赖后运行：

```powershell
uv sync --frozen
uv run python main.py --help
uv run python main.py <需求目录> --output-dir <生成应用目录>
```

以上尖括号为待替换路径；完整说明见 [实验与运行手册](docs/03-实验与运行手册.md)。仓库中的 `input/` 是认证示例，不能当作完整 BookStack 任务。

B0 使用干净打包工具：

```powershell
uv run python team-tools/package-baseline.py
```

输出到 `releases/`（本地忽略目录）。B0 默认模型为 `deepseek-flash`，API 地址和 Key 从运行环境读取；不要提交真实密钥。打包脚本会核对参考编译器未被修改，后续优化版需要新的版本和打包规则。

## 连接 GitHub

小组私有仓库：https://github.com/YAH0723/webapp-builder-agent 。main 已推送；加入小组与日常操作见 [GitHub 上手与约定](docs/07-GitHub上手与约定.md)。

创建空的私有仓库后，在本目录执行（替换 OWNER/REPO）：

```powershell
./team-tools/Connect-GitHub.ps1 -RepositoryUrl https://github.com/OWNER/webapp-builder-agent.git
```

此脚本不创建远程仓库、不强制覆盖远程历史。成员用户名确认后由仓库所有者邀请协作。
