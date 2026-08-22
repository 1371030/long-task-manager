# System Scope

English | [简体中文](system-scope.zh-CN.md)

## MVP In Scope

> Historical MVP scope: this section records the minimum closed loop originally targeted for the MVP and is not the current project scope.

The MVP covered only the minimum closed loop required for long-running task management.

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

- A task is a `Task` from the moment it is created
- It can initially be in `status=intake`
- The system supports viewing task status, progress, and context

### Step Management

- A Step is a work-decomposition unit of a task
- A Step is not a fixed array snapshot
- Dynamic addition, insertion, skipping, replacement, and reordering are supported

### Step Runs

- One Step can have multiple `StepRun`s
- The historical record of every execution attempt must be retained
- Run results do not overwrite historical runs

### Approvals

- Plans, step results, or runs can be reviewed
- Approval request decisions are `approved` or `request_revision`
- The resulting run states are `accepted` or `rejected`

### Artifacts

- Store artifact metadata such as reports, files, links, and summaries
- Artifacts can be associated with a task, step, run, or capability invocation

### Timeline

- All key status changes and execution events enter a unified timeline
- The timeline serves traceability and auditing

### Next Actions

- `next_actions` must be an array of structured objects
- It cannot be only a list of strings
- Each `next_action` must contain an explicit target
- `target` must explicitly contain `task_id`
- When an action target involves a step, run, or capability invocation, it must also contain the corresponding `step_id`, `run_id`, and `capability_invocation_id`
- Inapplicable fields may be omitted or set to null, but a plain string cannot replace target

### Conversational Task Intake

- Users can create tasks through chat input
- The system converts the conversation into a Task and suggestions for subsequent steps

### Dynamic Steps

- Steps can be added or adjusted during execution
- New steps can be inserted between existing steps

### Parallel Step Variants

- A Step can fork into multiple parallel variants
- The substep tree can be copied
- Variants can be compared and one can be selected to enter the mainline

### Capability Invocation Records

- The system records every capability invocation
- `capability_id`, `adapter_id`, and `handler_name` express invocation semantics and implementation
- No additional tool-category enum layer is defined

## MVP Out of Scope

> Historical MVP exclusions: the following limits applied to the original MVP roadmap, not as a claim about all current project capabilities.

Out of Scope for the historical MVP:
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

The following capabilities, even if they might be needed in the future, were outside this MVP:

- Automatic code modification in Source Workspace
- Automatic creation or updating of GitHub PRs
- Deployment orchestration
- A Temporal-based workflow engine
- Arbitrary CLI execution exposed to users
- Multi-tenant permissions and organization isolation
- A billing system
- A complex operations or analytics dashboard

These are historical MVP boundaries. The current project may optionally support OpenAI-compatible textual step execution and Codex/tmux integrations, while remaining not an arbitrary command execution platform.

## Positioning Boundary

Long Task Manager is not an automatic programming platform or an arbitrary command execution platform.

It can manage long-running tasks related to coding, and the current project may optionally execute textual steps through OpenAI-compatible providers or supported Codex/tmux integrations. It does not provide unrestricted shell or CLI execution. Code editing, CLI, browser, and database are not themselves modeled as executor types in the task domain; the system focuses on task progression and records rather than productizing specific tools.
