# ARC-Bench BookStack 需求编译智能体课程项目

优化目标：以可复现评测提高需求编译生成应用的质量，并控制 token 与时间成本。

本项目基于 [参考实现](https://github.com/code-philia/requirement-compilation-structure)，保留上游历史；初始 SHA 为 `d3da23e9897db84cfd37ce04a4ab5b38424ef399`。原始说明见 [UPSTREAM_README](docs/UPSTREAM_README.md)。

## 从这里开始

1. 阅读 [项目任务书](docs/00-项目任务书.md) 和 [两周优化计划](docs/01-优化计划.md)。
2. 按 [实验与运行手册](docs/03-实验与运行手册.md) 下载正式任务、复现 B0 并记录真实结果。
3. 认领 [小组协作待办](docs/05-小组协作.md)，使用分支与 PR 互审。
4. 按 [六页汇报提纲](docs/04-汇报提纲.md) 准备总计 10 分钟的展示与问答。

## 项目导航

| 目录 | 用途 |
|---|---|
| docs/ | 任务、计划、架构、实验、汇报和协作规范 |
| infrastructure/、00–12 脚本、main.py | 上游需求编译器源码，后续优化入口 |
| experiments/ | 真实运行与失败分析 CSV；raw/ 原始数据本地保留 |
| team-tools/ | 连接空 GitHub 仓库并首次推送的脚本 |
| .github/ | Issue 与 PR 模板 |
| materials/（本地） | 用户提供的 PPT 模板、平台页面快照 |
| tasks/（待下载，本地） | 正式 BookStack 需求、图片和平台 Agent Template |
| outputs/（运行后，本地） | 生成应用与 .arc 编译证据 |

## 当前状态

已完成本地工作区、代码核对、方案和协作材料。BookStack 平台基线、优化实现及真实成绩尚未完成；实验记录表未填入虚构数据。远程仓库创建与推送状态见 [初始化记录](docs/06-来源与初始化记录.md)。

**优先事项：** 当前 input/ 是认证示例；先确认完整 BookStack 输入与平台入口。上游 scripts/package.py 会把 .env 打包，正式提交前必须采用干净发布目录或修正打包逻辑。不要提交真实 API Key。

## 连接 GitHub

创建空的私有仓库后，在本目录执行（替换 OWNER/REPO）：

```powershell
./team-tools/Connect-GitHub.ps1 -RepositoryUrl https://github.com/OWNER/REPO.git
```

此脚本不创建远程仓库、不强制覆盖远程历史。成员用户名确认后由仓库所有者邀请协作。
