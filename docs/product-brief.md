# Product Brief

English | [简体中文](product-brief.zh-CN.md)

## Product Goal

Long Task Manager is a management system for long-running tasks.

Its goal is not to replace executors, but to let users initiate tasks through natural conversation and continuously manage steps, execution attempts, approvals, artifacts, and events as the task progresses.

## Target Experience

Users can create tasks as they would in a chat.

Once created, a task becomes a `Task`; its initial state can be `status=intake`, rather than first entering an additional pre-task entity.

The system should support the following core experiences:

- Users can create tasks as they would in a chat
- Tasks can be broken down into multiple steps
- Each step can be executed multiple times
- Each execution has an independent run record
- Users can review, return, and rerun work
- Steps can be added dynamically during execution
- Steps can fork into parallel approaches
- The system records artifacts, events, and progress

## Key Product Principles

### 1. Task first: creation immediately belongs to Task

A task is a `Task` from the moment it is created.

The system can distinguish the task’s stage, for example:
- `intake`
- `planning`
- `running`
- `blocked`
- `completed`

After creation, the task immediately enters `Task.status=intake`; conversational input belongs directly to the Task, with no additional pre-task entity.

### 2. Step is an evolvable structure, not a fixed checklist

Task steps are not a fixed array that becomes immutable after being generated once.

The system must support:
- Dynamically adding steps
- Inserting steps
- Skipping steps
- Replacing an old step with a new step
- Forking into parallel variants
- Copying the substep tree
- Comparing multiple variants
- Selecting a final variant to enter the mainline

### 3. Run records matter more than the final result

Step does not store one unique execution result.

Each execution forms an independent `StepRun`, used to preserve:
- Input
- Output
- Status
- Executor
- Review conclusion
- Artifacts
- Duration

Historical runs must be preserved in full and cannot be overwritten.

### 4. Process management is decoupled from execution

The system manages the process; it does not replace execution tools.

External executors can be:
- `human`
- `agent`
- `worker`
- `system`

Codex, CLI, browser, database, and file are not executor types in the task domain; they are details of the capability implementation layer.

The current project may optionally support OpenAI-compatible textual step execution and tmux-managed Codex integrations. It remains not an arbitrary command execution platform: these are supported execution integrations, not unrestricted shell or CLI access.

### 5. Capability invocations are auditable

The system needs to record every capability invocation to track:
- What capability was called
- Who initiated it
- Which adapter implemented it
- What it output
- Whether it failed
- Which artifacts it produced

## Success Criteria

If the MVP succeeds, users should be able to:
- Create a long-running task through conversation
- See the task decomposed into executable steps
- Run and rerun a step multiple times
- Review and return results
- Add steps or fork parallel approaches along the way
- View the complete timeline, artifacts, and structured next actions
