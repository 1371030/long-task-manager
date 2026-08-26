# API Design
[English](api-design.md) | 简体中文

## API 目标

MVP API 只覆盖长时间任务管理的基础闭环，不引入自动编程、PR、部署或任意命令执行能力。

当前可选的 OpenAI-compatible textual execution 以及由 tmux 管理的 Codex 集成仅属于明确的集成路径，不构成任意命令执行能力。

任务从创建开始就是 `Task`，只是初始状态可以为 `intake`。

## API 设计

### Task API

#### POST /tasks

创建任务。

请求体示例：
```json
{
  "title": "Investigate flaky import pipeline",
  "goal": "Find the root cause and propose a resolution",
  "initial_message": "The import pipeline has intermittent failures after retry"
}
```

响应示例（直接返回 `TaskRead`）：
```json
{
  "id": 123,
  "title": "Investigate flaky import pipeline",
  "goal": "Find the root cause and propose a resolution",
  "constraints": null,
  "status": "intake",
  "summary": null,
  "current_revision_id": null,
  "created_by": "user",
  "executor_mode": "agent",
  "project_path": null,
  "codex_tmux_session": null,
  "log_path": null,
  "created_at": "2026-08-22T10:30:00Z",
  "updated_at": "2026-08-22T10:30:00Z"
}
```

#### GET /tasks

列出任务。

#### GET /tasks/{task_id}

获取单个任务详情。返回类型为 `TaskDetailResponse`，包含任务、步骤、进度、当前指针和 `next_actions`。

返回中应包含：
- task 基本信息
- 当前状态
- 摘要信息
- 当前 revision
- 结构化 `next_actions`

### Task 对话 API

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
- 提交 `decision=approved`
- 提交 `decision=request_revision`

### Step API

#### POST /tasks/{task_id}/steps

创建、追加或插入 step。替代 step、fork variant 以及复制子步骤树属于独立操作，使用各自的路由。

请求体示例：
```json
{
  "title": "Compare two remediation options",
  "objective": "Evaluate tradeoffs before implementation",
  "insert_mode": "insert_after_step",
  "target_step_id": 2
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

### StepRun API

#### POST /tasks/{task_id}/steps/{step_id}/runs

创建某个 Step 的一次运行尝试。

请求体示例：
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

### Run 审核 API

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit

提交某次运行结果，通常把 run 状态推进到 `submitted`。

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/review

审核某次运行结果。

请求体示例：
```json
{
  "decision": "request_revision",
  "comment": "Please compare failure modes more explicitly"
}
```

请求中的 decision 只能是 `approved` 或 `request_revision`。此外，审核请求后，已存储的 run 状态可能变为：
- `accepted`
- `rejected`
- 或通过审核结论触发 rerun

### 重跑 API

#### POST /tasks/{task_id}/steps/{step_id}/rerun

从选定的源 step 创建 rerun 分支。该操作会复制该 step 的下游 steps，并在 fork 后的 step 上创建一次运行。历史记录会保留；请求不会选择任意历史 run。

请求支持：
- `executor_type`
- `executor_ref`
- `input`
- 可选的 `variant_label`、`title`、`objective`、`change_request`、`fork_reason`、`created_by_type` 和 `created_by_id`

请求体示例：
```json
{
  "executor_type": "agent",
  "executor_ref": "planner-agent",
  "input": {
    "instructions": "Reassess the remediation analysis"
  },
  "variant_label": "revised-analysis",
  "title": "Reassess remediation options",
  "objective": "Incorporate the requested failure-mode comparison",
  "change_request": "Compare failure modes more explicitly",
  "fork_reason": "Run review requested a revised branch",
  "created_by_type": "human",
  "created_by_id": "reviewer-7"
}
```

响应结构（`StepRerunBranchResponse`）：
```json
{
  "comparison_group_id": 17,
  "forked_step_id": 12,
  "cloned_steps_count": 3
}
```

### 进度复盘 API

#### POST /tasks/{task_id}/progress-reviews

为已有已批准计划的任务创建不可变进度复盘快照。调用方填写 0 到 100 的 `expected_progress_percent`，服务端复用有效步骤的标准进度算法计算实际进度，并按下式计算：

```text
variance_percentage_points = actual_progress_percent - expected_progress_percent
```

偏差大于 `+5` 时为 `ahead`，小于 `-5` 时为 `behind`，包含边界的 `-5` 到 `+5` 为 `on_track`。响应包含事实快照计数、确定性观察和对现有步骤操作的建议；系统不会自动执行建议。

任务处于 `planned`、`running`、`waiting_review`、`needs_revision`、`blocked`、`failed` 或 `completed` 时可创建复盘。最新复盘尚未决策时，不能创建下一条。

#### GET /tasks/{task_id}/progress-reviews

按时间倒序返回不可变复盘快照。每条记录通过 `previous_review_id` 指向上一条复盘。

#### POST /tasks/{task_id}/progress-reviews/{review_id}/decision

记录一次明确的 `keep_plan` 或 `adjust_plan` 决策，可附备注。每条复盘只能决策一次。该决定仅用于审计，不会改变任务状态、修改步骤或启动 retry/rerun。

### 时间线与产物 API

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

## next_actions 结构

`next_actions` 是结构化的 `NextAction` 对象列表，不允许只返回字符串。

每个 `NextAction` 包含：
- `action_type`
- `target_type`
- `target`，其中包含相关的数字标识符
- `label`
- 包含 `method` 和 `path` 的 `api`
- `requires_user_input`
- `input_schema`

示例：
```json
{
  "next_actions": [
    {
      "action_type": "review_run",
      "target_type": "run",
      "target": {
        "task_id": 123,
        "step_id": 9,
        "run_id": 3,
        "capability_invocation_id": null
      },
      "label": "Review the latest submitted run",
      "api": {
        "method": "POST",
        "path": "/tasks/123/steps/9/runs/3/review"
      },
      "requires_user_input": true,
      "input_schema": {
        "decision": {
          "type": "string",
          "enum": ["approved", "request_revision"]
        },
        "comment": {
          "type": "string"
        }
      }
    }
  ]
}
```

## API 设计约束

以下约束应在全部接口中保持一致：
- `Task.status` 只允许 `intake | planning | waiting_plan_review | planned | running | waiting_review | needs_revision | blocked | failed | completed | archived | cancelled`
- `RunStatus` 只允许 `running | submitted | accepted | rejected | failed | cancelled`
- `CapabilityInvocationStatus` 只允许 `pending | running | succeeded | failed | blocked | cancelled`
- 任务创建后即进入 `Task.status=intake`
- 不设置额外的前置任务实体
- `executor_type` 只允许 `human | agent | worker | system | codex`
- `CapabilityInvocation.invoked_by_type` 只允许 `human | agent | worker | system`
- 能力调用通过 `capability_id`、`adapter_id` 和 `handler_name` 表达；当前实现支持将 Codex 作为 `executor_type` 和集成路径

## MVP API 范围外

MVP API 不包含：
- Source Workspace 自动改代码
- GitHub PR
- 部署
- Temporal
- 任意命令执行（包括任意 CLI 执行）
- 多租户认证与组织模型
- billing
- 复杂 dashboard 聚合接口

OpenAI-compatible textual execution 以及由 tmux 管理的 Codex 集成如有启用，属于可选的、明确边界的集成路径，不改变上述任意命令执行的产品边界。
