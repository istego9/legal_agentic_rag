# Score Deltas (Scorer Truth Pack)

Date: 2026-03-10

## Objective
- Make scorer regression the authoritative gate for score-impacting changes.

## Action Items
- [x] Add regression checks for answer schema validity by `answer_type`.
- [x] Add regression checks for canonical used source page IDs (`pdf_id_page`).
- [x] Add regression checks for telemetry completeness contract.
- [x] Add regression checks for allowed no-answer form.
- [x] Publish readable scorer summary markdown from regression flow.
- [x] Add one local scorer regression command that runs the suite and writes summary artifact.
- [x] Keep checks route-agnostic by wiring validation into scorer engine, not route handlers.

## Local Commands
- Scorer regression command:
  - `.venv/bin/python scripts/scorer_regression.py`
- Strict repository verify:
  - `python scripts/agentfirst.py verify --strict`

## Artifact
- Summary markdown is generated at:
  - `reports/scorer_regression_summary.md`

## Included Checks In Summary
- `no_answer_precision`
- `no_answer_recall`
- `telemetry_factor`
- `telemetry_completeness_rate`
- `answer_schema_valid_rate`
- `source_page_id_valid_rate`
- `no_answer_form_valid_rate`
- `contract_pass_rate` (legacy alias of competition contract pass rate)
- `competition_contract_pass_rate`
- `invalid_prediction_count`

## Step 2a Strict Gate Semantics
- Strict mode enablement:
  - `STRICT_COMPETITION_CONTRACTS=1` (explicit)
  - if not set, strict mode follows `COMPETITION_MODE=1`
- Blocking contract failures:
  - answer schema invalid
  - source page id invalid or non-canonical
  - telemetry contract invalid
  - no-answer form invalid
- Contract severity model is currently single-level (`blocking_only.v1`):
  - all current contract issues are blocking
  - `contract_checks` expose `blocking_failures` and `competition_contract_valid`
  - no advisory warning bucket is emitted until a real advisory policy exists
- In strict mode:
  - invalid predictions are marked with `prediction_valid_for_competition=false`
  - per-question `overall_score` is forced to `0.0`
  - run-level `overall_score` is gated by `competition_contract_pass_rate`
  - submission export fails closed on preflight contract failures

## Local Strict Preflight Run
- `STRICT_COMPETITION_CONTRACTS=1 PYTHONPATH=apps/api/src:. .venv/bin/python -m pytest tests/scorer_regression tests/integration/test_api_e2e.py -k strict -q`
