# Release Checklist 0.4.0

## Version

- [x] Backend FastAPI version is `0.4.0`.
- [x] `/health` returns `version=0.4.0`.
- [x] Planner user agent reports `0.4.0`.
- [x] Frontend package and root lockfile versions are `0.4.0`.
- [x] Release notes exist for `0.4.0`.
- [x] Changelog includes `0.4.0`.

## Estimate and buffer scope

- [x] Estimate categories are explicit, normalized, and never inferred from titles.
- [x] Historical estimates use final accepted runs only, require at least three samples, and expose nearest-rank p20/median/p80.
- [x] Manual three-point revisions are immutable, use optimistic revision checks, and take precedence over historical evidence.
- [x] Decimal hours are converted once and persisted as integer milliseconds; PERT determines expected duration.
- [x] Actual duration uses approved selected-mainline runs with hierarchy-aware Task/Step deduplication.
- [x] Duration-weighted `schedule.node_ids` is separate from the unchanged node-count WBS `critical_path`.
- [x] RSS project and feeding buffers expose nonnegative consumption plus distinct zero/unavailable semantics.
- [x] Estimate GET is read-only, creates no event, and does not mutate execution state or WBS structure.

## Documentation and UI

- [x] English and Simplified Chinese README, API, domain, demo, and roadmap documents are synchronized.
- [x] Time guidance UI exposes sources, evidence, revisions, paths, buffers, and assumptions.
- [x] Security guidance and non-goals remain documented.
- [x] Deadlines, calendars, resource scheduling, automatic reordering, LLM critical-path reasoning, and cross-root dependencies remain out of scope.

## Validation

- [x] Focused estimate/buffer and migration backend tests pass.
- [x] Full backend pytest suite passes.
- [x] Frontend production build passes.
- [x] Desktop and 390px browser checks pass without horizontal overflow or console errors.
- [x] `scripts/demo_flow.sh` passes shell syntax validation.
- [x] `scripts/demo_flow.sh` passes live API validation.
- [x] Version consistency, bilingual links/code fences, and `git diff --check` pass.
- [x] GitNexus change detection matches the intended symbols and execution flows.

## Release

- [x] Local release commit is created.
- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.4.0` is pushed.
- [ ] GitHub Release `Long Task Manager v0.4.0` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
