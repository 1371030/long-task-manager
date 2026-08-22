# System Scope

## MVP In Scope

MVP 只覆盖长时间任务管理所需的最小闭环。

In Scope:
- task management
- step management
- step runs
- approvals
- artifacts
- timeline
- next_actions
- conversational task intake
- dynamic steps
- parallel step variants
- capability invocation records

## In-Scope Clarifications

### Task Management

- 任务从创建开始就是 `Task`
- 初始可处于 `status=intake`
- 支持查看任务状态、进度和上下文

### Step Management

- Step 是任务的工作分解单元
- Step 不是固定数组快照
- 支持动态新增、插入、跳过、替代与重排

### Step Runs

- 一个 Step 可以有多个 `StepRun`
- 每次执行尝试都必须保留历史记录
- 运行结果不覆盖历史 run

### Approvals

- 支持对计划、步骤结果或 run 进行审核
- 支持 accepted、rejected、needs_revision 等结论

### Artifacts

- 保存报告、文件、链接、摘要等产物元数据
- 产物可关联到 task、step、run 或 capability invocation

### Timeline

- 所有关键状态变化和执行事件进入统一时间线
- 时间线服务于可追踪性与审计

### Next Actions

- `next_actions` 必须是结构化对象数组
- 不能只是字符串列表
- 每个 `next_action` 必须包含明确 target
- `target` 必须显式包含 `task_id`
- 当动作目标涉及 step、run 或 capability invocation 时，必须同时包含对应的 `step_id`、`run_id`、`capability_invocation_id`
- 不适用的字段可以省略或为 null，但不能用纯字符串替代 target

### Conversational Task Intake

- 用户可以通过聊天输入创建任务
- 系统将对话转化为 Task 与后续步骤建议

### Dynamic Steps

- 执行过程中允许新增或调整步骤
- 支持在已有步骤之间插入新步骤

### Parallel Step Variants

- Step 可以 fork 成多个并行 variant
- 可复制子步骤树
- 可对比 variant 并选择一个进入主线

### Capability Invocation Records

- 系统记录每一次能力调用
- 使用 `capability_id`、`adapter_id`、`handler_name` 表示调用语义与实现方式
- 不设置额外的工具类别枚举层

## MVP Out of Scope

Out of Scope for MVP:
- automatic coding
- GitHub PR
- deployment
- arbitrary shell execution
- direct CLI execution
- source code auto modification
- Temporal
- multi-tenant auth
- billing
- complex dashboard

## Out-of-Scope Clarifications

以下能力即使未来可能需要，也不属于本次 MVP：

- Source Workspace 自动改代码
- 自动创建或更新 GitHub PR
- 部署编排
- 基于 Temporal 的工作流引擎
- 面向用户开放的任意 CLI 执行
- 多租户权限与组织隔离
- 计费系统
- 复杂运营或分析 dashboard

## Positioning Boundary

Long Task Manager 不是自动编程平台。

它可以管理与编码相关的长期任务，但不会把代码编辑、CLI、浏览器或数据库本身建模为任务领域中的执行者类型。系统关注的是任务推进和记录，而不是具体工具的产品化封装。
