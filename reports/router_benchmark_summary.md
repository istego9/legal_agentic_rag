# Router Benchmark Summary

- generated_at_utc: `2026-03-11T07:47:38.796116+00:00`
- public_dataset_path: `public_dataset.json`
- taxonomy_path: `datasets/taxonomy/public_question_taxonomy.v1.jsonl`
- benchmark_target: `services.runtime.router.resolve_route_decision`
- benchmark_mapping: `packages.router.benchmark_mapping.normalize_runtime_route_for_taxonomy`
- normalization_model_version: `benchmark_route_normalization.v2`
- total_questions: `100`
- raw_route_correct_predictions: `53`
- normalized_route_correct_predictions: `92`
- raw_route_accuracy: `0.5300`
- normalized_route_accuracy: `0.9200`
- normalized_macro_f1: `0.9158`

## Normalized Per-Route Precision/Recall/F1

| primary_route | support | predicted | precision | recall | f1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_outcome_or_value | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_cross_compare | 17 | 17 | 1.0000 | 1.0000 | 1.0000 |
| law_article_lookup | 31 | 30 | 0.9667 | 0.9355 | 0.9508 |
| law_relation_or_history | 17 | 16 | 0.9375 | 0.8824 | 0.9091 |
| law_scope_or_definition | 4 | 10 | 0.4000 | 1.0000 | 0.5714 |
| cross_law_compare | 21 | 17 | 1.0000 | 0.8095 | 0.8947 |
| negative_or_unanswerable | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |

## Predicted Count By Raw Runtime Route

| raw_runtime_route | predicted_count |
| --- | ---: |
| article_lookup | 40 |
| cross_case_compare | 17 |
| cross_law_compare | 17 |
| history_lineage | 16 |
| single_case_extraction | 6 |
| no_answer | 4 |

## Predicted Count By Normalized Taxonomy Route

| normalized_taxonomy_route | predicted_count |
| --- | ---: |
| case_entity_lookup | 3 |
| case_outcome_or_value | 3 |
| case_cross_compare | 17 |
| law_article_lookup | 30 |
| law_relation_or_history | 16 |
| law_scope_or_definition | 10 |
| cross_law_compare | 17 |
| negative_or_unanswerable | 4 |
| __unmapped__ | 0 |

## Confusion Matrix

| expected \\ predicted | case_entity_lookup | case_outcome_or_value | case_cross_compare | law_article_lookup | law_relation_or_history | law_scope_or_definition | cross_law_compare | negative_or_unanswerable | __unmapped__ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_outcome_or_value | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_cross_compare | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0 |
| law_article_lookup | 0 | 0 | 0 | 29 | 0 | 2 | 0 | 0 | 0 |
| law_relation_or_history | 0 | 0 | 0 | 1 | 15 | 1 | 0 | 0 | 0 |
| law_scope_or_definition | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| cross_law_compare | 0 | 0 | 0 | 0 | 1 | 3 | 17 | 0 | 0 |
| negative_or_unanswerable | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

## Top Confusion Pairs

- cross_law_compare -> law_scope_or_definition: 3
- law_article_lookup -> law_scope_or_definition: 2
- cross_law_compare -> law_relation_or_history: 1
- law_relation_or_history -> law_article_lookup: 1
- law_relation_or_history -> law_scope_or_definition: 1

## Dead Routes

- none

## Mismatches (8)

- [c595f1180b440f4e6ea5e130563fb4c2e9705557d3abf10e401948c0eb73b268] expected=law_relation_or_history raw_mapped=__unmapped__ normalized=law_article_lookup raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Which articles of Law No. 12 of 2004 are explicitly superseded by Law No. 16 of 2011, and what is the overarching theme of the content in Article 4 of Law No. 12 of 2004 that was superseded?
- [8d481702ddfb40310a070ac44f4a2e9637043f453afa0319cd83d20fd8ec607e] expected=cross_law_compare raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: What is the prescribed penalty for an offense against the Strata Title Law under the Strata Title Regulations, and what is the penalty for using leased premises for an illegal purpose under the Leasing Regulations?
- [54103603d632383a733ea81fe983eac4982a22bbd77f1e8a0daa333c249cd5c9] expected=cross_law_compare raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: How do the Limited Liability Partnership Law and the Non Profit Incorporated Organisations Law define their administration?
- [1107e2844571d4c05755c1607e1a847a54fc023777f8b4f87e2ac50d5256c3d8] expected=cross_law_compare raw_mapped=law_relation_or_history normalized=law_relation_or_history raw_runtime=history_lineage source=runtime_metadata.taxonomy_route :: What is the commencement date for the Data Protection Law 2020 and the Employment Law 2019?
- [46927f372acef1888a11ef8de5f7a1dff5588a85efc12eaafe7c7f59c5fbf14f] expected=cross_law_compare raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Does the term 'Law' in the Strata Title Regulations refer to the same law number as the 'Employment Law' mentioned in the Employment Regulations?
- [82664b585f15bcd8afa3bd6acf97c3fa415fcad7d60762d8ad80421418caf3f5] expected=law_relation_or_history raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: What is the full title of the enacted law?
- [6e3abab5157d5897a698c91d0c980646b14e5cc1e773e6c6537e918dcb26275e] expected=law_article_lookup raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Under the Common Reporting Standard Law 2018, is the Relevant Authority liable for acts or omissions in its performance of functions if the act or omission is shown to have been in bad faith?
- [73510f45df2f1b3f268f4fabc89e1b98690777acb78579beabb20801b34e3fc4] expected=law_article_lookup raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: According to the DIFC Non Profit Incorporated Organisations Law 2012, can an Incorporated Organisation undertake Financial Services as prescribed in the General Module of the DFSA Rulebook?
