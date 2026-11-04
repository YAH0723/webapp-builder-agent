# GitHub 上手与小组约定

仓库：https://github.com/YAH0723/webapp-builder-agent

main 已推送，包含参考实现、计划、实验表、Issue 和 PR 模板。此文为建议工作规范；协作者邀请、看板、里程碑、分支保护及 CI 尚未配置。

## 1. 邀请组员

由仓库所有者打开 Settings → Collaborators → Add people，输入组员 GitHub 用户名，核对账号后发送邀请。组员接受邀请后即可访问私有仓库并参与协作。GitHub Free 允许在私有仓库中邀请不限数量的协作者。

官方说明：https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository

## 2. 第一次下载代码

组员接受邀请、安装 Git 并配置自己的提交身份后，在自己电脑的项目父目录运行：

```powershell
git clone https://github.com/YAH0723/webapp-builder-agent.git
cd webapp-builder-agent
```

身份验证按 Git 的正常提示完成，不把密码或 token 写进仓库 URL。现有本地项目已经连接，不需要重新 clone。下载完成后按 `03-实验与运行手册.md` 安装依赖。

## 3. 一个任务一个分支

main 保存可运行的共享版本。小组初期采用 main + 短期任务分支；完成任务后合并，下一任务再开分支。

| 分支示例 | 工作范围 |
|---|---|
| feat/requirements-input | 自然语言需求入口 |
| feat/task-adapter | 通用任务接口与平台适配 |
| feat/traceability | 需求到代码和验收证据的追踪 |
| fix/session-state | 修复会话状态问题 |
| exp/cross-task-evaluation | 跨任务对比实验 |
| docs/team-guide | 修改协作或汇报文档 |

在工作目录干净、已有改动已提交或妥善保存的前提下，每次新任务运行：

```powershell
git switch main
git pull --ff-only
git switch -c feat/requirements-input
```

开发完成后先 `git status` 查看改动，使用 `git add` 逐项暂存本次任务文件，再提交和推送：

```powershell
git status
# 用真实文件路径替换下面的占位符，不要直接复制占位符执行
git add <本次修改的文件路径>
git commit -m "feat: add natural-language requirements input"
git push -u origin feat/requirements-input
```

也可以在网页 Code 页点击 main 下拉框，输入分支名并点击 Create branch；但本地开发时仍需 fetch 并切换到该分支。优先统一使用上面的 Git 命令，减少本地与网页分支不一致的困惑。

## 4. 发起 PR、评审、合并

1. 推送分支后进入仓库的 Pull requests → New pull request；base 选 main，compare 选任务分支。
2. 填写修改原因、关联 Issue、验证命令和结果；数据尚未测量则如实说明。
3. 指定另一位组员检查代码和验证证据。有问题则继续在该分支修改、提交、推送，PR 会随之更新。
4. 验证通过并获得至少一位其他成员同意后，由本次集成人员合并。建议统一使用 Squash and merge。
5. 合并后的任务分支可以删除；每位成员开始下一任务前更新本地 main。不要在已经完成合并的旧任务分支上继续开发新任务。

官方工作流：https://docs.github.com/en/get-started/using-github/hello-world

## 5. 必须约定的规则

| 项目 | 小组建议 |
|---|---|
| main | 首次初始化完成后，日常功能变更通过 PR；保持可启动 |
| 任务 | 每项工作建一个 Issue，写负责人、完成条件、优先级和日期 |
| 分支 | 从最新 main 创建；一个任务一个分支；避免多人同时修改同一文件 |
| PR | 一次围绕一个目标；至少一位其他成员检查；附验证证据 |
| 合并 | 集成人员合并；有冲突由分支作者处理并重新验证；不 force push main |
| 配置 | .env 和真实密钥各自本地管理；公共配置写 .env.example；日志脱敏后分享 |
| 实验 | 记录 Agent commit、task_id、模型、预算、通过率、token 与耗时；不只报最好一次 |
| 版本 | 基线、优化版、期中交付分别打标签；正式标签由集成人员统一管理 |

## 6. GitHub 功能配置清单

- **Issues**：先登记 T01–T12 待办；标签用 P0/P1/P2 和 feature/bug/experiment/docs。开始时分配负责人，完成标准写进正文。
- **Pull requests**：已提供模板；按上述评审约定执行。设置中建议启用 Squash merging，并按需要选择合并后自动删除分支。
- **Projects**：创建一个看板，状态设 Todo / In progress / In review / Done，卡片关联 Issue。Projects 可关联 Issue 和 PR，提供负责人、日期等字段。
- **Milestones**：可先设“基线可运行”“通用入口与 V1”“期中展示”三个里程碑，日期按课堂通知填写。
- **Branches / Rules**：若私有仓库的账号套餐支持，保护 main：要求 PR、至少 1 个 approval、解决评审讨论，禁止强制推送。等 CI 建立并确实可通过后，再设为必需检查。
- **Actions**：后续增加无需真实 API Key 的自动检查，例如已有离线单元测试。付费模型调用和正式评测单独触发并设预算，不作为每次普通 PR 的默认操作。

私有仓库的受保护分支需要 GitHub Pro/Team/Enterprise 等相应套餐。若当前套餐不支持，先以协作约定执行 PR 和互审，具体功能是否可用以仓库设置和账号套餐为准。

功能参考：

- Projects：https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects
- 分支保护：https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

今天的实际顺序：确认仓库文件 → 邀请并接受协作 → 认领首批 Issue → 每人开任务分支 → 做一个小改动并走完 PR 流程 → 开始基线复现。
