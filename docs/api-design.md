# API Design
English | [简体中文](api-design.zh-CN.md)

## API Goals

The MVP API covers only the basic loop for long-running task management. It does not introduce automated programming, PRs, deployment, or arbitrary command execution capabilities.

The current optional OpenAI-compatible textual execution and tmux-managed Codex integration are explicitly bounded integration paths; they do not constitute arbitrary command execution capability.

A task is a `Task` from the moment it is created; its initial status may simply be `intake`.

## Endpoints

### Task APIs

#### POST /tasks

Create a task.

Request body example:
```json
{
  "title": "Investigate flaky import pipeline",
  "goal": "Find the root cause and propose a resolution",
  "initial_message": "The import pipeline has intermittent failures after retry"
}
```

Response shape example (`TaskRead` directly):
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

List tasks.

#### GET /tasks/{task_id}

Get the details of a single task. The response is a `TaskDetailResponse` containing the task, steps, progress, current pointer, and `next_actions`.

The response should include:
- Basic task information
- Current status
- Summary information
- Current revision
- Structured `next_actions`

### Task Conversation APIs

#### POST /tasks/{task_id}/messages

Append a conversation message to a task.

Uses:
- Add context
- Append requirements
- Request plan revisions

#### POST /tasks/{task_id}/generate-plan

Generate a step plan from the current task and conversation context.

Uses:
- Enter an executable step structure from `intake`
- Generate the initial Step set
- Subsequently propose revisions based on new context

#### POST /tasks/{task_id}/approve-plan

Review and confirm the task's current plan.

Uses:
- Submit `decision=approved`
- Submit `decision=request_revision`

### Step APIs

#### POST /tasks/{task_id}/steps

Create, append, or insert a step. Superseding a step, forking a variant, and cloning a subtree are separate operations with their own routes.

Request body example:
```json
{
  "title": "Compare two remediation options",
  "objective": "Evaluate tradeoffs before implementation",
  "insert_mode": "insert_after_step",
  "target_step_id": 2
}
```

#### GET /tasks/{task_id}/steps

List the task's steps.

The response should not describe steps as an immutable fixed-array semantic. Instead, it should represent:
- Order
- Hierarchy
- Variant grouping
- Whether a step was skipped
- Whether a step is the finally selected branch

### StepRun APIs

#### POST /tasks/{task_id}/steps/{step_id}/runs

Create one run attempt for a Step.

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

Notes:
- A Step can have multiple runs created
- Each call creates a new `StepRun`
- Historical runs are not overwritten

#### GET /tasks/{task_id}/steps/{step_id}/runs

List the complete run history for a Step.

### Run Review APIs

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit

Submit a run result, typically advancing the run status to `submitted`.

#### POST /tasks/{task_id}/steps/{step_id}/runs/{run_id}/review

Review a run result.

Request body example:
```json
{
  "decision": "request_revision",
  "comment": "Please compare failure modes more explicitly"
}
```

The request decision is either `approved` or `request_revision`. Separately, reviewing the request can result in the stored run status becoming:
- `accepted`
- `rejected`
- Or a rerun being triggered by the review decision

### Rerun API

#### POST /tasks/{task_id}/steps/{step_id}/rerun

Create a rerun branch from the selected source step. The operation clones that step's downstream steps and creates a run on the forked step. Historical records are preserved; the request does not select an arbitrary historical run.

The request supports:
- `executor_type`
- `executor_ref`
- `input`
- Optional `variant_label`, `title`, `objective`, `change_request`, `fork_reason`, `created_by_type`, and `created_by_id`

Request body example:
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

Response shape (`StepRerunBranchResponse`):
```json
{
  "comparison_group_id": 17,
  "forked_step_id": 12,
  "cloned_steps_count": 3
}
```

### Timeline and Artifact APIs

#### GET /tasks/{task_id}/timeline

Return the task timeline.

It should include:
- Task status changes
- Step creation, skipping, replacement, forking, and variant selection
- Run submission and review
- Capability invocation events
- Artifact production events

#### GET /tasks/{task_id}/artifacts

Return artifacts related to the task.

It should support filtering or presentation by the following dimensions:
- Task
- Step
- Run
- Capability invocation

## next_actions Shape

`next_actions` is a list of structured `NextAction` objects; returning only a string is not allowed.

Every `NextAction` contains:
- `action_type`
- `target_type`
- `target`, an object with the relevant numeric identifiers
- `label`
- `api` with `method` and `path`
- `requires_user_input`
- `input_schema`

Example:
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

## API Design Constraints

The following constraints should be consistent across all interfaces:
- `Task.status` allows exactly `intake | planning | waiting_plan_review | planned | running | waiting_review | needs_revision | blocked | failed | completed | archived | cancelled`
- `RunStatus` allows exactly `running | submitted | accepted | rejected | failed | cancelled`
- `CapabilityInvocationStatus` allows exactly `pending | running | succeeded | failed | blocked | cancelled`
- After creation, a task immediately enters `Task.status=intake`
- No additional preliminary-task entity is defined
- `executor_type` allows only `human | agent | worker | system | codex`
- `CapabilityInvocation.invoked_by_type` allows only `human | agent | worker | system`
- Capability calls are expressed through `capability_id`, `adapter_id`, and `handler_name`; Codex is a supported `executor_type` and integration path in the current implementation

## Explicitly Out of Scope for MVP API

The MVP API does not include:
- Automatic code changes to the Source Workspace
- GitHub PRs
- Deployment
- Temporal
- Arbitrary command execution, including arbitrary CLI execution
- Multi-tenant authentication and organization models
- Billing
- Complex dashboard aggregation endpoints

If enabled, OpenAI-compatible textual execution and tmux-managed Codex integration are optional, explicitly bounded integration paths and do not change the product boundary against arbitrary command execution.
