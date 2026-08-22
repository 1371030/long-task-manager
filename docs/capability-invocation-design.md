# Capability Invocation Design

## 设计目标

系统需要记录“谁在什么上下文下调用了什么能力，以及结果如何”。

为此，任务领域中应区分三件事：
- `executor_type` = 谁负责
- `capability_id` = 调用了什么能力
- `adapter_id` = 能力如何实现

## 三层语义划分

### executor_type

表示责任主体，只允许：
- `human`
- `agent`
- `worker`
- `system`

它回答的问题是：**谁负责这次执行或发起动作。**

### capability_id

表示能力定义。

示例：
- `call_codex`
- `run_tests`
- `scan_source`
- `generate_report`
- `query_database`
- `browse_url`
- `export_openapi`

它回答的问题是：**这次调用想完成什么能力。**

### adapter_id

表示能力的实现适配器。

示例形式：
- `codex_adapter`
- `browser_adapter`
- `db_query_adapter`
- `report_export_adapter`

它回答的问题是：**这个能力是通过哪种接入方式实现的。**

## Why Not an Extra Tool Category

MVP 不设置额外的工具类别枚举层。

能力调用只通过：
- `capability_id`
- `adapter_id`
- `handler_name`

来表达能力语义、实现适配器和具体处理入口。

原因：
- 这些类别把实现介质抬升成了领域主概念
- 它们既混淆“能力是什么”，也混淆“谁在执行”
- 对任务系统来说，更稳定的抽象是 capability + adapter + handler

## Skill Positioning

Skill 不应作为独立实体。

如果某项能力以 skill 形式暴露，那么 skill 只是 `Capability` 的一种表达方式或接入方式，仍然应记录为：
- 一个 `capability_id`
- 一个 `adapter_id`
- 一个 `handler_name`

## Codex Positioning

Codex 不应作为 `executor_type`。

如果文档中提到 Codex，它只能作为：
- capability 的 adapter 实现示例
- 外部执行能力示例

不能进入任务核心执行者枚举。

## CapabilityInvocation Entity

`CapabilityInvocation` 表示一次能力调用记录。

字段包括：
- `task_id`
- `step_id`
- `run_id`
- `invoked_by_type`
- `capability_id`
- `adapter_id`
- `handler_name`
- `status`
- `input`
- `output`
- `error`
- `artifacts`
- `duration_ms`

建议补充字段：
- `id`
- `invoked_by_id`
- `created_at`
- `ended_at`

## Field Notes

### task_id / step_id / run_id

定义调用发生在哪个任务上下文中。

### invoked_by_type

表示由谁发起调用，建议与执行者枚举保持一致：
- `human`
- `agent`
- `worker`
- `system`

### capability_id

引用能力定义，例如 `run_tests`。

### adapter_id

表示能力接入实现，例如通过哪类适配器转发到具体外部系统。

### handler_name

表示系统内部实际处理入口，例如某个 handler、service method 或 integration route 名称。

### status

建议至少支持：
- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

### input / output / error

分别保存调用输入、结构化输出和错误信息。

### artifacts

表示本次调用关联的产物集合，可以是 artifact id 列表或关联对象引用。

### duration_ms

记录执行耗时，便于后续分析与审计。

## Example Interpretation

一次记录可以被理解为：
- 某个 `agent`
- 在某个 task 的某个 step 的某次 run 中
- 调用了 `scan_source` 这个 capability
- 通过 `browser_adapter` 或 `codex_adapter` 等适配器实现
- 由某个 `handler_name` 实际处理
- 产生了输出、错误信息和产物

## Design Summary

该模型的重点是：
- 用 `executor_type` 表达责任主体
- 用 `capability_id` 表达能力语义
- 用 `adapter_id` 与 `handler_name` 表达实现方式
- 不把 skill、Codex、CLI、browser、database、file 直接提升为任务领域核心类型
