# Release Checklist 0.1.2

## Version

- [x] Backend FastAPI version is `0.1.2`.
- [x] `/health` returns `version=0.1.2`.
- [x] Planner user agent reports `0.1.2`.
- [x] Frontend package and root lockfile versions are `0.1.2`.
- [x] Release notes exist for `0.1.2`.
- [x] Changelog includes `0.1.2`.

## Future roadmap

- [x] English and Simplified Chinese future roadmap documents exist.
- [x] Reciprocal language navigation resolves.
- [x] Both README files link to the matching roadmap language.
- [x] The historical MVP roadmap remains separate from the future roadmap.
- [x] Proposed v0.2-v0.8 items are marked as future plans, not implemented capabilities.
- [x] Hard workflow rules are distinguished from soft, explainable guidance.

## Validation

- [x] Backend pytest suite passes.
- [x] Frontend production build passes.
- [x] `scripts/demo_flow.sh` passes shell syntax validation.
- [x] A running backend returns the expected `0.1.2` health payload.
- [x] Roadmap links and Markdown formatting pass validation.
- [x] Version consistency and `git diff --check` pass.

## Release

- [ ] Release commit is pushed to `main`.
- [ ] Annotated tag `v0.1.2` is pushed.
- [ ] GitHub Release `Long Task Manager v0.1.2` is published.
- [ ] `HEAD`, `origin/main`, the tag, and the GitHub Release reference the same commit.
