# Release Notes 0.1.1

Long Task Manager 0.1.1 is a maintenance release that aligns public terminology and version metadata with the current implementation.

## What changed

- Public documentation now describes the optional executor as a **tmux-managed Codex executor**.
- The documentation clarifies that tmux manages persistent sessions while Codex CLI performs execution.
- English and Simplified Chinese documents use matching terminology and reciprocal language navigation.
- Backend metadata, the planner user agent, frontend package metadata, and health examples now report `0.1.1`.

## Execution boundary

The current CLI execution path is specific to Codex:

- `executor_mode=codex` selects the Codex path.
- tmux manages the persistent Codex session.
- Codex-specific flags, hooks, callbacks, configuration, and prompt templates remain unchanged.

This release does **not** add Claude execution, generic CLI-agent execution, or a pluggable executor architecture. The OpenAI-compatible executor remains a separate text-only workflow path.

## Validation

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
cd ..
npm run build --prefix frontend
bash -n scripts/demo_flow.sh
```

The backend is also started locally to verify that `/health` returns:

```json
{
  "status": "ok",
  "version": "0.1.1"
}
```

## Compatibility

This release does not change API routes, request or response schemas, database models, Codex callback protocols, or executor configuration names.
