# Release Notes 0.2.1

Long Task Manager 0.2.1 is a documentation-focused patch release that makes installation and local operation easier to follow from a fresh checkout.

## What changed

- Added explicit Git, Python, Node.js, npm, and optional tool prerequisites.
- Added repository clone and project-directory instructions.
- Expanded backend setup for macOS, Linux, and Windows PowerShell.
- Documented automatic SQLite database creation and backend verification URLs.
- Clarified frontend installation and the two-terminal development workflow.
- Added stop, restart, and production-style frontend build commands.
- Clarified that manual mode requires no API credentials.
- Retained explicit warnings against exposing the unauthenticated services to untrusted networks.

## Compatibility

This release changes documentation and version metadata only. It does not change APIs, database schemas, workflow semantics, or executor behavior.

## Validation

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
cd ..
npm run build --prefix frontend
bash -n scripts/demo_flow.sh
```

A running backend should report version `0.2.1` from `/health`.
