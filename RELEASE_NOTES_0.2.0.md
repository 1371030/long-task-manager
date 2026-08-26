# Release Notes 0.2.0

Long Task Manager 0.2.0 introduces manual recursive progress reviews: an explainable feedback loop that compares a user-entered expected completion percentage with the system's canonical actual progress and records an explicit planning decision.

## What changed

- Added first-class immutable `TaskReview` records linked through `previous_review_id`.
- Added manual expected-progress input and automatic actual-progress snapshots.
- Added variance classification:
  - greater than `+5` percentage points: `ahead`;
  - less than `-5` percentage points: `behind`;
  - inclusive `-5` through `+5`: `on_track`.
- Added deterministic observations and suggestions based on active step states, run states, retries, dynamic scope, and blocked task state.
- Added one-time `keep_plan` and `adjust_plan` decisions with optional notes.
- Added task timeline and task-log events for review creation and decisions.
- Added a task-detail UI showing the latest review, immutable evidence, suggestions, a decision form, and reverse-chronological history.
- Extended the repeatable API demo and backend regression tests.
- Updated English and Simplified Chinese product, API, domain model, demo, and roadmap documentation.

## API additions

```text
POST /tasks/{task_id}/progress-reviews
GET  /tasks/{task_id}/progress-reviews
POST /tasks/{task_id}/progress-reviews/{review_id}/decision
```

Progress reviews can be created for tasks in `planned`, `running`, `waiting_review`, `needs_revision`, `blocked`, `failed`, or `completed`. The latest review must be decided before another review can be created, and each review can be decided only once.

## Deliberate boundaries

- Review analysis is rule-based and does not call an LLM.
- Suggestions are transparent references to existing workflow operations and are never applied automatically.
- `adjust_plan` records intent only; it does not modify task status, steps, runs, or the plan.
- This release does not add automatic review scheduling, planned durations, deadlines, resource calendars, project buffers, or schedule prediction.

## Compatibility

The release adds a new SQLite table through existing startup metadata creation. It does not rename existing routes or change existing progress semantics. Existing task, step, run, approval, artifact, and capability invocation APIs remain available.

## Validation

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
cd ..
npm run build --prefix frontend
bash -n scripts/demo_flow.sh
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

A running backend should report version `0.2.0` from `/health`.
