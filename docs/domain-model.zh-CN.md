# Domain Model
[English](domain-model.md) | 简体中文

## 核心实体关系图

系统核心模型：

`Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event`

此外包含：
- `TaskMessage`
- `TaskRevision`
- `TaskReview`
- `Capability`
- `StepComparisonGroup`

## Task

表示一个长期任务。

建议字段：
- `id`
- `title`
- `goal`
- `status` (`intake`, `planning`, `waiting_plan_review`, `planned`, `running`, `waiting_review`, `needs_revision`, `blocked`, `failed`, `completed`, `archived`, `cancelled`)
- `summary`
- `current_revision_id`
- `created_by`
- `created_at`
- `updated_at`

说明：
- 任务从创建开始就是 `Task`
- 任务创建后即进入 `Task.status=intake`
- 不设置额外的前置任务实体

## TaskMessage

表示任务上下文中的一条对话消息。

建议字段：
- `id`
- `task_id`
- `author_type`
- `author_id`
- `message`
- `created_at`

用途：
- 保存对话式任务输入
- 为计划生成和步骤调整提供上下文

## TaskRevision

表示任务结构的一次版本化快照或修订记录。

建议字段：
- `id`
- `task_id`
- `revision_number`
- `reason`
- `created_by_type`
- `created_by_id`
- `created_at`

用途：
- 记录计划演进
- 跟踪步骤结构调整
- 支持审计而不是覆盖式更新

## TaskReview

表示一次不可变的任务级进度复盘。

字段：
- `id`
- `task_id`
- `previous_review_id`（可空）
- `expected_progress_percent`
- `actual_progress_percent`
- `variance_percentage_points`
- `classification`（`ahead`、`on_track`、`behind`）
- `snapshot_json`
- `observations_json`
- `suggestions_json`
- `decision`（`keep_plan`、`adjust_plan`，可空）
- `decision_note`
- `decided_by_type`、`decided_by_id`、`decided_at`
- `created_by_type`、`created_by_id`、`created_at`

设计约束：
- 每条复盘保留创建时的进度依据。
- `previous_review_id` 形成递归历史，不改写早期快照。
- 决策只能记录一次，且不会修改任务、步骤或运行。
- 任务级进度复盘与用于计划和运行结果审核的 `Approval` 相互独立。

## Step

表示任务中的一个工作步骤。

建议字段：
- `id`
- `task_id`
- `parent_step_id`（可空）
- `comparison_group_id`（可空）
- `title`
- `objective`
- `status`
- `position`
- `variant_label`（可空）
- `selected_variant`（布尔，可空）
- `created_at`
- `updated_at`

设计约束：
- Step 不是固定数组中的一次性条目
- Step 必须支持动态新增、插入、跳过、替代与重排
- Step 可以 fork 成并行 variant
- Step 可以复制子步骤树
- Step 本身不保存唯一执行结果

## StepRun

表示某个 Step 的一次执行尝试。

建议字段：
- `id`
- `task_id`
- `step_id`
- `attempt_number`
- `executor_type`
- `executor_ref`
- `status` (`running`, `submitted`, `accepted`, `rejected`, `failed`, `cancelled`)
- `input`
- `output`
- `error`
- `started_at`
- `ended_at`
- `duration_ms`

关键约束：
- 一个 Step 可以有多个 `StepRun`
- 历史 run 不能覆盖
- Step 的执行结果以 StepRun 为准，而不是写回为唯一结果

## Capability

表示系统中的能力定义。

建议字段：
- `id`
- `name`
- `description`
- `input_schema`
- `output_schema`
- `status`
- `created_at`
- `updated_at`

示例：
- `call_codex`
- `run_tests`
- `scan_source`
- `generate_report`
- `query_database`
- `browse_url`
- `export_openapi`

说明：
- Capability 是能力定义
- Skill 如果出现，只能作为 Capability 的一种表达方式
- Skill 不作为独立实体

## CapabilityInvocation

表示一次能力调用记录。

建议字段：
- `id`
- `task_id`
- `step_id`
- `run_id`
- `invoked_by_type`
- `invoked_by_id`
- `capability_id`
- `adapter_id`
- `handler_name`
- `status` (`pending`, `running`, `succeeded`, `failed`, `blocked`, `cancelled`)
- `input`
- `output`
- `error`
- `duration_ms`
- `created_at`

设计约束：
- 使用 `capability_id` 表示调用了什么能力
- 使用 `adapter_id` 表示能力如何实现
- 使用 `handler_name` 表示具体处理入口
- 不设置额外的工具类别枚举层

## Approval

表示一次审核或审批结论。

建议字段：
- `id`
- `task_id`
- `step_id`（可空）
- `run_id`（可空）
- `decision` (`approved`, `request_revision`)

对于 run 审核，请求中的 decision 为 `approved` 或 `request_revision`；已存储的 run 状态则单独记录为 `accepted` 或 `rejected`。
- `comment`
- `reviewed_by_type`
- `reviewed_by_id`
- `created_at`

用途：
- 审核计划
- 审核步骤结果
- 审核某次具体运行结果

## Artifact

表示执行过程产生的产物。

建议字段：
- `id`
- `task_id`
- `step_id`（可空）
- `run_id`（可空）
- `capability_invocation_id`（可空）
- `type`
- `name`
- `uri`
- `metadata`
- `created_at`

用途：
- 关联报告、文件、链接、导出物、摘要等

## Event

表示系统中的时间线事件。

建议字段：
- `id`
- `task_id`
- `step_id`（可空）
- `run_id`（可空）
- `capability_invocation_id`（可空）
- `event_type`
- `payload`
- `created_at`

用途：
- 构建统一 timeline
- 记录任务状态流转、运行事件、审批事件、分叉事件

## StepComparisonGroup

表示一组并行 step variants 的对比集合。

建议字段：
- `id`
- `task_id`
- `origin_step_id`
- `selection_status`
- `selected_step_id`（可空）
- `created_at`
- `updated_at`

用途：
- 组织多个并行 variant
- 记录对比与最终选择结果

## 执行者类型规则

`executor_type` 只允许：
- `human`
- `agent`
- `worker`
- `system`
- `codex`

`CapabilityInvocation.invoked_by_type` 只允许：
- `human`
- `agent`
- `worker`
- `system`

当前实现支持将 Codex 作为 `executor_type` 和集成路径。这不改变以下区分：`capability_id` 表示调用了什么能力，`adapter_id` 表示如何实现，`handler_name` 表示具体处理入口；也不表示支持任意命令执行。

明确不允许作为 `executor_type` 的值：
- `skill`
- `cli`
- `file`
- `browser`
- `database`

原因：
- `executor_type` 表示谁负责
- 工具、环境和接口属于能力实现细节，不是任务核心执行者类型
- 由 tmux 管理的 Codex 集成与 OpenAI-compatible textual execution 是当前实现支持的、有明确边界的集成路径

## 关系摘要

- 一个 `Task` 有多条 `TaskMessage`
- 一个 `Task` 有多次 `TaskRevision`
- 一个 `Task` 有多个 `Step`
- 一个 `Step` 有多个 `StepRun`
- 一个 `StepRun` 有多个 `CapabilityInvocation`
- `Approval` 可关联 `Task`、`Step` 或 `StepRun`
- `Artifact` 可关联 `Task`、`Step`、`StepRun` 或 `CapabilityInvocation`
- `Event` 记录整个生命周期中的关键变化
- `StepComparisonGroup` 用于管理并行 variants 的比较与择优
