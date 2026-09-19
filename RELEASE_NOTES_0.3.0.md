# Release Notes 0.3.0

Long Task Manager 0.3.0 adds an independent Work Breakdown Structure (WBS) planning layer while preserving the existing Task, Step, StepRun, approval, and auto-run behavior.

## Highlights

- Build multi-level WBS trees with stable depth-first ordering.
- Optionally link each WBS node to one execution Task without making WBS nodes executable.
- Roll up progress from active direct children without double-counting descendants.
- Record milestone titles and completion criteria; milestone status is read-only and derived from the owning node.
- Add same-tree dependencies with cycle validation, blocked-state reporting, and a longest unfinished dependency-chain hint.
- Review child and dependency changes as immutable draft proposals before they affect the tree.
- Reject stale approvals through optimistic root-version checks.
- Inspect WBS progress, milestones, dependencies, snapshots, decisions, and audit events in the task-detail UI.

## API and data

The release adds `wbs_nodes`, `wbs_milestones`, `wbs_dependencies`, and `wbs_change_proposals`. Existing SQLite databases are upgraded through idempotent startup schema and index creation.

New endpoints cover initial root creation, tree reads, milestone criteria, child and dependency proposals, proposal history, and approve/reject decisions. Existing task-detail and execution response shapes remain unchanged.

## Validation

- 97 backend tests pass, including 10 focused WBS tests.
- The Next.js production build passes.
- Desktop and 390px browser validation covers the WBS tree, blocked dependencies, milestones, draft proposals, and horizontal overflow.

## Intentional exclusions

This release does not add time estimates, deadlines, project buffers, resource calendars, automatic reordering, LLM critical-path reasoning, cross-root dependencies, or automatic milestone-criteria evaluation.

The service still has no authentication or authorization. Do not expose it directly to an untrusted network, and use Codex mode only with trusted project directories.
