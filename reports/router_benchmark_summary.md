# Router Benchmark Summary

- generated_at_utc: `2026-03-11T04:38:33.274690+00:00`
- public_dataset_path: `/Users/artemgendler/dev/legal_agentic_rag/public_dataset.json`
- taxonomy_path: `/Users/artemgendler/dev/legal_agentic_rag/datasets/taxonomy/public_question_taxonomy.v1.jsonl`
- benchmark_target: `services.runtime.router.resolve_route_decision`
- benchmark_mapping: `packages.router.benchmark_mapping.normalize_runtime_route_for_taxonomy`
- normalization_model_version: `benchmark_route_normalization.v2`
- total_questions: `100`
- raw_route_correct_predictions: `45`
- normalized_route_correct_predictions: `78`
- raw_route_accuracy: `0.4500`
- normalized_route_accuracy: `0.7800`
- normalized_macro_f1: `0.8021`

## Normalized Per-Route Precision/Recall/F1

| primary_route | support | predicted | precision | recall | f1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_outcome_or_value | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_cross_compare | 17 | 17 | 1.0000 | 1.0000 | 1.0000 |
| law_article_lookup | 31 | 24 | 1.0000 | 0.7742 | 0.8727 |
| law_relation_or_history | 17 | 4 | 1.0000 | 0.2353 | 0.3810 |
| law_scope_or_definition | 4 | 9 | 0.3333 | 0.7500 | 0.4615 |
| cross_law_compare | 21 | 36 | 0.5556 | 0.9524 | 0.7018 |
| negative_or_unanswerable | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |

## Predicted Count By Raw Runtime Route

| raw_runtime_route | predicted_count |
| --- | ---: |
| cross_law_compare | 36 |
| article_lookup | 33 |
| cross_case_compare | 17 |
| single_case_extraction | 6 |
| history_lineage | 4 |
| no_answer | 4 |

## Predicted Count By Normalized Taxonomy Route

| normalized_taxonomy_route | predicted_count |
| --- | ---: |
| case_entity_lookup | 3 |
| case_outcome_or_value | 3 |
| case_cross_compare | 17 |
| law_article_lookup | 24 |
| law_relation_or_history | 4 |
| law_scope_or_definition | 9 |
| cross_law_compare | 36 |
| negative_or_unanswerable | 4 |
| __unmapped__ | 0 |

## Confusion Matrix

| expected \\ predicted | case_entity_lookup | case_outcome_or_value | case_cross_compare | law_article_lookup | law_relation_or_history | law_scope_or_definition | cross_law_compare | negative_or_unanswerable | __unmapped__ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_outcome_or_value | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_cross_compare | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0 |
| law_article_lookup | 0 | 0 | 0 | 24 | 0 | 2 | 5 | 0 | 0 |
| law_relation_or_history | 0 | 0 | 0 | 0 | 4 | 3 | 10 | 0 | 0 |
| law_scope_or_definition | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 |
| cross_law_compare | 0 | 0 | 0 | 0 | 0 | 1 | 20 | 0 | 0 |
| negative_or_unanswerable | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

## Top Confusion Pairs

- law_relation_or_history -> cross_law_compare: 10
- law_article_lookup -> cross_law_compare: 5
- law_relation_or_history -> law_scope_or_definition: 3
- law_article_lookup -> law_scope_or_definition: 2
- cross_law_compare -> law_scope_or_definition: 1
- law_scope_or_definition -> cross_law_compare: 1

## Dead Routes

- none

## Mismatches (22)

- [c595f1180b440f4e6ea5e130563fb4c2e9705557d3abf10e401948c0eb73b268] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Which articles of Law No. 12 of 2004 are explicitly superseded by Law No. 16 of 2011, and what is the overarching theme of the content in Article 4 of Law No. 12 of 2004 that was superseded?
- [eeae1069cbbc9ef2fe66f063459ddac4c5ff5edef405593bb299aca715246b39] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: How does Law No. 1 of 2025 modify the application of the Data Protection Law 2020 as it pertains to processing Personal Data in the DIFC by a Controller or Processor, as originally outlined in the Data Protection Law 2020?
- [fb1de34d3ebe58b03c5e9898c2e29d1d8c6297fa570f0021967986e43b62da62] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Who has the authority to make the Dematerialised Investments Regulations (DIR), and what other laws are cited as conferring powers for these regulations?
- [170221727c50538d8728268a4e4b0d0cb8bfac6a8b9c159d47d8ceea7f6a3bfd] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: What is the title of DIFC Law No. 5 of 2018 and DIFC Law No. 4 of 2019, and when were their consolidated versions last updated?
- [2b4df6b47be14235fb3f3d5b75491ba3232be4e471db296b992446105369b60e] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Which laws were amended by DIFC Law No. 2 of 2022?
- [36a833768836b02a61938fcb5914f069b6b342eaf47d1a67ca2c5acc6d71bc0e] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Which laws were amended by 'DIFC Law No. 2 of 2022'?
- [d9c088343bcf9b1b7a17a4a92b394925494a8ae2a2f86b09d10d267179eb01bb] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: When was the DIFC Laws Amendment Law, DIFC Law No. 8 of 2018 enacted and what law did it amend?
- [4aa0f4e28b151c9fb03acbccd37d724bb0f9fae137c8fdc268c6c03cd6c7c7ac] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Which laws mention the 'Ruler of Dubai' as the legislative authority and also specify that the law comes into force on the date specified in the Enactment Notice?
- [f35f42eba75cda26f5f6439caee02d4c5ef2648ec6d61831f1324c0f631ea10a] expected=law_relation_or_history raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: What are the effective dates for pre-existing and new accounts under the Common Reporting Standard Law 2018, and what is the date of its enactment?
- [6e8d0c41f3e5b8a5383db8964a64254de33aec88f0c7abea793c37ecf4c4db43] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Which laws were made by the Ruler of Dubai and their commencement date is specified in an Enactment Notice?
- [46927f372acef1888a11ef8de5f7a1dff5588a85efc12eaafe7c7f59c5fbf14f] expected=cross_law_compare raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Does the term 'Law' in the Strata Title Regulations refer to the same law number as the 'Employment Law' mentioned in the Employment Regulations?
- [82664b585f15bcd8afa3bd6acf97c3fa415fcad7d60762d8ad80421418caf3f5] expected=law_relation_or_history raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: What is the full title of the enacted law?
- [4ced374a0c805f11161598ee003019f841de3c03da4f478c1b7cea81d58bc4bc] expected=law_relation_or_history raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Does the enactment notice specify a precise calendar date for the law to come into force?
- [f032929682fae6c65c184050d97635e4024703a6d40ed3028a9dde70856ecfad] expected=law_scope_or_definition raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: What is the law number for the 'Law on the Application of Civil and Commercial Laws in the DIFC'?
- [be535a44eec463ed7edfac6f145990d962ea6394f22877b7c991c6140433e056] expected=law_relation_or_history raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: What is the latest DIFC Law number that amended the 'Law on the Application of Civil and Commercial Laws in the DIFC'?
- [75bf397c92fcaee5bf25f9e869454c21c77972e8280c746e33635612ecddda33] expected=law_article_lookup raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: According to Article 10 of the Real Property Law 2018, does freehold ownership of Real Property carry the same rights and obligations as ownership of an estate in fee simple under English common law and equity?
- [6e3abab5157d5897a698c91d0c980646b14e5cc1e773e6c6537e918dcb26275e] expected=law_article_lookup raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: Under the Common Reporting Standard Law 2018, is the Relevant Authority liable for acts or omissions in its performance of functions if the act or omission is shown to have been in bad faith?
- [1e1238c6119ed749321cd0addedbaeb69e68eec861acb1d122a2730e8944bf23] expected=law_article_lookup raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: According to Article 17(1) of the Strata Title Law DIFC Law No. 5 of 2007, what type of resolution is required for a Body Corporate to sell or dispose of part of the Common Property, or grant or amend a lease over part of the Common Property?
- [5b78eff477f6545504892d039a34a82fcba94b79584e925a1e231875f6892a5b] expected=law_article_lookup raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: If a Body Corporate grants an Exclusive Use Right with respect to a part of the Common Property to an Owner, as per Article 16(2) of the Strata Title Law DIFC Law No. 5 of 2007, who are the Body Corporate's rights and liabilities with respect to that part of the Common Property vested in while the Exclusive Use Right continues?
- [30ab0e56ee0c43b5bf94fd9657c7f7ac24f0e7be29ced2933437f7a234713cd7] expected=law_article_lookup raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Under Article 8(1) of the Operating Law 2018, is a person permitted to operate or conduct business in or from the DIFC without being incorporated, registered, or continued under a Prescribed Law or other Legislation administered by the Registrar?
- [73510f45df2f1b3f268f4fabc89e1b98690777acb78579beabb20801b34e3fc4] expected=law_article_lookup raw_mapped=__unmapped__ normalized=law_scope_or_definition raw_runtime=article_lookup source=runtime_metadata.taxonomy_route :: According to the DIFC Non Profit Incorporated Organisations Law 2012, can an Incorporated Organisation undertake Financial Services as prescribed in the General Module of the DFSA Rulebook?
- [0149374f1699ab209f6169cffcdd94f45072fca07fbf7a580720760f5c32f658] expected=law_article_lookup raw_mapped=cross_law_compare normalized=cross_law_compare raw_runtime=cross_law_compare source=runtime_metadata.taxonomy_route :: Under Article 11(2)(b) of the Employment Law 2019, can an Employee waive any right under this Law by entering into a written agreement with their Employer to terminate employment, provided they were given an opportunity to receive independent legal advice or took part in mediation?
