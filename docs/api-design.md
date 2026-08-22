# API Design

## API Goals

MVP API 只覆盖长时间任务管理的基础闭环，不引入自动编程、PR、部署或任意执行能力。

任务从创建开始就是 `Task`，只是初始状态可以为 `intake`。

## Endpoints

### Task APIs

#### POST /tasks

创建任务。

Request body example:
```json
{
  "title": "Investigate flaky import pipeline",
  "goal": "Find the root cause and propose a resolution",
  "initial_message": "The import pipeline has intermittent failures after retry"
}
```

Response shape example:
```json
{
  "task": {
    "id": "task_123",
    "status": "intake",
    "title": "Investigate flaky import pipeline",
    "goal": "Find the root cause and propose a resolution"
  },
  "next_actions": [
    {
      "type": "await_plan_generation",
      "label": "Generate an initial step plan",
      "target": {
        "task_id": "task_123",
        "step_id": null,
        "run_id": null,
        "capability_invocation_id": null
      }
    }
  ]
}
```

#### GET /tasks

列出任务。

#### GET /tasks/{task_id}

获取单个任务详情。

返回中应包含：
- task 基本信息
- 当前状态
- 摘要信息
- 当前 revision
- 结构化 `next_actions`

### Task Conversation APIs

#### POST /tasks/{task_id}/messages

向任务追加对话消息。

用途：
- 补充上下文
- 追加需求
- 请求计划修订

#### POST /tasks/{task_id}/generate-plan

根据当前任务与对话上下文生成步骤计划。

用途：
- 从 `intake` 进入可执行步骤结构
- 生成初始 Step 集合
- 后续也可用于基于新上下文提出修订方案

#### POST /tasks/{task_id}/approve-plan

对任务当前计划进行审核确认。

用途：
- 接受计划
- 拒绝计划
- 标记需要修订

### Step APIs

#### POST /tasks/{task_id}/steps

创建步骤。

应支持以下场景：
- 新增 step
- 在指定位置插入 step
- 替代已有 step
- 创建并行 variant step
- 基于已有 step 复制子步骤树

Request body example:
```json
{
  "title": "Compare two remediation options",
  "objective": "Evaluate tradeoffs before implementation",
  "insert_after_step_id": "step_2",
  "mode": "insert"
}
```

#### GET /tasks/{task_id}/steps

列出任务步骤。

返回不应把 steps 描述为不可变化的固定数组语义，而应体现：
- 顺序
- 层级
- variant 分组
- 是否被跳过
- 是否为最终选中分支

### StepRun APIs

#### POST /tasks/{task_id}/steps/{step_id}/runs

创建某个 Step 的一次运行尝试。

Request body example:
```json
{
  "executor_type": "agent",
  "executor_ref": "planner-agent",
  "input": {
    "instructions": "Draft remediation analysis"
  }
}
```

说明：
- 一个 Step 可以多次创建 run
- 每次调用创建新的 `StepRun`
- 历史 run 不覆盖

#### GET /tasks/{task_id}/steps/{step_id}/runs

列出某个 Step 的全部运行历史。

### Run Review APIs

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit

提交某次运行结果，通常把 run 状态推进到 `submitted`。

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/review

审核某次运行结果。

Request body example:
```json
{
  "decision": "needs_revision",
  "comment": "Please compare failure modes more explicitly"
}
```

审核后可导致：
- `accepted`
- `rejected`
- 或通过审核结论触发 rerun

### Rerun API

#### POST /tasks/{task_id}/steps/{step_id}/rerun

为某个 Step 创建新的运行尝试。

请求可指定：
- 基于哪个历史 run 重跑
- 是否更换 executor
- 是否调整输入

语义上应创建新的 `StepRun`，而不是覆盖旧记录。

### Timeline and Artifact APIs

#### GET /tasks/{task_id}/timeline

返回任务时间线。

应包含：
- task 状态变化
- step 创建、跳过、替代、fork、variant 选择
- run 提交与审核
- capability invocation 事件
- artifact 产出事件

#### GET /tasks/{task_id}/artifacts

返回任务相关产物。

应支持按以下维度过滤或展示：
- task
- step
- run
- capability invocation

## next_actions Shape

`next_actions` 必须是结构化对象，不允许只返回字符串。

每个 `next_action` 必须包含明确 target：
- `task_id`
- `step_id`，如适用
- `run_id`，如适用
- `capability_invocation_id`，如适用

`target` 必须显式包含 `task_id`。当动作目标涉及 step、run 或 capability invocation 时，必须同时包含对应的 `step_id`、`run_id`、`capability_invocation_id`。不适用的字段可以省略或为 null，但不能用纯字符串替代 target。

Example:
```json
{
  "next_actions": [
    {
      "type": "review_run",
      "label": "Review the latest submitted run",
      "target": {
        "task_id": "task_123",
        "step_id": "step_9",
        "run_id": "run_3",
        "capability_invocation_id": null
      },
      "metadata": {
        "decision_options": ["accepted", "rejected", "needs_revision"]
      }
    }
  ]
}
```

## API Design Constraints

以下约束应在全部接口中保持一致：
- 任务创建后即进入 `Task.status=intake`
- 不设置额外的前置任务实体
- `executor_type` 只允许 `human | agent | worker | system`
- 能力调用只通过 `capability_id`、`adapter_id`、`handler_name` 表达

## Explicitly Out of Scope for MVP API

MVP API 不包含：
- Source Workspace 自动改代码
- GitHub PR
- 部署
- Temporal
- 任意 CLI 执行
- 多租户认证与组织模型
- billing
- 复杂 dashboard 聚合接口
