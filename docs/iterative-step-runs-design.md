# Iterative Step Runs Design

## 核心原则

Step 不是一次性结果。

一个 Step 表示“要完成的工作单元”，而不是“只执行一次并保存唯一结果的槽位”。真正的执行尝试由 `StepRun` 表示。

## Why StepRun Exists

在长期任务中，同一个步骤往往会经历多次尝试：
- 首次执行
- 人工审核后打回
- 修订后重跑
- 更换执行者后再次运行
- 并行方案试验

因此系统必须把“步骤定义”和“执行尝试”拆开。

## Step 与 StepRun 的职责分离

### Step 负责
- 表达步骤目标
- 参与任务结构编排
- 承载状态汇总
- 支持插入、跳过、替代、分叉与合流

### StepRun 负责
- 保存一次具体执行尝试
- 保存输入、输出、错误、耗时与执行者
- 承接能力调用记录
- 承接审核结果

## Multiple Runs Per Step

每个 Step 可以有多个 `StepRun`。

典型生命周期：
1. 创建 Step
2. 发起第一次 StepRun
3. 运行结束后提交结果
4. 审核 accepted 或 rejected
5. 若 `needs_revision` 或 `rejected`，则重新发起新的 StepRun

历史 Run 不覆盖。

这意味着：
- `run_1` 失败后仍保留
- `run_2` 打回后仍保留
- `run_3` 被接受后也不应删除前序记录

## Run Status Model

Run 可以处于以下状态之一：
- `queued`
- `running`
- `submitted`
- `accepted`
- `rejected`
- `failed`
- `cancelled`

其中至少应支持以下关键业务状态：
- `submitted`
- `accepted`
- `rejected`
- `failed`

## Review and Rerun Flow

一个常见流程如下：

1. StepRun 执行完成，状态进入 `submitted`
2. 审核人创建 `Approval`
3. 若通过，则 StepRun 标记为 `accepted`
4. 若不通过，则 StepRun 标记为 `rejected`
5. 若要求修改，则可记录 `needs_revision` 审核结论，并触发新的 rerun

`needs_revision` 不意味着覆盖原运行记录，而是意味着创建新的 `StepRun`。

## Dynamic Step Evolution

Step 不能被当作任务开始时就完全确定的固定数组。

系统必须支持：
- 动态新增 step
- 在任意位置插入 step
- 跳过 step
- 用新 step 替代已有 step
- 在执行中根据结果扩展后续步骤

这使得计划可以随着任务认知变化而演进。

## Forking Variants

某些步骤存在多种可行方案时，Step 应支持 fork 成多个并行 variant。

例如：
- 方案 A
- 方案 B
- 方案 C

每个 variant 都可以独立拥有：
- 自己的 StepRun 历史
- 自己的子步骤
- 自己的产物与审批记录

## Copying Substep Trees

当一个 Step fork 成并行 variant 时，系统可以复制原有子步骤树到各个 variant 分支。

这样做的意义是：
- 让不同方案拥有对称的执行结构
- 便于比较相同步骤在不同方案下的结果
- 避免把变体实现限制在单层 step 上

## Comparing Variants

variants 可以并行执行并对比。

系统至少需要支持：
- 把多个 variant 归入同一个 comparison group
- 记录每个 variant 的状态、产物和运行结果
- 支持审核人查看差异并给出选择结论

## Selecting the Final Variant

对比完成后，需要从多个 variants 中选择一个进入主线。

选择结果应满足：
- 被选中的 variant 标记为最终方案
- 未被选中的 variant 保留历史记录
- 主线后续步骤继续从被选中的 variant 继承

## Design Summary

这个设计确保：
- Step 是结构节点，不是唯一结果容器
- StepRun 是执行历史的真实载体
- 历史 run 永不覆盖
- 计划可在执行中持续演化
- 并行方案可以被系统化比较，而不是临时拼接
