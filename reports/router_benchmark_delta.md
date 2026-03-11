# Router Benchmark Delta

- baseline_source: `step3b1 (commit 9b8de79 baseline run)`
- candidate_source: `step3b2 deterministic router upgrade`
- generated_at_utc: `2026-03-11T03:23:00+00:00`

## Metrics

| metric | before | after | delta |
| --- | ---: | ---: | ---: |
| raw_route_accuracy | 0.1000 | 0.4500 | +0.3500 |
| normalized_route_accuracy | 0.4900 | 0.7800 | +0.2900 |
| normalized_macro_f1 | 0.3802 | 0.8021 | +0.4219 |
| normalized_correct_predictions | 49/100 | 78/100 | +29 |
| mismatches | 51 | 22 | -29 |

## Dead Routes

- before: `case_cross_compare`, `cross_law_compare`, `negative_or_unanswerable`
- after: `none`

## Top Confusion Pairs (Before)

- `case_cross_compare -> case_outcome_or_value`: 15
- `cross_law_compare -> law_scope_or_definition`: 13
- `law_relation_or_history -> law_scope_or_definition`: 7

## Top Confusion Pairs (After)

- `law_relation_or_history -> cross_law_compare`: 10
- `law_article_lookup -> cross_law_compare`: 5
- `law_relation_or_history -> law_scope_or_definition`: 3
- `law_article_lookup -> law_scope_or_definition`: 2

## Notes

- Dead routes were activated via deterministic runtime precedence rules and stronger cross-case/cross-law/negative signal detection.
- Benchmark normalization remains unchanged (`benchmark_route_normalization.v2`), with no benchmark-side question-text rerouting.
