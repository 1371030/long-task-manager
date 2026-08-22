# Release Checklist 0.1.1

## Version

- [x] Backend FastAPI version is `0.1.1`.
- [x] `/health` returns `version=0.1.1`.
- [x] Planner user agent reports `0.1.1`.
- [x] Frontend package and root lockfile versions are `0.1.1`.
- [x] Release notes exist for `0.1.1`.
- [x] Changelog includes `0.1.1`.

## Executor terminology

- [x] Public documentation describes a tmux-managed Codex executor.
- [x] tmux is identified as the persistent session manager.
- [x] Codex CLI is identified as the current CLI executor.
- [x] No Claude or generic CLI-agent support is claimed.
- [x] Existing `codex_*` configuration and API identifiers remain unchanged.

## Documentation

- [x] English and Simplified Chinese README files use matching terminology.
- [x] Eight English documents have matching `.zh-CN.md` counterparts.
- [x] Reciprocal language links and local Markdown links resolve.
- [x] API paths, fields, statuses, and code examples remain aligned across languages.

## Validation

- [x] Backend pytest suite passes.
- [x] Frontend production build passes.
- [x] `scripts/demo_flow.sh` passes shell syntax validation.
- [x] A running backend returns the expected `0.1.1` health payload.
- [x] Version and terminology scans pass.
- [x] `git diff --check` passes.

## Release

- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.1.1` is pushed.
- [ ] GitHub Release `Long Task Manager v0.1.1` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
