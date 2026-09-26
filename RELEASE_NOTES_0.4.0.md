# Release Notes 0.4.0

Long Task Manager 0.4.0 adds explainable time estimates and schedule buffers to the independent WBS planning layer without changing execution order, commitments, or the existing node-count critical-path hint.

## Highlights

- Assign explicit estimate categories normalized with Unicode NFKC, trimming, case folding, and whitespace collapse.
- Derive historical estimates only from final accepted runs in the same category, with a minimum of three samples and nearest-rank p20/median/p80.
- Record immutable manual three-point estimate revisions with optimistic revision checks and precedence over historical evidence.
- Accept Decimal hours and persist all estimate values as integer milliseconds.
- Compute expected duration with PERT and calculate approved-mainline actuals with hierarchy-aware Task/Step deduplication.
- Select a separate duration-weighted main chain while preserving the existing unfinished node-count `critical_path` semantics.
- Report RSS project and feeding buffers with explicit recommended, consumed, remaining, percentage, zero-buffer, and unavailable semantics.
- Inspect sources, evidence, revisions, paths, buffers, exclusions, and assumptions through the API and task-detail UI.

## API and data

The release adds immutable `wbs_estimate_revisions`, an explicit `estimate_category` on steps, `POST /wbs/{node_id}/estimate-revisions`, and read-only `GET /tasks/{task_id}/wbs/estimate-buffer`.

Manual inputs are ordered three-point Decimal hours. The server stores integer milliseconds and computes PERT expected duration. A later null-manual revision clears manual precedence without rewriting history. Historical evidence is accepted-only and requires at least three final accepted samples with an explicit matching normalized category.

The estimate GET is deterministic and read-only: it creates no timeline event and does not mutate Task, Step, StepRun, WBS node, dependency, proposal, revision, or ordering state.

## Buffer semantics

Project and feeding buffers use root-sum-square aggregation of each covered node's nonnegative safety amount (`conservative_ms - expected_ms`). Consumption compares approved-mainline actual duration with expected duration. Valid zero buffers are `not_applicable` with a null percentage and explicit reason; unavailable inputs remain `unavailable` with null duration values and explicit exclusions.

## Intentional exclusions

This release does not add deadlines, calendars, resource scheduling, automatic reordering, LLM critical-path reasoning, or cross-root dependencies. Recommendations do not create runs, alter workflow status, or replace human commitments.

The service still has no authentication or authorization. Do not expose it directly to an untrusted network, and use Codex mode only with trusted project directories.
