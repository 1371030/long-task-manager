# Release Checklist 0.1.0

## Version

- [x] Backend FastAPI version is `0.1.0`.
- [x] `/health` returns `version=0.1.0`.
- [x] Frontend package version is `0.1.0`.
- [x] Release notes exist for `0.1.0`.
- [x] Changelog includes `0.1.0`.

## Environment

- [x] Backend requires Python 3.11+.
- [x] Backend local venv is created with `python3.11 -m venv .venv` from `backend/`.
- [x] Backend tests run with `python -m pytest -q` from an active Python 3.11 virtual environment.

## Core model

- [x] Task is created directly from the first user message; no separate draft-task model is used.
- [x] Step represents a workflow phase.
- [x] StepRun represents one execution attempt.
- [x] Historical StepRuns are preserved.
- [x] CapabilityInvocation uses `capability_id`, `adapter_id`, and `handler_name`.
- [x] next_actions are structured objects with explicit target IDs.

## Phase coverage

- [x] Phase 1 task, step, run, approval, revision, and rerun flow.
- [x] Phase 2 dynamic step operations.
- [x] Phase 3 parallel variants and forked step branches.
- [x] Phase 4 record-only capability invocation records.
- [x] Phase 5 release documentation and regression pass.

## Validation

- [x] Backend pytest suite passes.
- [x] Frontend production build passes.
- [x] `scripts/demo_flow.sh` passes shell syntax validation.
- [x] `scripts/demo_flow.sh` passes against a running backend.
- [x] Forbidden terminology scan passes.

## Explicit non-goals

- [x] No Codex execution.
- [x] No CLI execution.
- [x] No arbitrary shell execution from the product.
- [x] No Git or GitHub integration.
- [x] No Source Workspace.
- [x] No automatic source modification.
- [x] No Temporal runtime.
- [x] No deployment automation.
- [x] No multi-tenant auth.
- [x] No billing.
- [x] No complex dashboard.
