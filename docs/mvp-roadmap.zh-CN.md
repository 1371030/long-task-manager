# MVP Roadmap

[English](mvp-roadmap.md) | 简体中文

> 历史 MVP 路线图：本文描述的是原始 MVP 阶段，不代表当前项目范围。

## Phase 1：核心 Task / Step / StepRun 模型

目标：建立长时间任务管理的最小核心模型。

范围：
- `Task`
- `TaskMessage`
- `TaskRevision`
- `Step`
- `StepRun`
- `Approval`
- `Artifact`
- `Event`

本阶段重点：
- 任务创建即为 `Task`
- 支持 `status=intake`
- Step 与 StepRun 职责分离
- 支持一个 Step 对应多个 StepRun
- 历史 run 永不覆盖
- 建立基础 timeline 与 artifact 关联能力

完成标志：
- 可以创建任务
- 可以创建步骤
- 可以对步骤发起多次运行
- 可以查看运行历史、产物和事件

## Phase 2：对话式任务接收

目标：让用户可以像聊天一样创建和补充任务。

范围：
- 对话消息写入 `TaskMessage`
- 基于消息生成初始计划
- 计划审核与修订
- 输出结构化 `next_actions`

本阶段重点：
- 任务创建后即进入 `Task.status=intake`
- 使用 `Task.status=intake` 表达任务刚创建但尚未成形
- 对话是任务输入方式，不是独立的前置任务容器

完成标志：
- 用户可通过消息创建任务
- 系统可生成初始 step 计划
- 用户可审核计划并继续补充上下文

## Phase 3：动态步骤与重跑支持

目标：支持任务在执行过程中的结构演进。

范围：
- 动态新增 step
- 插入 step
- 跳过 step
- 替代 step
- rerun 某个 step
- 审核后打回与再次提交
- 记录 capability invocation

本阶段重点：
- Step 不是固定数组
- `needs_revision` 导致新的 `StepRun`
- 用 `capability_id`、`adapter_id`、`handler_name` 建立可审计调用记录

完成标志：
- 步骤可在任务中途被调整
- 某一步被打回后可多次重跑
- 每次能力调用都可追踪到对应 step 和 run

## Phase 4：并行步骤变体与对比

目标：支持并行方案探索与结构化择优。

范围：
- Step fork 成并行 variants
- 复制子步骤树
- `StepComparisonGroup`
- variant 对比
- 最终 variant 选择并回归主线

本阶段重点：
- 并行方案是任务结构的一等能力
- 未被选中的 variant 也保留完整历史
- 选中的 variant 决定后续主线路径

完成标志：
- 可以从一个 step 分叉多个方案
- 每个方案可独立运行与产出结果
- 系统可对比 variants 并选出最终进入主线的方案

## 所有历史 MVP 阶段均不包含的目标

在以上四个历史 MVP 阶段中，都不引入以下能力：
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

这些排除项仅描述历史 MVP 路线图。当前项目可以选择性支持 OpenAI-compatible textual step execution 以及 Codex/tmux 集成，但仍不是任意命令执行平台。这些当前可选能力不属于历史路线图，也不改变其原始范围。
