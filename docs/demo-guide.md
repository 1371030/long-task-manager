# MVP Demo Guide

This guide runs the Phase 1C end-to-end demo for Long Task Manager.

The demo verifies the MVP API golden path:

1. Create a task.
2. Add a follow-up task message.
3. Generate a plan with steps.
4. Approve the plan.
5. Start a `StepRun`.
6. Submit the run result.
7. Approve the submitted run.
8. Read progress, current pointer, structured next actions, timeline events, and artifacts.

Dynamic steps, parallel variants, and capability invocation records are covered by backend regression tests and the minimal frontend UI.

## Start the backend

Backend requires Python 3.11+. Do not use a Python 3.9 virtual environment.

From the project root:

```bash
cd backend
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

Or, if your Python 3.11 virtual environment is already active:

```bash
cd backend
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

The backend exposes:

```http
GET /health
```

Expected response:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## Start the frontend

In another terminal:

```bash
cd frontend
npm run dev
```

The frontend reads the backend URL from `NEXT_PUBLIC_API_BASE_URL` and defaults to:

```text
http://127.0.0.1:8000
```

Example:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

## Run the API demo script

The demo script uses `API_BASE_URL` and defaults to:

```text
http://127.0.0.1:8000
```

Run from the project root:

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

The script requires `jq`. It checks `/health` before running the workflow and exits non-zero on any failed step or failed assertion.

## What the demo proves

The demo proves that the MVP can run a complete managed workflow through the backend API:

- task intake
- conversational task updates
- plan generation
- plan approval
- step listing
- step run creation
- run submission
- run approval
- progress calculation
- structured `current_pointer`
- structured `next_actions` with target ids
- timeline retrieval
- artifacts retrieval, including the valid empty-list state

The full release also includes dynamic step operations, parallel step variants, and record-only capability invocation APIs. Those are validated by the backend test suite and surfaced in the minimal frontend.

## Current exclusions

The MVP intentionally does not include:

- Codex calls
- actual capability execution
- direct CLI execution
- Git or GitHub operations
- Source Workspace
- automatic source code modification
- Temporal
- deployment
- complex dashboards
- authentication or authorization systems
