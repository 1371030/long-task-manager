# Release Checklist 0.3.0

## Version

- [x] Backend FastAPI version is `0.3.0`.
- [x] `/health` returns `version=0.3.0`.
- [x] Planner user agent reports `0.3.0`.
- [x] Frontend package and root lockfile versions are `0.3.0`.
- [x] Release notes exist for `0.3.0`.
- [x] Changelog includes `0.3.0`.

## WBS scope

- [x] WBS remains separate from Task/Step/StepRun execution and approval state machines.
- [x] Tree reads, direct-child roll-up, exclusions, dependencies, blocked state, and critical-path hints are covered.
- [x] Child and dependency changes require immutable draft proposals and one-time decisions.
- [x] Stale proposal approvals return a root-version conflict.
- [x] Milestone status is read-only and derived from the owning node.
- [x] Existing SQLite databases receive idempotent WBS schema/index setup.

## Documentation and UI

- [x] English and Simplified Chinese README, API, domain, demo, and roadmap documents are synchronized.
- [x] WBS UI covers empty state, tree, roll-up, milestones, dependencies, proposal snapshots, and decisions.
- [x] Timeline labels include WBS creation, milestone, proposal, approval, and rejection events.
- [x] Security guidance and non-goals remain documented.

## Validation

- [x] Focused WBS backend tests pass.
- [x] Full backend pytest suite passes.
- [x] Frontend production build passes.
- [x] Desktop and 390px browser checks pass without horizontal overflow or console errors.
- [ ] `scripts/demo_flow.sh` passes shell syntax and live API validation.
- [ ] Version consistency, bilingual links/code fences, and `git diff --check` pass.
- [ ] GitNexus change detection matches the intended symbols and execution flows.

## Release

- [ ] Local release commit is created.
- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.3.0` is pushed.
- [ ] GitHub Release `Long Task Manager v0.3.0` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
