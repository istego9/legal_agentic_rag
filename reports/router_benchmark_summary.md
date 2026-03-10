# Router Benchmark Summary

- generated_at_utc: `2026-03-10T18:58:23.473245+00:00`
- public_dataset_path: `/Users/artemgendler/dev/legal_agentic_rag/public_dataset.json`
- taxonomy_path: `/Users/artemgendler/dev/legal_agentic_rag/datasets/taxonomy/public_question_taxonomy.v1.jsonl`
- benchmark_target: `services.runtime.router.resolve_route`
- benchmark_mapping: `packages.router.benchmark_mapping.normalize_runtime_route_for_taxonomy`
- normalization_model_version: `benchmark_route_normalization.v1`
- total_questions: `100`
- correct_predictions: `80`
- overall_accuracy: `0.8000`
- macro_f1: `0.8264`

## Per-Route Precision/Recall/F1

| primary_route | support | predicted | precision | recall | f1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_outcome_or_value | 3 | 3 | 1.0000 | 1.0000 | 1.0000 |
| case_cross_compare | 17 | 17 | 1.0000 | 1.0000 | 1.0000 |
| law_article_lookup | 31 | 25 | 0.9600 | 0.7742 | 0.8571 |
| law_relation_or_history | 17 | 15 | 0.7333 | 0.6471 | 0.6875 |
| law_scope_or_definition | 4 | 6 | 0.3333 | 0.5000 | 0.4000 |
| cross_law_compare | 21 | 27 | 0.5926 | 0.7619 | 0.6667 |
| negative_or_unanswerable | 4 | 4 | 1.0000 | 1.0000 | 1.0000 |

## Predicted Count By Raw Runtime Route

| raw_runtime_route | predicted_count |
| --- | ---: |
| article_lookup | 61 |
| single_case_extraction | 25 |
| history_lineage | 14 |

## Predicted Count By Normalized Taxonomy Route

| normalized_taxonomy_route | predicted_count |
| --- | ---: |
| case_entity_lookup | 3 |
| case_outcome_or_value | 3 |
| case_cross_compare | 17 |
| law_article_lookup | 25 |
| law_relation_or_history | 15 |
| law_scope_or_definition | 6 |
| cross_law_compare | 27 |
| negative_or_unanswerable | 4 |

## Confusion Matrix

| expected \\ predicted | case_entity_lookup | case_outcome_or_value | case_cross_compare | law_article_lookup | law_relation_or_history | law_scope_or_definition | cross_law_compare | negative_or_unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_outcome_or_value | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_cross_compare | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 |
| law_article_lookup | 0 | 0 | 0 | 24 | 1 | 2 | 4 | 0 |
| law_relation_or_history | 0 | 0 | 0 | 0 | 11 | 1 | 5 | 0 |
| law_scope_or_definition | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 0 |
| cross_law_compare | 0 | 0 | 0 | 1 | 3 | 1 | 16 | 0 |
| negative_or_unanswerable | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |

## Top Confusion Pairs

- law_relation_or_history -> cross_law_compare: 5
- law_article_lookup -> cross_law_compare: 4
- cross_law_compare -> law_relation_or_history: 3
- law_article_lookup -> law_scope_or_definition: 2
- law_scope_or_definition -> cross_law_compare: 2
- cross_law_compare -> law_article_lookup: 1
- cross_law_compare -> law_scope_or_definition: 1
- law_article_lookup -> law_relation_or_history: 1
- law_relation_or_history -> law_scope_or_definition: 1

## Dead Routes

- none

## Mismatches (20)

- [eeae1069cbbc9ef2fe66f063459ddac4c5ff5edef405593bb299aca715246b39] expected=law_relation_or_history normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: How does Law No. 1 of 2025 modify the application of the Data Protection Law 2020 as it pertains to processing Personal Data in the DIFC by a Controller or Processor, as originally outlined in the Data Protection Law 2020?
- [89fd4fbcdcf5c17ba256395ee64378a3f2125b081394a9568964defb28fdef75] expected=cross_law_compare normalized=law_article_lookup raw=article_lookup subroute=law_article_lookup :: Which laws mention 'interpretative provisions' in their schedules?
- [fb1de34d3ebe58b03c5e9898c2e29d1d8c6297fa570f0021967986e43b62da62] expected=law_relation_or_history normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: Who has the authority to make the Dematerialised Investments Regulations (DIR), and what other laws are cited as conferring powers for these regulations?
- [2b4df6b47be14235fb3f3d5b75491ba3232be4e471db296b992446105369b60e] expected=law_relation_or_history normalized=cross_law_compare raw=history_lineage subroute=cross_law_compare :: Which laws were amended by DIFC Law No. 2 of 2022?
- [36a833768836b02a61938fcb5914f069b6b342eaf47d1a67ca2c5acc6d71bc0e] expected=law_relation_or_history normalized=cross_law_compare raw=history_lineage subroute=cross_law_compare :: Which laws were amended by 'DIFC Law No. 2 of 2022'?
- [4aa0f4e28b151c9fb03acbccd37d724bb0f9fae137c8fdc268c6c03cd6c7c7ac] expected=law_relation_or_history normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: Which laws mention the 'Ruler of Dubai' as the legislative authority and also specify that the law comes into force on the date specified in the Enactment Notice?
- [6351cfe2534da67df395e52e3370b7b5f724a1ac5d23e053b3d8ebc88a5f634c] expected=cross_law_compare normalized=law_relation_or_history raw=article_lookup subroute=law_relation_or_history :: Which laws are administered by the Registrar and were enacted in 2004?
- [115a9bca032550a20271240b8785b922d35a7117f7f1760250eba1c34345be9e] expected=cross_law_compare normalized=law_relation_or_history raw=article_lookup subroute=law_relation_or_history :: Which laws mention the Ruler of Dubai as the legislative authority and were enacted in 2018?
- [1107e2844571d4c05755c1607e1a847a54fc023777f8b4f87e2ac50d5256c3d8] expected=cross_law_compare normalized=law_relation_or_history raw=article_lookup subroute=law_relation_or_history :: What is the commencement date for the Data Protection Law 2020 and the Employment Law 2019?
- [b909797db886eacd0f6264bf87649f2ada41f9b7d6c02bc12fe7ea21a02a7418] expected=cross_law_compare normalized=law_scope_or_definition raw=article_lookup subroute=law_scope_or_definition :: Which laws are administered by the Registrar and what are their respective citation titles?
- [f35f42eba75cda26f5f6439caee02d4c5ef2648ec6d61831f1324c0f631ea10a] expected=law_relation_or_history normalized=law_scope_or_definition raw=article_lookup subroute=law_scope_or_definition :: What are the effective dates for pre-existing and new accounts under the Common Reporting Standard Law 2018, and what is the date of its enactment?
- [f032929682fae6c65c184050d97635e4024703a6d40ed3028a9dde70856ecfad] expected=law_scope_or_definition normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: What is the law number for the 'Law on the Application of Civil and Commercial Laws in the DIFC'?
- [f378457dc4e9f78aa2ce25dde7449a5400b853217f8ebda07a8654a015b15021] expected=law_scope_or_definition normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: What is the law number of the Data Protection Law?
- [75bf397c92fcaee5bf25f9e869454c21c77972e8280c746e33635612ecddda33] expected=law_article_lookup normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: According to Article 10 of the Real Property Law 2018, does freehold ownership of Real Property carry the same rights and obligations as ownership of an estate in fee simple under English common law and equity?
- [6e3abab5157d5897a698c91d0c980646b14e5cc1e773e6c6537e918dcb26275e] expected=law_article_lookup normalized=law_scope_or_definition raw=article_lookup subroute=law_scope_or_definition :: Under the Common Reporting Standard Law 2018, is the Relevant Authority liable for acts or omissions in its performance of functions if the act or omission is shown to have been in bad faith?
- [06034335eee6dbe0df799fd5ce57e8f311ac8ad693dbeeb8dad4edaa9edb53eb] expected=law_article_lookup normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: Under Article 15(1) of the Strata Title Law DIFC Law No. 5 of 2007, what entity holds ownership of the Common Property in trust for the Owners in the Strata Scheme?
- [1e1238c6119ed749321cd0addedbaeb69e68eec861acb1d122a2730e8944bf23] expected=law_article_lookup normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: According to Article 17(1) of the Strata Title Law DIFC Law No. 5 of 2007, what type of resolution is required for a Body Corporate to sell or dispose of part of the Common Property, or grant or amend a lease over part of the Common Property?
- [5b78eff477f6545504892d039a34a82fcba94b79584e925a1e231875f6892a5b] expected=law_article_lookup normalized=cross_law_compare raw=article_lookup subroute=cross_law_compare :: If a Body Corporate grants an Exclusive Use Right with respect to a part of the Common Property to an Owner, as per Article 16(2) of the Strata Title Law DIFC Law No. 5 of 2007, who are the Body Corporate's rights and liabilities with respect to that part of the Common Property vested in while the Exclusive Use Right continues?
- [73510f45df2f1b3f268f4fabc89e1b98690777acb78579beabb20801b34e3fc4] expected=law_article_lookup normalized=law_scope_or_definition raw=article_lookup subroute=law_scope_or_definition :: According to the DIFC Non Profit Incorporated Organisations Law 2012, can an Incorporated Organisation undertake Financial Services as prescribed in the General Module of the DFSA Rulebook?
- [e59a0dc49c291402ead91342b065bc4e9ded0043d126f73dd00ba6045aae46b7] expected=law_article_lookup normalized=law_relation_or_history raw=article_lookup subroute=law_relation_or_history :: Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide an Employee with a written Employment Contract after the commencement of employment?
