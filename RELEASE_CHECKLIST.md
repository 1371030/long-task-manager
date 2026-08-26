# Release Checklist 0.2.0

## Version

- [x] Backend FastAPI version is `0.2.0`.
- [x] `/health` returns `version=0.2.0`.
- [x] Planner user agent reports `0.2.0`.
- [x] Frontend package and root lockfile versions are `0.2.0`.
- [x] Release notes exist for `0.2.0`.
- [x] Changelog includes `0.2.0`.

## Recursive progress reviews

- [x] Review snapshots persist expected, actual, variance, classification, evidence, and suggestions.
- [x] Reviews link recursively and remain immutable after later workflow changes.
- [x] The inclusive ±5-point range is classified as `on_track`.
- [x] Each review accepts one explicit `keep_plan` or `adjust_plan` decision.
- [x] Decisions and suggestions do not automatically mutate workflow state.
- [x] Latest review details and reverse-chronological history are available in the task UI.
- [x] English and Simplified Chinese product, API, domain, demo, and roadmap documentation are synchronized.

## Validation

- [x] Full backend pytest suite passes.
- [x] Frontend production build passes.
- [x] `scripts/demo_flow.sh` passes shell syntax validation and its live API run.
- [x] Browser golden-path and responsive checks pass.
- [x] A running backend returns the expected `0.2.0` health payload.
- [x] Version consistency, bilingual documentation checks, and `git diff --check` pass.
- [x] GitNexus change detection matches the intended symbols and execution flows.

## Release

- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.2.0` is pushed.
- [ ] GitHub Release `Long Task Manager v0.2.0` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
