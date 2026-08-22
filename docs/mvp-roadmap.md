# MVP Roadmap

English | [简体中文](mvp-roadmap.zh-CN.md)

> Historical MVP roadmap: this document describes the original MVP phases and is not the current project scope.

## Phase 1: Core Task / Step / StepRun model

Goal: Establish the minimum core model for long-running task management.

Scope:
- `Task`
- `TaskMessage`
- `TaskRevision`
- `Step`
- `StepRun`
- `Approval`
- `Artifact`
- `Event`

Focus of this phase:
- Task creation immediately creates a `Task`
- Support `status=intake`
- Separate the responsibilities of Step and StepRun
- Support multiple StepRuns for one Step
- Never overwrite historical runs
- Establish basic timeline and artifact association capabilities

Completion criteria:
- Tasks can be created
- Steps can be created
- Multiple runs can be initiated for steps
- Run history, artifacts, and events can be viewed

## Phase 2: Conversational task intake

Goal: Allow users to create and supplement tasks as they would in a chat.

Scope:
- Write conversational messages to `TaskMessage`
- Generate an initial plan from messages
- Plan review and revision
- Output structured `next_actions`

Focus of this phase:
- After task creation, enter `Task.status=intake` immediately
- Use `Task.status=intake` to express that a task has just been created but has not yet taken shape
- Conversation is a task input method, not a separate pre-task container

Completion criteria:
- Users can create tasks through messages
- The system can generate an initial step plan
- Users can review the plan and continue supplementing context

## Phase 3: Dynamic steps and rerun support

Goal: Support structural evolution of a task during execution.

Scope:
- Dynamically add steps
- Insert steps
- Skip steps
- Replace steps
- Rerun a step
- Return and resubmit after review
- Record capability invocations

Focus of this phase:
- Step is not a fixed array
- `needs_revision` results in a new `StepRun`
- Use `capability_id`, `adapter_id`, and `handler_name` to establish auditable invocation records

Completion criteria:
- Steps can be adjusted midway through a task
- A returned step can be rerun multiple times
- Every capability invocation can be traced to its corresponding step and run

## Phase 4: Parallel step variants and comparison

Goal: Support parallel solution exploration and structured selection of the best approach.

Scope:
- Fork a Step into parallel variants
- Copy the substep tree
- `StepComparisonGroup`
- Variant comparison
- Select the final variant and return it to the mainline

Focus of this phase:
- Parallel approaches are a first-class task structure capability
- Unselected variants also retain their complete history
- The selected variant determines the subsequent mainline path

Completion criteria:
- Multiple approaches can be forked from one step
- Each approach can run independently and produce results
- The system can compare variants and select the approach that ultimately enters the mainline

## Non-Goals Across All Historical MVP Phases

Across the four historical phases above, the following capabilities were not introduced:
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

These exclusions describe the historical MVP roadmap only. The current project may optionally support OpenAI-compatible textual step execution and tmux-managed Codex integrations, while remaining not an arbitrary command execution platform. Those optional current capabilities are outside the historical roadmap and do not change its original scope.
