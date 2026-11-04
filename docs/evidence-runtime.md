# B2.3：失败证据与通用功能骨架

## 失败证据

E2E fixture 在失败测试中附加 `arc-diagnostics` JSON：API 请求的 method/path/status、网络失败、页面运行错误和控制台错误。最多保留 40 条观察，优先移除成功请求。它不采集请求头或请求体；URL 去掉凭据、查询参数和 fragment，错误文本进行常见凭据形式的遮蔽。

观察不改变验收语义：正常业务拒绝的 4xx 不自动记为失败。原有断言、运行错误检查、完整最终回归仍决定通过状态。截图、trace 和完整检查报告继续保留。

解析器只读取指定名称/类型、大小受限的附件；文件型附件必须位于当前工作区的 `frontend/test-results` 内。实现代理收到至多 12 条去重观察、相关 API ID、需求 ID 和已有源码路径；网络/运行错误、5xx 优先于成功请求。数量上限可能省略部分观察，不构成精确根因证明。模型输入移除重复的原始 diagnostics，保留断言反馈；摘要写入 `.arc/diagnostics/*.json`。

路径只用于导航到原本可修改的应用源码，不扩大独立测试任务的读取范围或实现代理修改测试的权限。

## 通用功能骨架

`prepare_frontend()` 将可选库放到生成应用的 `frontend/src/arc-lib/`：

| 模块 | 接口与范围 |
|---|---|
| `http.ts` | `requestJson<T>()`；保留 HTTP 状态与响应数据、支持 signal、空响应、结构化错误，不自动重试 |
| `api-client.ts` | 根据当前契约生成 API ID、method/path；`callApi()` 编码标准 `:param` 和查询参数 |
| `useSubmit.ts` | 同一 hook 实例的并发调用共享一个 Promise，暴露 pending/success/error/reset |
| `async-state.ts` | 异步状态的 TypeScript 联合类型 |
| `AsyncBoundary.tsx` | 按状态渲染调用方提供的内容，不预设文案或业务规则 |

API ID 约束是编译期提示，泛型 `T` 不代表响应已通过运行时 schema 校验。骨架不提供业务权限、认证策略、服务器端幂等性、状态迁移或数据库 CRUD。多次已完成的提交、多个 hook 实例与跨客户端请求仍需业务层处理。

库目录不是新的框架要求。模型可选用或修改应用辅助代码；自定义文件保留，仅刷新 hash 与上次托管版本一致的文件。`.arc/feature_runtime.json` 记录来源摘要。向实现代理提供已知接口目录；独立验收生成任务不提供该目录，也不使用这些辅助函数代替真实浏览器行为。

## 开关与验证

默认随 B2 profile 启用，支持独立关闭：`ARC_B2_DIAGNOSTICS=0`、`ARC_B2_FEATURE_RUNTIME=0`。B0/B1 profile 不默认启用。B2.2 提交包保持冻结。

```sh
uv run python -m unittest discover -s tests -p test_b23_evidence.py -v
uv run python -m unittest discover -s tests -p test_feature_runtime.py -v
uv run python team-tools/smoke-b23.py
uv run python team-tools/package-baseline.py --variant B2.3
```

Smoke 使用真实 React/Express/SQLite/Chromium：制造数据库字段错误，捕获 HTTP 500，将证据交给脚本化实现代理，通过现有文件工具修复源码，再运行完整用例。覆盖并发重复提交、刷新回读、业务拒绝与重试、路径/查询编码、空响应和参数错误。它不调用真实模型，不证明完整网站生成质量或官方提速。

设计参考：[FullStack-Dev 调试工具](https://github.com/mnluzimu/FullStack-Dev/tree/main/src/tools)、[bolt.diy 执行循环](https://github.com/stackblitz-labs/bolt.diy/blob/main/app/lib/.server/llm/agent-loop.ts)。本层为当前 Python 编译器实现，没有嵌入这些项目的运行栈。
