# v0.4 Demo Guide

English | [简体中文](demo-guide.zh-CN.md)

This guide runs the Long Task Manager v0.4 end-to-end manual API demo. The script uses no sleeps and does not require an external model or executor.

## Start the backend

Backend requires Python 3.11+. From the project root:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8000
```

If a Python 3.11+ environment is already active, omit the environment creation and activation steps.

Verify:

```http
GET /health
```

```json
{
  "status": "ok",
  "version": "0.4.0"
}
```

## Run the demo

In another terminal, from the project root:

```bash
API_BASE_URL=http://127.0.0.1:8000 ./scripts/demo_flow.sh
```

The script requires `curl` and `jq`. It exits non-zero on a failed request or assertion.

## Golden path

The demo:

1. Checks `/health` for version `0.4.0`.
2. Creates a task and independent WBS root.
3. Creates three atomic WBS nodes through child draft proposals and approval: a two-node main chain and a one-node feeding chain.
4. Creates both same-root dependencies through draft proposals and approval.
5. Creates deterministic immutable manual estimate revisions using Decimal hours, then verifies normalized category, revision number, source, and integer-millisecond persistence.
6. Generates and approves the normal execution plan, accepts one human run, and completes the existing progress-review flow.
7. Reads `GET /tasks/{task_id}/wbs/estimate-buffer` twice and asserts stable output, the duration-weighted main and feeding paths, nonnegative project/feeding buffers, source, and WBS version.
8. Reads WBS, task detail, and timeline before and after the estimate GET to prove that it does not mutate execution or structure and does not emit events.
9. Prints a compact JSON summary.

The fixed manual samples make the expected PERT values and RSS buffers deterministic. Historical p20/median/p80 behavior and the minimum-three accepted-run threshold are covered by backend regression tests; the demo deliberately uses manual precedence so it remains quick and does not manufacture timestamp-based histories.

## Semantics demonstrated

- Estimate categories are explicit and normalized; no title-based similarity is inferred.
- Only final accepted approved runs can contribute historical or actual evidence.
- Manual three-point revisions are immutable and take precedence over history until a later revision clears the manual values.
- Decimal input hours are persisted and returned as integer milliseconds.
- PERT supplies expected duration; historical evidence uses nearest-rank p20/median/p80 after at least three samples.
- Hierarchy-aware approved-mainline actuals deduplicate Task and Step contributions.
- `schedule.node_ids` is a duration-weighted main chain. Existing `critical_path` remains the node-count-based unfinished-chain hint.
- Project and feeding buffers use RSS safety aggregation. Unavailable data and valid zero-buffer cases have distinct reasons/statuses; consumption values never become negative.
- Estimate GET is read-only.

## Intentional exclusions

v0.4 does not add deadlines, resource calendars, resource scheduling, automatic reordering, LLM critical-path reasoning, or cross-root dependencies. The demo also does not perform arbitrary capability, CLI, Git/GitHub, deployment, or source-modification operations.
