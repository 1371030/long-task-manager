# Release Notes 0.1.2

Long Task Manager 0.1.2 is a documentation and planning release that introduces a bilingual future roadmap while keeping the implemented scope unchanged.

## What changed

- Added `docs/future-roadmap.md` and `docs/future-roadmap.zh-CN.md`.
- Added links to the future roadmap from both README files.
- Documented a three-layer long-term architecture:
  - planning and strategy engine;
  - execution and state management;
  - data and knowledge foundation.
- Proposed staged evolution from v0.2 through v0.8.
- Aligned backend, planner user agent, frontend package metadata, and health examples at version `0.1.2`.

## Proposed roadmap

- v0.2: recursive reviews and progress variance
- v0.3: WBS task trees and milestones
- v0.4: time estimates and project buffers
- v0.5: resource calendars, skills, and bottlenecks
- v0.6: parallelism and rework decisions
- v0.7: progress heatmaps and risk observability
- v0.8: optional focus workspace

These items are proposals rather than implemented features or fixed delivery commitments. The current implementation remains the source of truth for supported behavior.

## Compatibility

This release does not change API routes, schemas, database models, executor behavior, callbacks, or configuration names.

## Validation

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
cd ..
npm run build --prefix frontend
bash -n scripts/demo_flow.sh
```

The backend is also started locally to confirm that `/health` reports version `0.1.2`.
