# Router Benchmark Delta

- baseline_source: `step3d-pre (commit 9f25431 baseline run)`
- candidate_source: `step3d law-family disambiguation cleanup`
- generated_at_utc: `2026-03-11T05:12:00+00:00`

## Metrics

| metric | before | after | delta |
| --- | ---: | ---: | ---: |
| raw_route_accuracy | 0.4500 | 0.5300 | +0.0800 |
| normalized_route_accuracy | 0.7800 | 0.9200 | +0.1400 |
| normalized_macro_f1 | 0.8021 | 0.9158 | +0.1137 |
| normalized_correct_predictions | 78/100 | 92/100 | +14 |
| mismatches | 22 | 8 | -14 |

## Law-Family Focus

| metric | before | after | delta |
| --- | ---: | ---: | ---: |
| law_relation_or_history recall | 0.2353 | 0.8824 | +0.6471 |
| law_article_lookup recall | 0.7742 | 0.9355 | +0.1613 |
| cross_law_compare predicted | 36 | 17 | -19 |
| cross_law_compare support | 21 | 21 | 0 |

## Confusion Reduction

- `law_relation_or_history -> cross_law_compare`: `10 -> 0` (100% reduction)
- `law_article_lookup -> cross_law_compare`: `5 -> 0` (100% reduction)

## Top Confusion Pairs (After)

- `cross_law_compare -> law_scope_or_definition`: 3
- `law_article_lookup -> law_scope_or_definition`: 2
- `cross_law_compare -> law_relation_or_history`: 1
- `law_relation_or_history -> law_article_lookup`: 1
- `law_relation_or_history -> law_scope_or_definition`: 1

## Dead Routes

- before: `none`
- after: `none`

## Notes

- Cross-law compare now requires stronger explicit comparison framing.
- Provision-lookup (`article/section/...`) and lineage/history cues are protected from compare overfire.
- Benchmark normalization logic unchanged (`benchmark_route_normalization.v2`), no benchmark-side rerouting.
