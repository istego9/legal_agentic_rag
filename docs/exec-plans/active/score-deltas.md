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
- `contract_pass_rate`
