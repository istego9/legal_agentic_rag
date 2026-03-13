# Router Benchmark Summary

- generated_at_utc: `2026-03-13T16:40:08.609560+00:00`
- public_dataset_path: `datasets/official_fetch_2026-03-11/questions.json`
- taxonomy_path: `datasets/taxonomy/public_question_taxonomy.v1.jsonl`
- benchmark_target: `services.runtime.router.resolve_route_decision`
- benchmark_mapping: `packages.router.benchmark_mapping.normalize_runtime_route_for_taxonomy`
- normalization_model_version: `benchmark_route_normalization.v2`
- total_questions: `100`
- raw_route_correct_predictions: `39`
- normalized_route_correct_predictions: `100`
- raw_route_accuracy: `0.3900`
- normalized_route_accuracy: `1.0000`
- normalized_macro_f1: `0.8750`

## Normalized Per-Route Precision/Recall/F1

| primary_route | support | predicted | precision | recall | f1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |
| case_outcome_or_value | 12 | 12 | 1.0000 | 1.0000 | 1.0000 |
| case_cross_compare | 31 | 31 | 1.0000 | 1.0000 | 1.0000 |
| law_article_lookup | 34 | 34 | 1.0000 | 1.0000 | 1.0000 |
| law_relation_or_history | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |
| law_scope_or_definition | 11 | 11 | 1.0000 | 1.0000 | 1.0000 |
| cross_law_compare | 0 | 0 | 0.0000 | 0.0000 | 0.0000 |
| negative_or_unanswerable | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |

## Predicted Count By Raw Runtime Route

| raw_runtime_route | predicted_count |
| --- | ---: |
| article_lookup | 45 |
| cross_case_compare | 31 |
| single_case_extraction | 16 |
| history_lineage | 4 |
| no_answer | 4 |

## Predicted Count By Normalized Taxonomy Route

| normalized_taxonomy_route | predicted_count |
| --- | ---: |
| case_entity_lookup | 4 |
| case_outcome_or_value | 12 |
| case_cross_compare | 31 |
| law_article_lookup | 34 |
| law_relation_or_history | 4 |
| law_scope_or_definition | 11 |
| cross_law_compare | 0 |
| negative_or_unanswerable | 4 |
| __unmapped__ | 0 |

## Confusion Matrix

| expected \\ predicted | case_entity_lookup | case_outcome_or_value | case_cross_compare | law_article_lookup | law_relation_or_history | law_scope_or_definition | cross_law_compare | negative_or_unanswerable | __unmapped__ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_outcome_or_value | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_cross_compare | 0 | 0 | 31 | 0 | 0 | 0 | 0 | 0 | 0 |
| law_article_lookup | 0 | 0 | 0 | 34 | 0 | 0 | 0 | 0 | 0 |
| law_relation_or_history | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| law_scope_or_definition | 0 | 0 | 0 | 0 | 0 | 11 | 0 | 0 | 0 |
| cross_law_compare | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| negative_or_unanswerable | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

## Top Confusion Pairs

- none

## Dead Routes

- none

## Mismatches (0)

- none
