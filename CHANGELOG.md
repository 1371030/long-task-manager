# Changelog

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
