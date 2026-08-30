# Release Checklist 0.2.1

## Version

- [x] Backend FastAPI version is `0.2.1`.
- [x] `/health` returns `version=0.2.1`.
- [x] Planner user agent reports `0.2.1`.
- [x] Frontend package and root lockfile versions are `0.2.1`.
- [x] Release notes exist for `0.2.1`.
- [x] Changelog includes `0.2.1`.

## Documentation

- [x] English and Simplified Chinese installation instructions are synchronized.
- [x] Prerequisites and repository setup are documented.
- [x] Backend installation covers macOS, Linux, and Windows PowerShell.
- [x] Frontend development and production-style startup commands are documented.
- [x] Restart, verification, optional configuration, and security guidance are documented.

## Validation

- [x] Full backend pytest suite passes.
- [x] Frontend production build passes.
- [x] `scripts/demo_flow.sh` passes shell syntax validation.
- [x] Version consistency, bilingual documentation checks, and `git diff --check` pass.
- [x] GitNexus change detection matches the intended symbols and execution flows.

## Release

- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.2.1` is pushed.
- [ ] GitHub Release `Long Task Manager v0.2.1` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
