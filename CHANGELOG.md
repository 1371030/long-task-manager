# Changelog

## 0.2.1 - Installation and running documentation

Patch release making local installation, configuration, startup, restart, and verification steps directly actionable for new users.

### Changed

- Expanded the English and Simplified Chinese README files with prerequisites and repository setup.
- Added complete backend installation and startup instructions for macOS, Linux, and Windows PowerShell.
- Clarified the two-terminal development workflow, automatic SQLite setup, service URLs, and manual mode without credentials.
- Added restart commands, local production-style frontend build instructions, optional tooling, and network safety boundaries.

## 0.2.0 - Recursive progress reviews

Minor release implementing the first transparent feedback loop from execution progress to an explicit planning decision.

### Added

- First-class immutable `TaskReview` records linked through `previous_review_id`.
- Manual expected-progress input and canonical actual-progress snapshots.
- Deterministic `ahead`, `on_track`, and `behind` classification using an inclusive ±5-point on-track range.
- Rule-based observations and suggestions derived from active steps and run history.
- One-time `keep_plan` or `adjust_plan` decisions with optional notes.
- Progress-review APIs, timeline events, task-log updates, and a latest-plus-history task-detail UI.
- Demo and regression coverage for variance boundaries, recursive history, immutable snapshots, workflow isolation, and failure paths.

### Boundaries

- Review analysis does not call an LLM.
- Suggestions do not automatically mutate tasks, steps, runs, or plans.
- The release does not add automatic review scheduling, time estimation, resource calendars, or project buffers.

## 0.1.2 - Future roadmap

Patch release documenting the proposed evolution of Long Task Manager beyond the current MVP.

### Added

- English and Simplified Chinese future roadmap documents.
- A three-layer architecture blueprint covering planning and strategy, execution and state management, and the data and knowledge foundation.
- Proposed v0.2-v0.8 phases for recursive reviews, WBS milestones, schedule buffers, resource bottlenecks, parallelism decisions, risk observability, and an optional focus workspace.

### Clarified

- Future roadmap items are proposals, not currently implemented capabilities or fixed delivery commitments.
- Hard workflow rules remain distinct from explainable planning and resource recommendations.

## 0.1.1 - tmux-managed Codex terminology

Patch release aligning public documentation and version metadata with the current execution architecture.

### Changed

- Describe the optional executor as a tmux-managed Codex executor, with tmux managing persistent sessions and Codex CLI performing execution.
- Clarify that Claude and generic CLI-agent execution are not implemented.
- Align the backend, planner user agent, frontend package metadata, and health examples at version `0.1.1`.
- Add and cross-link complete English and Simplified Chinese documentation sets.

### Validation

- Backend regression suite passes.
- Frontend production build passes.
- Demo script shell syntax and the running `/health` endpoint are verified.

## 0.1.0 - MVP Release Freeze

Initial Long Task Manager MVP release.

### Added

- Core `Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event` model.
- Direct task intake from the first user message with `status=intake`.
- Backend workflow APIs for task creation, task messages, plan generation, plan approval, step runs, run submission, run review, and rerun.
- Structured `current_pointer`, progress summary, and `next_actions` with explicit target IDs.
- Dynamic step operations: append, insert before/after, skip, supersede, reorder metadata, and progress recalculation.
- Parallel step variants: fork, clone subtree, compare variants, select a mainline variant, and abandon variants.
- Record-only capability invocation registry and invocation APIs using `capability_id`, `adapter_id`, and `handler_name`.
- Artifact and timeline event records, including capability-invocation-linked artifacts.
- Minimal Next.js UI for task intake, workflow operation, dynamic steps, variants, runs, review, artifacts, timeline, and capability invocation records.
- Repeatable `scripts/demo_flow.sh` API demo.

### Confirmed exclusions

- No Codex execution.
- No CLI execution or arbitrary shell execution.
- No Git or GitHub integration.
- No Source Workspace.
- No automatic source modification.
- No Temporal, deployment, multi-tenant auth, billing, or complex dashboard.
