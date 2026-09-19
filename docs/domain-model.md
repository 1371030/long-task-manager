# Domain Model
English | [简体中文](domain-model.zh-CN.md)

## Core Entity Map

The core system model is:

`Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event`

It also includes:
- `TaskMessage`
- `TaskRevision`
- `TaskReview`
- `Capability`
- `StepComparisonGroup`
- `WbsNode`
- `Milestone`
- `WbsDependency`
- `WbsChangeProposal`

## Task

Represents a long-running task.

Suggested fields:
- `id`
- `title`
- `goal`
- `status` (`intake`, `planning`, `waiting_plan_review`, `planned`, `running`, `waiting_review`, `needs_revision`, `blocked`, `failed`, `completed`, `archived`, `cancelled`)
- `summary`
- `current_revision_id`
- `created_by`
- `created_at`
- `updated_at`

Notes:
- A task is a `Task` from the moment it is created
- After creation, a task immediately enters `Task.status=intake`
- No additional preliminary-task entity is defined

## TaskMessage

Represents one conversation message in the task context.

Suggested fields:
- `id`
- `task_id`
- `author_type`
- `author_id`
- `message`
- `created_at`

Uses:
- Store conversational task input
- Provide context for plan generation and step adjustment

## TaskRevision

Represents a versioned snapshot or revision record of the task structure.

Suggested fields:
- `id`
- `task_id`
- `revision_number`
- `reason`
- `created_by_type`
- `created_by_id`
- `created_at`

Uses:
- Record plan evolution
- Track adjustments to the step structure
- Support auditing rather than overwrite-based updates

## TaskReview

Represents one immutable task-level progress review.

Fields:
- `id`
- `task_id`
- `previous_review_id` (nullable)
- `expected_progress_percent`
- `actual_progress_percent`
- `variance_percentage_points`
- `classification` (`ahead`, `on_track`, `behind`)
- `snapshot_json`
- `observations_json`
- `suggestions_json`
- `decision` (`keep_plan`, `adjust_plan`, nullable)
- `decision_note`
- `decided_by_type`, `decided_by_id`, `decided_at`
- `created_by_type`, `created_by_id`, `created_at`

Design constraints:
- Each review preserves the progress evidence as it existed when created.
- `previous_review_id` forms a recursive history without rewriting earlier snapshots.
- A decision can be recorded only once and does not mutate the task, steps, or runs.
- Task-level progress review is separate from `Approval`, which reviews plans and run results.

## WBS Planning Layer

`WbsNode` represents a non-executing work-breakdown item. A node may link through unique, nullable `execution_task_id` to one execution `Task`, but it does not create StepRuns, own plan approval, or become part of the Step progress denominator.

Tree invariants:

- A root has `parent_id=null` and `root_id=id`; every non-root node belongs to the same root as its parent.
- Siblings use unique positive positions and reads use stable depth-first `(position, id)` order.
- Existing nodes are archived with `is_active=false` rather than removed through a proposal.
- Leaf progress comes from its linked Task; parents aggregate active direct children only.

`Milestone` stores a title and human-readable criteria for one WBS node. Its API status is read-only and derived from the owning node. The current implementation does not independently evaluate criteria or use them to gate node completion.

`WbsDependency` links a predecessor to a successor in the same root. Self-links, duplicates, cross-root edges, and cycles are invalid. Unfinished predecessors derive blocked state, and a topological pass produces the longest unfinished dependency-chain hint without estimating time.

`WbsChangeProposal` preserves immutable canonical `before` and validated editable `after` snapshots. Child and dependency convenience endpoints create drafts only. New nodes use negative temporary IDs in a proposal. Approval can occur once and requires the root version to still match `base_version`; stale approval returns a conflict rather than overwriting newer structure.

## Step

Represents a work step in a task.

Suggested fields:
- `id`
- `task_id`
- `parent_step_id` (nullable)
- `comparison_group_id` (nullable)
- `title`
- `objective`
- `status`
- `position`
- `variant_label` (nullable)
- `selected_variant` (boolean, nullable)
- `created_at`
- `updated_at`

Design constraints:
- A Step is not a one-time item in a fixed array
- A Step must support dynamic addition, insertion, skipping, replacement, and reordering
- A Step can fork into parallel variants
- A Step can copy a child-step tree
- A Step itself does not store a unique execution result

## StepRun

Represents one execution attempt for a Step.

Suggested fields:
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

Key constraints:
- A Step can have multiple `StepRun` records
- Historical runs cannot be overwritten
- The Step's execution result is determined by StepRun, rather than written back as a unique result

## Capability

Represents a capability definition in the system.

Suggested fields:
- `id`
- `name`
- `description`
- `input_schema`
- `output_schema`
- `status`
- `created_at`
- `updated_at`

Examples:
- `call_codex`
- `run_tests`
- `scan_source`
- `generate_report`
- `query_database`
- `browse_url`
- `export_openapi`

Notes:
- Capability is a capability definition
- If Skill appears, it can only be one expression of Capability
- Skill is not an independent entity

## CapabilityInvocation

Represents a record of one capability call.

Suggested fields:
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

Design constraints:
- Use `capability_id` to represent what capability was called
- Use `adapter_id` to represent how the capability is implemented
- Use `handler_name` to represent the concrete handling entry point
- Do not define an additional tool-category enum layer

## Approval

Represents one review or approval decision.

Suggested fields:
- `id`
- `task_id`
- `step_id` (nullable)
- `run_id` (nullable)
- `decision` (`approved`, `request_revision`)

For run review, the request decision is `approved` or `request_revision`; the stored run status is tracked separately as `accepted` or `rejected`.
- `comment`
- `reviewed_by_type`
- `reviewed_by_id`
- `created_at`

Uses:
- Review a plan
- Review a step result
- Review a particular run result

## Artifact

Represents an artifact produced during execution.

Suggested fields:
- `id`
- `task_id`
- `step_id` (nullable)
- `run_id` (nullable)
- `capability_invocation_id` (nullable)
- `type`
- `name`
- `uri`
- `metadata`
- `created_at`

Uses:
- Associate reports, files, links, exports, summaries, and similar outputs

## Event

Represents a timeline event in the system.

Suggested fields:
- `id`
- `task_id`
- `step_id` (nullable)
- `run_id` (nullable)
- `capability_invocation_id` (nullable)
- `event_type`
- `payload`
- `created_at`

Uses:
- Build a unified timeline
- Record task status transitions, run events, approval events, and fork events

## StepComparisonGroup

Represents a comparison set for a group of parallel step variants.

Suggested fields:
- `id`
- `task_id`
- `origin_step_id`
- `selection_status`
- `selected_step_id` (nullable)
- `created_at`
- `updated_at`

Uses:
- Organize multiple parallel variants
- Record comparison and the final selection result

## Executor Type Rules

`executor_type` allows only:
- `human`
- `agent`
- `worker`
- `system`
- `codex`

`CapabilityInvocation.invoked_by_type` allows only:
- `human`
- `agent`
- `worker`
- `system`

The current implementation supports Codex as an `executor_type` and integration path. This does not change the distinction between `capability_id` (what capability was called), `adapter_id` (how it is implemented), and `handler_name` (the concrete handling entry point), or imply arbitrary command execution.

Explicitly disallowed as `executor_type` values:
- `skill`
- `cli`
- `file`
- `browser`
- `database`

Reasons:
- `executor_type` represents who is responsible
- Tools, environments, and interfaces are capability implementation details, not core task executor types
- tmux-managed Codex integration and OpenAI-compatible textual execution are bounded integration paths supported by the current implementation

## Relationship Summary

- A `Task` has multiple `TaskMessage` records
- A `Task` has multiple `TaskRevision` records
- A `Task` has multiple `Step` records
- A `Step` has multiple `StepRun` records
- A `StepRun` has multiple `CapabilityInvocation` records
- `Approval` can be associated with a `Task`, `Step`, or `StepRun`
- `Artifact` can be associated with a `Task`, `Step`, `StepRun`, or `CapabilityInvocation`
- `Event` records key changes throughout the lifecycle
- `StepComparisonGroup` manages comparison and selection among parallel variants
- A `Task` can be linked by at most one `WbsNode`; WBS ownership remains separate from execution ownership
- A WBS root contains nodes, milestones, same-root dependencies, and immutable change proposals
