# 通用需求、契约与影响索引

本模块读取任务的需求树、数据库 schema、API 设计和 UI 设计，生成 `.arc/contracts.json`。业务实体名、路径和规则来自输入，不按任务名分支。

## 数据与接口

- `ContractRegistry(tree, schema, backend, ui)` 建立需求引用、DB 字段、完整 API 定义、页面及关联边。
- `context_for(requirement_id)` 返回少量契约引用、显式依赖和静态检查问题；不复制整份任务。
- `topological_order()` 仅处理输入中显式声明的 `depends_on`。它不把父子包含关系解释成执行依赖，也不自动推断业务先后关系。
- `impact(requirements=..., apis=..., fields=..., pages=...)` 返回基于声明依赖和共享契约的保守关联范围，不代表精确根因或可安全省略的测试集。
- `export()` 返回可序列化副本。多个任务使用独立实例和输出目录。

可选输入示例：

```yaml
id: ROOT
children:
  - id: REQ-CREATE
    name: Create an item
  - id: REQ-VIEW
    name: View the item
    depends_on: [REQ-CREATE]
```

静态检查覆盖未定义 API、DB 字段和 UI 引用、缺失依赖及显式依赖环。检查结果先以 report-only 方式记录，不代替现有编译、HTTP 或浏览器验收。

## 运行接入

Stage 11 保存契约索引，并将少量引用附到当前需求的绑定记录中。实现修复可使用 `contract`、`dependency` 上下文查询读取需要的定义。最终回归失败时，从实际失败堆栈中的测试路径定位需求，再提供相关 API/页面源码；不把通过文件的清单当作失败根因。

`ARC_B2_CONTRACT_REGISTRY=0` 可关闭该层。B2.1 使用 B2 执行 profile，保留既有独立验收和权限约束。

## 验证范围

```sh
uv run python -m unittest discover -s tests -p test_generic_contracts.py -v
```

同一构建器以知识库、电商、任务管理三类业务数据检查关联、影响范围、循环检测、任务隔离与上下文检索。这是多领域机制测试，不是三个网站的完整生成或官方成绩。

当前是统一中间表示和契约层的最小切片。尚未实现自然语言标准化、自动推断语义依赖、依赖图驱动的阶段调度、增量编译、模型路由或交互面板。它们需要独立实现与端到端评测，不能视作本层已经具备的功能。
