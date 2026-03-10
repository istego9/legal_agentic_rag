# tests/scorer_regression

Deterministic and policy-versioned scorer regression suites.

Coverage:
- scoring policy fallback resolution (`requested` -> `default/available`)
- policy-driven grounding (`beta`) and TTFT factor curves
- telemetry policy behavior (`run_level_factor` vs `all_or_nothing`)
- stable eval metric slices for compare/leaderboard (`by_answer_type`, `by_route_family`)
- response contract checks:
  - answer schema validity by `answer_type`
  - canonical `source_page_id` validation (`pdf_id_page`)
  - telemetry completeness contract checks
  - allowed no-answer form checks
- readable scorer summary markdown (`scorer_summary.markdown`)

Local command:
- `PYTHONPATH=apps/api/src:. .venv/bin/python -m pytest tests/scorer_regression -q`
