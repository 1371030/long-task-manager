# Release Notes 0.1.0

Long Task Manager 0.1.0 freezes the MVP scope as a long-running task management system, not an automatic programming platform.

## Scope

The release manages task structure, execution attempts, approvals, artifacts, events, progress, and structured next actions.

Core model:

```text
Task → Step → StepRun → CapabilityInvocation → Approval → Artifact → Event
```

## Included phases

- Phase 1: task intake, steps, step runs, submission, approval, revision request, and rerun.
- Phase 2: dynamic step append, insert, skip, supersede, and progress recalculation.
- Phase 3: parallel step variants, subtree cloning, comparison, selection, and abandonment.
- Phase 4: record-only capability invocation registry and invocation records.
- Phase 5: release documentation and regression validation.

## Validation commands

```bash
cd backend
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pytest -q
cd ..
npm run build --prefix frontend
bash -n scripts/demo_flow.sh
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

## Known limitations

- Capability invocations are recorded only; no external capability is executed by this system.
- The demo script exercises the API golden path and the backend tests cover dynamic steps, variants, and capability records.
- The frontend is intentionally minimal and not a complex dashboard.
- There is no authentication, authorization, billing, deployment automation, Temporal workflow runtime, GitHub integration, Source Workspace, or automatic source modification.

## Non-goals confirmed

This release does not implement Codex calls, direct CLI execution, arbitrary shell execution, Git/GitHub integration, Source Workspace, automatic programming, deployment, multi-tenancy, billing, or complex dashboards.
