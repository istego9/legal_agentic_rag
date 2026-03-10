# Router Benchmark Summary

- generated_at_utc: `2026-03-10T18:25:06.263030+00:00`
- public_dataset_path: `/Users/artemgendler/dev/legal_agentic_rag/public_dataset.json`
- taxonomy_path: `/Users/artemgendler/dev/legal_agentic_rag/datasets/taxonomy/public_question_taxonomy.v1.jsonl`
- benchmark_target: `services.runtime.router.resolve_route`
- benchmark_mapping: `scripts.router_benchmark.map_runtime_route_to_primary_route`
- total_questions: `100`
- correct_predictions: `49`
- overall_accuracy: `0.4900`

## Per-Route Precision/Recall/F1

| primary_route | support | predicted | precision | recall | f1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 9 | 0.3333 | 1.0000 | 0.5000 |
| case_outcome_or_value | 3 | 16 | 0.1875 | 1.0000 | 0.3158 |
| case_cross_compare | 17 | 0 | 0.0000 | 0.0000 | 0.0000 |
| law_article_lookup | 31 | 33 | 0.8788 | 0.9355 | 0.9062 |
| law_relation_or_history | 17 | 14 | 0.7143 | 0.5882 | 0.6452 |
| law_scope_or_definition | 4 | 28 | 0.1429 | 1.0000 | 0.2500 |
| cross_law_compare | 21 | 0 | 0.0000 | 0.0000 | 0.0000 |
| negative_or_unanswerable | 4 | 0 | 0.0000 | 0.0000 | 0.0000 |

## Confusion Matrix

| expected \\ predicted | case_entity_lookup | case_outcome_or_value | case_cross_compare | law_article_lookup | law_relation_or_history | law_scope_or_definition | cross_law_compare | negative_or_unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| case_entity_lookup | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_outcome_or_value | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| case_cross_compare | 6 | 9 | 0 | 0 | 0 | 2 | 0 | 0 |
| law_article_lookup | 0 | 0 | 0 | 29 | 0 | 2 | 0 | 0 |
| law_relation_or_history | 0 | 0 | 0 | 0 | 10 | 7 | 0 | 0 |
| law_scope_or_definition | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 |
| cross_law_compare | 0 | 0 | 0 | 4 | 4 | 13 | 0 | 0 |
| negative_or_unanswerable | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 |

## Mismatches (51)

- [eeae1069cbbc9ef2fe66f063459ddac4c5ff5edef405593bb299aca715246b39] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: How does Law No. 1 of 2025 modify the application of the Data Protection Law 2020 as it pertains to processing Personal Data in the DIFC by a Controller or Processor, as originally outlined in the Data Protection Law 2020?
- [89fd4fbcdcf5c17ba256395ee64378a3f2125b081394a9568964defb28fdef75] expected=cross_law_compare predicted=law_article_lookup runtime=article_lookup :: Which laws mention 'interpretative provisions' in their schedules?
- [fb1de34d3ebe58b03c5e9898c2e29d1d8c6297fa570f0021967986e43b62da62] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: Who has the authority to make the Dematerialised Investments Regulations (DIR), and what other laws are cited as conferring powers for these regulations?
- [571f60136b26b5ce872f29817024fa60d27e8d3e49cec533d162fa48af9d4b13] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: What are the titles of DIFC Law No. 6 of 2013 and DIFC Law No. 3 of 2013?
- [4aa0f4e28b151c9fb03acbccd37d724bb0f9fae137c8fdc268c6c03cd6c7c7ac] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: Which laws mention the 'Ruler of Dubai' as the legislative authority and also specify that the law comes into force on the date specified in the Enactment Notice?
- [bd8d0befc731315ee2a477221feb950b44e68d9596823a90c47f78fc04870870] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Was the Employment Law enacted in the same year as the Intellectual Property Law?
- [bb67fc19f45527933d0c7319a2c96b4bf5e782f83018254b6a0d34685b219ec5] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Was the Intellectual Property Law enacted earlier in the year than the Employment Law?
- [96bccc8b15e2795578584484ea3533e71d6e044d13420cf77a32393b7502fc1c] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Is the Intellectual Property Law No. 4 of 2019 administered by the same entity that administers the Trust Law No. 4 of 2018?
- [9f9fb4b911d75c22f2c9a42bb852848ac45594179a7d0d126c8ef0ac8941b18d] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Do cases CA 004/2025 and SCT 295/2025 involve any of the same legal entities or individuals as parties?
- [737940cf4c4cd4c7f6f6d3b8b30570e853538790e06d40583631acf017eb6029] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Is there any main party that appeared in both cases CFI 010/2024 and ENF 053/2025 at any point?
- [bfa089d55bda48890b3f84ec000ad2c3c682031ff7153cc8023efeeb8c1ff9e3] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Was the same judge involved in both case CFI 010/2024 and case DEC 001/2025 at any point?
- [52a35cfabe76f2c538c6f72a841a08e0cc85bbe8f732874a4d2827383794c213] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Did cases CA 004/2025 and ARB 034/2025 have any judges in common?
- [54d56331536ad42544a97a57c5d700cf82d9b5b46dc2e6a08a31992d5b755fb0] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Is there any party (claimant or defendant) common to both case TCD 001/2024 and case CFI 016/2025 at any point?
- [fba6e86a3169728c19a02ccbad9cd87599344fdd0bfd0589e5ab7bf6e16a09b9] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Did cases DEC 001/2025 and CFI 057/2025 have any judges in common at any point?
- [1e1121d0cc14259a4f345408302ef2ddf8e474cdb9ad60a34b060bd789b95298] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Do cases DEC 001/2025 and SCT 514/2025 involve any of the same legal entities or individuals as main parties at any point?
- [3c19ecbe27fe9701f742589a927a11a5b701f064e49d35d631deef0d478aa99f] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Was the same judge involved in both case DEC 001/2025 and case TCD 001/2024 at any point?
- [2d436eb3d28cb6d4eacebcb6d703e402800a56bc2f8b4d4185ea5961d5e53960] expected=case_cross_compare predicted=law_scope_or_definition runtime=article_lookup :: Identify whether any person or company is a main party to both CA 005/2025 and CFI 067/2025 at any point.
- [acd3200d75f4507d2cfbbcb1c568d7adf8da409063bee2e2e0b7832c4894a5a9] expected=cross_law_compare predicted=law_article_lookup runtime=article_lookup :: What are the common elements found in the interpretation sections of the Operating Law 2018, Trust Law 2018, and Common Reporting Standard Law 2018?
- [4ce050c0d6261bf3ee2eafa9c7d5fc7273e390a4a1c09ab6e26f691c68199d1b] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: What entity administers the Leasing Law 2020 and the Trust Law 2018?
- [6351cfe2534da67df395e52e3370b7b5f724a1ac5d23e053b3d8ebc88a5f634c] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Which laws are administered by the Registrar and were enacted in 2004?
- [b4d8c1cc3b6017107e2f566421d5548b95844e6fa9f6c9e40a695f4bbc11ee6a] expected=cross_law_compare predicted=law_article_lookup runtime=article_lookup :: What are the common elements found in Schedule 1 of the Operating Law 2018 and the Trust Law 2018?
- [5d8fd8335f98f500b33d96269161657f4493445e6fc6afc5f2a4baba3bd49a3e] expected=cross_law_compare predicted=law_article_lookup runtime=article_lookup :: Which laws, enacted in 2018, include provisions relating to the application of the Arbitration Law in their Schedule 2?
- [8d481702ddfb40310a070ac44f4a2e9637043f453afa0319cd83d20fd8ec607e] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: What is the prescribed penalty for an offense against the Strata Title Law under the Strata Title Regulations, and what is the penalty for using leased premises for an illegal purpose under the Leasing Regulations?
- [e14388d8fe61056e07ce155e692acf4552e070e0ee88d73b20c15c3c750dbc0d] expected=cross_law_compare predicted=law_relation_or_history runtime=history_lineage :: What is the common commencement date for the DIFC Laws Amendment Law, DIFC Law No. 3 of 2024, and the Law of Security Law, DIFC Law No. 4 of 2024?
- [54103603d632383a733ea81fe983eac4982a22bbd77f1e8a0daa333c249cd5c9] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: How do the Limited Liability Partnership Law and the Non Profit Incorporated Organisations Law define their administration?
- [115a9bca032550a20271240b8785b922d35a7117f7f1760250eba1c34345be9e] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Which laws mention the Ruler of Dubai as the legislative authority and were enacted in 2018?
- [2180c75894515d7db767c477c26326e97f1cd69c17c4f1746706e859f2d0e10d] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Which laws explicitly mention the Companies Law 2018 and the Insolvency Law 2009 in their regulations concerning company structures?
- [1107e2844571d4c05755c1607e1a847a54fc023777f8b4f87e2ac50d5256c3d8] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: What is the commencement date for the Data Protection Law 2020 and the Employment Law 2019?
- [b909797db886eacd0f6264bf87649f2ada41f9b7d6c02bc12fe7ea21a02a7418] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Which laws are administered by the Registrar and what are their respective citation titles?
- [f35f42eba75cda26f5f6439caee02d4c5ef2648ec6d61831f1324c0f631ea10a] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: What are the effective dates for pre-existing and new accounts under the Common Reporting Standard Law 2018, and what is the date of its enactment?
- [8e3b4683596d94dbc9a66f20104329939e0e8d4da1e1dbf6df5784247c2ea373] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: Was the same judge involved in both case CA 005/2025 and case TCD 001/2024 at any point?
- [6e8d0c41f3e5b8a5383db8964a64254de33aec88f0c7abea793c37ecf4c4db43] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: Which laws were made by the Ruler of Dubai and their commencement date is specified in an Enactment Notice?
- [b9dc2dae206c155bc5936c971272e8154d22b4f9e3fa65795eb8b49a80d26b6f] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Which case was decided earlier: CFI 016/2025 or ENF 269/2023?
- [0f6e75bde356a184b0fa69f0568c29290fb8adf42b5409ab4d2e7e1c193295dd] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Which case was decided earlier: ENF 269/2023 or SCT 169/2025?
- [d9d27c9cace6eafd11dbb349244e0443e16c8cc0efdf516514cc945135e1a597] expected=case_cross_compare predicted=law_scope_or_definition runtime=article_lookup :: Between ARB 034/2025 and SCT 295/2025, which was issued first?
- [3dc92e33b028436ab27768b30c91d5c53f0527acb35f8378f55131fc77f628bf] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Which case has an earlier decision date: CFI 010/2024 or SCT 169/2025?
- [fbe661b99e48c27ade90fbce66ae359902f15f2351774dd29c00f41c62f72c80] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Which case was decided earlier: CA 004/2025 or SCT 295/2025?
- [d4157e6a3b7b321d042a7d5db7cf2e829317d818e4f2d56ea2399c5547f95b42] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Which case was decided earlier: ENF 269/2023 or SCT 514/2025?
- [8f104743e21eef9d7218950d7a7a1eade455fafb809ba01a923c1d88f0493c8f] expected=case_cross_compare predicted=case_entity_lookup runtime=single_case_extraction :: Identify the case ID with the higher monetary amount: ARB 032/2025 or CFI 067/2025?
- [46927f372acef1888a11ef8de5f7a1dff5588a85efc12eaafe7c7f59c5fbf14f] expected=cross_law_compare predicted=law_scope_or_definition runtime=article_lookup :: Does the term 'Law' in the Strata Title Regulations refer to the same law number as the 'Employment Law' mentioned in the Employment Regulations?
- [b249b41b7ff44ce4d5686bb8b9e0533e4874f5482a2594f49d60edf11b04f1ac] expected=cross_law_compare predicted=law_relation_or_history runtime=history_lineage :: Was the Strata Title Law Amendment Law, DIFC Law No. 11 of 2018, enacted on the same day as the Financial Collateral Regulations came into force?
- [d5bc744160e9f3690c91cd3ee29e601a00444ac66a53b0e8e4d7991e1bf7de20] expected=cross_law_compare predicted=law_relation_or_history runtime=history_lineage :: Was the Leasing Law enacted in the same year as the Real Property Law Amendment Law?
- [af8d46901ce0daf134701c809e7ae02f5682b9676a20a226b61eaa40512dbc4e] expected=cross_law_compare predicted=law_relation_or_history runtime=history_lineage :: Did the DIFC Law Amendment Law (DIFC Law No. 1 of 2024) come into force on the same date as the Digital Assets Law (DIFC Law No. 2 of 2024)?
- [82664b585f15bcd8afa3bd6acf97c3fa415fcad7d60762d8ad80421418caf3f5] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: What is the full title of the enacted law?
- [4ced374a0c805f11161598ee003019f841de3c03da4f478c1b7cea81d58bc4bc] expected=law_relation_or_history predicted=law_scope_or_definition runtime=article_lookup :: Does the enactment notice specify a precise calendar date for the law to come into force?
- [6e3abab5157d5897a698c91d0c980646b14e5cc1e773e6c6537e918dcb26275e] expected=law_article_lookup predicted=law_scope_or_definition runtime=article_lookup :: Under the Common Reporting Standard Law 2018, is the Relevant Authority liable for acts or omissions in its performance of functions if the act or omission is shown to have been in bad faith?
- [73510f45df2f1b3f268f4fabc89e1b98690777acb78579beabb20801b34e3fc4] expected=law_article_lookup predicted=law_scope_or_definition runtime=article_lookup :: According to the DIFC Non Profit Incorporated Organisations Law 2012, can an Incorporated Organisation undertake Financial Services as prescribed in the General Module of the DFSA Rulebook?
- [5bf060b3f9965c46f19e59c4d9afa555d6a1b04e9b9675ed35ef6b85249bb811] expected=negative_or_unanswerable predicted=case_outcome_or_value runtime=single_case_extraction :: What did the jury decide in case ENF 053/2025?
- [84941458c4ade946dae84cf5ebc4abf362a6f6e6fec835ba5c43ad2d3b4b14d7] expected=negative_or_unanswerable predicted=case_outcome_or_value runtime=single_case_extraction :: Is there any information about parole hearings in case CFI 057/2025?
- [89f4b2e86cf7e48e185b9d5775d67e7c8a51beccbb20abce8dac2a1b0e80b723] expected=negative_or_unanswerable predicted=case_outcome_or_value runtime=single_case_extraction :: Were the Miranda rights properly administered in case ENF 269/2023?
- [cb9cb3ecb09af7477b20abee3d5f9567c09a99fb6f4840daf933da74680ef030] expected=negative_or_unanswerable predicted=case_outcome_or_value runtime=single_case_extraction :: What was the plea bargain in case ARB 032/2025?
