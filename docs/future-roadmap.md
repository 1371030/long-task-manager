# Future Roadmap

English | [简体中文](future-roadmap.zh-CN.md)

This document describes the proposed evolution of Long Task Manager after the current MVP. It is a planning document, not a promise that these capabilities already exist or will be delivered on a fixed schedule.

## Long-Term Architecture

The long-term direction is organized around three layers:

```text
Planning and Strategy Engine
            ↓
Execution and State Management
            ↓
Data and Knowledge Foundation
```

### Planning and Strategy Engine

The planning layer should translate long-term goals into executable, reviewable structures.

Potential capabilities:

- Work Breakdown Structure (WBS) for multi-level task trees
- Milestones and explicit completion criteria
- Time estimation based on historical execution data
- Project and feeding buffers for absorbing schedule variance
- Priority recalculation after review and progress feedback

### Execution and State Management

The execution layer should turn plans into durable actions while preserving human control and recoverability.

Potential capabilities:

- Periodic recursive reviews that compare the original goal with current progress
- Resource-aware scheduling and bottleneck warnings
- Parallelism recommendations based on dependencies, capacity, and rework probability
- Approval gates for high-impact transitions
- Explainable recommendations instead of opaque automatic reprioritization

### Data and Knowledge Foundation

The foundation should make execution history useful for future planning.

Potential capabilities:

- Planned versus actual duration for tasks and steps
- Resource calendars and skill profiles
- Delay reasons, review outcomes, and rework history
- Project-level memory and retrospective records
- Health, risk, and buffer-consumption metrics

## Proposed Evolution

### v0.2 — Recursive Reviews and Progress Variance (delivered)

**Goal:** Close the first feedback loop from execution history back into planning.

Delivered scope:

- Manually created task progress reviews with a user-entered expected percentage
- Canonical actual-progress snapshots and `ahead`, `on_track`, or `behind` classification using a ±5-point threshold
- Deterministic evidence and suggestions derived from step and run history
- Recursive history through `previous_review_id`
- One explicit `keep_plan` or `adjust_plan` decision per review
- Timeline and task-log audit events

The first release intentionally does not schedule reviews, estimate time, call an LLM for analysis, or automatically apply suggestions. Those require additional planning, scheduling, and approval semantics.

### v0.3 — WBS Task Trees and Milestones

**Goal:** Extend the step graph into a multi-level work breakdown structure.

Potential scope:

- Parent and child task relationships
- Milestones with completion criteria
- Roll-up progress from child tasks to parent tasks
- Task-level dependencies and critical-path hints
- Reviewable changes to the task tree

**Prerequisite:** Define how task trees relate to the current `Task` and `Step` models without duplicating ownership or approval semantics.

### v0.4 — Time Estimates and Project Buffers

**Goal:** Make schedule variance visible and manageable instead of hiding it in fixed due dates.

Potential scope:

- Historical duration distributions for similar tasks
- Conservative and aggressive estimates
- Project and feeding buffers
- Buffer-consumption reporting
- Schedule recommendations based on observed variance

**Principle:** Estimation should begin as an explainable recommendation. It should not silently override user commitments or create false precision.

### v0.5 — Resource Calendars, Skills, and Bottlenecks

**Goal:** Match work to suitable capacity rather than assigning every task to whoever appears idle.

Potential scope:

- Resource availability calendars
- Skill and proficiency profiles
- Workload and utilization summaries
- Bottleneck warnings when capacity is constrained
- Suggested reassignment or sequencing changes

**Principle:** Start with visibility and recommendations. Automatic reassignment should require explicit approval.

### v0.6 — Parallelism and Rework Decisions

**Goal:** Help users choose between fully parallel and partially serialized execution.

Potential scope:

- Dependency-aware parallelism analysis
- Capacity-aware completion-time estimates
- Rework-probability signals
- Comparison of parallel and serialized plans
- Human-approved changes to execution strategy

This phase builds on the current parallel step variants and comparison groups rather than replacing them.

### v0.7 — Progress Heatmaps and Risk Observability

**Goal:** Make long-running work understandable at a glance.

Potential scope:

- Milestone health indicators
- Risk and delay heatmaps
- Step, task, and project trend views
- Buffer and workload visualizations
- Explainable status transitions and recommended next actions

The UI should show why an item is healthy, at risk, or delayed rather than relying on color alone.

### v0.8 — Focus Workspace

**Goal:** Support individual execution without turning the system into a notification-heavy productivity suite.

Potential scope:

- A focused execution workspace for the active step
- Optional focus timers or Pomodoro-style sessions
- Suppression of non-urgent in-app notifications
- Clear boundaries between focus state and workflow state

Focus features should remain optional and should never hide urgent approval, failure, or security events.

## Hard Rules and Soft Guidance

The system should combine enforceable workflow rules with explainable recommendations.

### Hard rules

- Approval requirements for defined transitions
- Dependency constraints
- Valid task, step, and run state transitions
- Preservation of historical runs and decisions
- Safety boundaries for external execution integrations

### Soft guidance

- Time and resource estimates
- Bottleneck warnings
- Priority suggestions
- Recursive review reminders
- Parallelism and rework recommendations

Recommendations should expose their inputs and reasoning so a person can accept, modify, or reject them.

## Non-Goals

This roadmap does not promise immediate support for:

- Claude execution or generic CLI-agent execution
- Unrestricted shell execution
- Multi-tenant identity and authorization
- Billing
- A full enterprise project-management suite
- Opaque autonomous reprioritization

The current implementation remains the source of truth for supported behavior. Future roadmap items should be promoted into an implemented scope only after their data model, API behavior, safety boundaries, tests, and user experience are defined.
