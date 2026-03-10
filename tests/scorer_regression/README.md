# tests/scorer_regression

Deterministic and policy-versioned scorer regression suites.

Coverage:
- scoring policy fallback resolution (`requested` -> `default/available`)
- policy-driven grounding (`beta`) and TTFT factor curves
- telemetry policy behavior (`run_level_factor` vs `all_or_nothing`)
- stable eval metric slices for compare/leaderboard (`by_answer_type`, `by_route_family`)
