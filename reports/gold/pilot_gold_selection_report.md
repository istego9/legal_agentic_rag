# Pilot Gold Subset Selection Report

- selection_version: `pilot_gold_questions_v1`
- source_questions: `/Users/artemgendler/dev/legal_agentic_rag/public_dataset.json`
- source_triage_queue: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_api_baseline/triage_queue.jsonl`

## Final Route Composition

- `law_article_lookup`: `8`
- `law_relation_or_history`: `5`
- `cross_law_compare`: `5`
- `law_scope_or_definition`: `0`
- `case_family`: `3`
- `negative_or_unanswerable`: `4`

## Highest-Risk Selected Questions

- `e59a0dc49c291402ead91342b065bc4e9ded0043d126f73dd00ba6045aae46b7` `law_article_lookup` `number` - Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide an Employee with a written Employment Contract after the commencement of employment?
- `06034335eee6dbe0df799fd5ce57e8f311ac8ad693dbeeb8dad4edaa9edb53eb` `law_article_lookup` `name` - Under Article 15(1) of the Strata Title Law DIFC Law No. 5 of 2007, what entity holds ownership of the Common Property in trust for the Owners in the Strata Scheme?
- `146567e3d096312584103b24983e3ff8e904e4ec5dea993d9774d24fef15fce7` `law_article_lookup` `number` - According to Article 14(2)(b) of the General Partnership Law 2004, how many years must a Recognised Partnership's Accounting Records be preserved?
- `230b6411c31b25717cb6271824274dd9ebc1cb2575c3ec622ffee06c2aea51e1` `law_article_lookup` `number` - According to Article 8(2)(a) of the DIFC Contract Law 2004, what is the minimum age a natural person must attain to have competent legal capacity?
- `33060f268efcac79c65cd3e0a39bc0f7d91d9bb1802bc2e08bfa43ec5a5cd355` `law_article_lookup` `name` - According to Article 16(1) of the Operating Law 2018, what document must every Registered Person file with the Registrar at the same time as applying for Licence renewal?
- `5b78eff477f6545504892d039a34a82fcba94b79584e925a1e231875f6892a5b` `law_article_lookup` `name` - If a Body Corporate grants an Exclusive Use Right with respect to a part of the Common Property to an Owner, as per Article 16(2) of the Strata Title Law DIFC Law No. 5 of 2007, who are the Body Corporate's rights and liabilities with respect to that part of the Common Property vested in while the Exclusive Use Right continues?
- `0149374f1699ab209f6169cffcdd94f45072fca07fbf7a580720760f5c32f658` `law_article_lookup` `boolean` - Under Article 11(2)(b) of the Employment Law 2019, can an Employee waive any right under this Law by entering into a written agreement with their Employer to terminate employment, provided they were given an opportunity to receive independent legal advice or took part in mediation?
- `47cb314acde5887a03dc25c4f36992ad801e5fa7565d8288af88491f60c53fd5` `law_article_lookup` `boolean` - According to Article 34(1) of the General Partnership Law 2004, is a person admitted as a Partner into an existing General Partnership liable to creditors for anything done before they became a Partner?
- `4cbb1883a9d09e09cbf273aea34dd9ce104eacf5ffa1b3e95e2a5c18440f778c` `law_relation_or_history` `number` - In what year was the Employment Law Amendment Law enacted?
- `7700103c51940db23ba51a0efefbef679201af5b0a60935853d10bf81a260466` `law_relation_or_history` `number` - What is the law number of the Employment Law Amendment Law?
- `82664b585f15bcd8afa3bd6acf97c3fa415fcad7d60762d8ad80421418caf3f5` `law_relation_or_history` `name` - What is the full title of the enacted law?
- `4ced374a0c805f11161598ee003019f841de3c03da4f478c1b7cea81d58bc4bc` `law_relation_or_history` `boolean` - Does the enactment notice specify a precise calendar date for the law to come into force?

## Unavoidable Imbalances

- `none`

## Selection Table

- `e59a0dc49c291402ead91342b065bc4e9ded0043d126f73dd00ba6045aae46b7` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: numeric_requirement. Risk tier: high.
  question: Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide an Employee with a written Employment Contract after the commencement of employment?
- `06034335eee6dbe0df799fd5ce57e8f311ac8ad693dbeeb8dad4edaa9edb53eb` `law_article_lookup` `name` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: compare_dimension. Risk tier: high.
  question: Under Article 15(1) of the Strata Title Law DIFC Law No. 5 of 2007, what entity holds ownership of the Common Property in trust for the Owners in the Strata Scheme?
- `146567e3d096312584103b24983e3ff8e904e4ec5dea993d9774d24fef15fce7` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: numeric_requirement. Risk tier: high.
  question: According to Article 14(2)(b) of the General Partnership Law 2004, how many years must a Recognised Partnership's Accounting Records be preserved?
- `230b6411c31b25717cb6271824274dd9ebc1cb2575c3ec622ffee06c2aea51e1` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: number. Risk tier: high.
  question: According to Article 8(2)(a) of the DIFC Contract Law 2004, what is the minimum age a natural person must attain to have competent legal capacity?
- `33060f268efcac79c65cd3e0a39bc0f7d91d9bb1802bc2e08bfa43ec5a5cd355` `law_article_lookup` `name` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: name. Risk tier: high.
  question: According to Article 16(1) of the Operating Law 2018, what document must every Registered Person file with the Registrar at the same time as applying for Licence renewal?
- `5b78eff477f6545504892d039a34a82fcba94b79584e925a1e231875f6892a5b` `law_article_lookup` `name` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: identity_lookup. Risk tier: high.
  question: If a Body Corporate grants an Exclusive Use Right with respect to a part of the Common Property to an Owner, as per Article 16(2) of the Strata Title Law DIFC Law No. 5 of 2007, who are the Body Corporate's rights and liabilities with respect to that part of the Common Property vested in while the Exclusive Use Right continues?
- `0149374f1699ab209f6169cffcdd94f45072fca07fbf7a580720760f5c32f658` `law_article_lookup` `boolean` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: boolean_norm. Risk tier: high.
  question: Under Article 11(2)(b) of the Employment Law 2019, can an Employee waive any right under this Law by entering into a written agreement with their Employer to terminate employment, provided they were given an opportunity to receive independent legal advice or took part in mediation?
- `47cb314acde5887a03dc25c4f36992ad801e5fa7565d8288af88491f60c53fd5` `law_article_lookup` `boolean` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: boolean. Risk tier: high.
  question: According to Article 34(1) of the General Partnership Law 2004, is a person admitted as a Partner into an existing General Partnership liable to creditors for anything done before they became a Partner?
- `4cbb1883a9d09e09cbf273aea34dd9ce104eacf5ffa1b3e95e2a5c18440f778c` `law_relation_or_history` `number` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: In what year was the Employment Law Amendment Law enacted?
- `7700103c51940db23ba51a0efefbef679201af5b0a60935853d10bf81a260466` `law_relation_or_history` `number` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: number. Risk tier: high.
  question: What is the law number of the Employment Law Amendment Law?
- `82664b585f15bcd8afa3bd6acf97c3fa415fcad7d60762d8ad80421418caf3f5` `law_relation_or_history` `name` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: What is the full title of the enacted law?
- `4ced374a0c805f11161598ee003019f841de3c03da4f478c1b7cea81d58bc4bc` `law_relation_or_history` `boolean` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: boolean_norm. Risk tier: high.
  question: Does the enactment notice specify a precise calendar date for the law to come into force?
- `1107e2844571d4c05755c1607e1a847a54fc023777f8b4f87e2ac50d5256c3d8` `law_relation_or_history` `free_text` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: free_text. Risk tier: high.
  question: What is the commencement date for the Data Protection Law 2020 and the Employment Law 2019?
- `af8d46901ce0daf134701c809e7ae02f5682b9676a20a226b61eaa40512dbc4e` `cross_law_compare` `boolean` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: boolean. Risk tier: high.
  question: Did the DIFC Law Amendment Law (DIFC Law No. 1 of 2024) come into force on the same date as the Digital Assets Law (DIFC Law No. 2 of 2024)?
- `b249b41b7ff44ce4d5686bb8b9e0533e4874f5482a2594f49d60edf11b04f1ac` `cross_law_compare` `boolean` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: history_or_version. Risk tier: high.
  question: Was the Strata Title Law Amendment Law, DIFC Law No. 11 of 2018, enacted on the same day as the Financial Collateral Regulations came into force?
- `e14388d8fe61056e07ce155e692acf4552e070e0ee88d73b20c15c3c750dbc0d` `cross_law_compare` `free_text` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: compare_dimension. Risk tier: high.
  question: What is the common commencement date for the DIFC Laws Amendment Law, DIFC Law No. 3 of 2024, and the Law of Security Law, DIFC Law No. 4 of 2024?
- `96bccc8b15e2795578584484ea3533e71d6e044d13420cf77a32393b7502fc1c` `cross_law_compare` `boolean` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: authority_or_administration. Risk tier: high.
  question: Is the Intellectual Property Law No. 4 of 2019 administered by the same entity that administers the Trust Law No. 4 of 2018?
- `2180c75894515d7db767c477c26326e97f1cd69c17c4f1746706e859f2d0e10d` `cross_law_compare` `free_text` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: free_text. Risk tier: high.
  question: Which laws explicitly mention the Companies Law 2018 and the Insolvency Law 2009 in their regulations concerning company structures?
- `0f6e75bde356a184b0fa69f0568c29290fb8adf42b5409ab4d2e7e1c193295dd` `case_family` `name` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: compare_dimension. Risk tier: high.
  question: Which case was decided earlier: ENF 269/2023 or SCT 169/2025?
- `d204a13070fd2f18eb3e9e939fdc80855a915dfafd7f49f8fc8e80d6a3d7637b` `case_family` `number` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: number. Risk tier: high.
  question: What was the claim value referenced in the appeal judgment CA 005/2025?
- `6f9c0b194e9e654d320fe873627afcd5403fd3ff3f4f939d6389e9431c20f413` `case_family` `names` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: identity_lookup. Risk tier: high.
  question: Identify all claimants who appeared at any point in case TCD 001/2024.
- `5bf060b3f9965c46f19e59c4d9afa555d6a1b04e9b9675ed35ef6b85249bb811` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: What did the jury decide in case ENF 053/2025?
- `84941458c4ade946dae84cf5ebc4abf362a6f6e6fec835ba5c43ad2d3b4b14d7` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: Is there any information about parole hearings in case CFI 057/2025?
- `89f4b2e86cf7e48e185b9d5775d67e7c8a51beccbb20abce8dac2a1b0e80b723` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: Were the Miranda rights properly administered in case ENF 269/2023?
- `cb9cb3ecb09af7477b20abee3d5f9567c09a99fb6f4840daf933da74680ef030` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: What was the plea bargain in case ARB 032/2025?
