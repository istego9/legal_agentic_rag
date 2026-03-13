# Pilot Gold Subset Selection Report

- selection_version: `pilot_gold_questions_v1`
- source_questions: `/Users/artemgendler/dev/legal_agentic_rag/datasets/official_fetch_2026-03-11/questions.json`
- source_triage_queue: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/triage_queue.jsonl`

## Final Route Composition

- `law_article_lookup`: `8`
- `law_relation_or_history`: `4`
- `cross_law_compare`: `1`
- `law_scope_or_definition`: `5`
- `case_family`: `3`
- `negative_or_unanswerable`: `4`

## Highest-Risk Selected Questions

- `e59a0dc49c291402ead91342b065bc4e9ded0043d126f73dd00ba6045aae46b7` `law_article_lookup` `number` - Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide an Employee with a written Employment Contract after the commencement of employment?
- `146567e3d096312584103b24983e3ff8e904e4ec5dea993d9774d24fef15fce7` `law_article_lookup` `number` - According to Article 14(2)(b) of the General Partnership Law 2004, how many years must a Recognised Partnership's Accounting Records be preserved?
- `254c8499b22ba05b0b1536c111b23e8afb031d0ed14af5970f665d6b1e821e65` `law_article_lookup` `number` - Under Article 26(2) of the Employment Law 2019, for how many months after the actual date of childbirth is a female Employee returning from Maternity Leave entitled to nursing breaks if her working time exceeds six hours?
- `33060f268efcac79c65cd3e0a39bc0f7d91d9bb1802bc2e08bfa43ec5a5cd355` `law_article_lookup` `name` - According to Article 16(1) of the Operating Law 2018, what document must every Registered Person file with the Registrar at the same time as applying for Licence renewal?
- `0149374f1699ab209f6169cffcdd94f45072fca07fbf7a580720760f5c32f658` `law_article_lookup` `boolean` - Under Article 11(2)(b) of the Employment Law 2019, can an Employee waive any right under this Law by entering into a written agreement with their Employer to terminate employment, provided they were given an opportunity to receive independent legal advice or took part in mediation?
- `7aae865f328e2012c31b41b6e2cccac715c14df5b56ec548d3fa9cb6bc46dcd1` `law_article_lookup` `boolean` - Under Article 11 of the General Partnership Law 2004, is an unincorporated body of persons carrying on business for profit automatically deemed a partnership if there is an agreement specifying it as a body corporate?
- `9f48d8eca6d10cf26f60226078f0d9cb32d3aa2fd25c90c312549cb6265ebd84` `law_article_lookup` `free_text` - According to Article 2 of the DIFC Personal Property Law 2005, who made this Law?
- `bce4c288236518dfd08f6bac5a75c75ea79b1250347c4b998252fa9d7265a7c3` `law_article_lookup` `free_text` - What kind of liability do Partners have under Article 28(1) of the General Partnership Law 2004?
- `9596fb754439e6752034890c1272a2df7c0f9000db7d186db21aa232a253fca4` `law_relation_or_history` `free_text` - What is the effective date for due diligence requirements for Pre-existing Accounts and New Accounts under the Common Reporting Standard Law 2018?
- `98d473221f50a845466544b43d6bb52b0497893aade63a8659db228459c271b4` `law_relation_or_history` `free_text` - When was the consolidated version of the Law on the Application of Civil and Commercial Laws in the DIFC published?
- `b2fcc22c0bfc27e799fec5df74c911114a91f83d0aa2995729390d6c8cb80c1a` `law_relation_or_history` `free_text` - On what date was the DIFC Personal Property Law 2005 enacted?
- `fcabd6aa14e2df4b7ca00fa516a70eba6de58b74dfde30270e3fe3eec6d1da7a` `law_relation_or_history` `free_text` - Which specific DIFC Laws were amended by DIFC Law No. 2 of 2022?

## Unavoidable Imbalances

- law_relation_or_history: selected 4 of target 5 because only 4 current candidates matched this family.
- cross_law_compare: selected 1 of target 5 because only 1 current candidates matched this family.
- law_scope_or_definition substitution: filled 5 missing slots because current baseline exposes too few law_relation_or_history/cross_law_compare candidates.

## Selection Table

- `e59a0dc49c291402ead91342b065bc4e9ded0043d126f73dd00ba6045aae46b7` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: numeric_requirement. Risk tier: high.
  question: Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide an Employee with a written Employment Contract after the commencement of employment?
- `146567e3d096312584103b24983e3ff8e904e4ec5dea993d9774d24fef15fce7` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: numeric_requirement. Risk tier: high.
  question: According to Article 14(2)(b) of the General Partnership Law 2004, how many years must a Recognised Partnership's Accounting Records be preserved?
- `254c8499b22ba05b0b1536c111b23e8afb031d0ed14af5970f665d6b1e821e65` `law_article_lookup` `number` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: numeric_requirement. Risk tier: high.
  question: Under Article 26(2) of the Employment Law 2019, for how many months after the actual date of childbirth is a female Employee returning from Maternity Leave entitled to nursing breaks if her working time exceeds six hours?
- `33060f268efcac79c65cd3e0a39bc0f7d91d9bb1802bc2e08bfa43ec5a5cd355` `law_article_lookup` `name` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: name. Risk tier: high.
  question: According to Article 16(1) of the Operating Law 2018, what document must every Registered Person file with the Registrar at the same time as applying for Licence renewal?
- `0149374f1699ab209f6169cffcdd94f45072fca07fbf7a580720760f5c32f658` `law_article_lookup` `boolean` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: boolean_norm. Risk tier: high.
  question: Under Article 11(2)(b) of the Employment Law 2019, can an Employee waive any right under this Law by entering into a written agreement with their Employer to terminate employment, provided they were given an opportunity to receive independent legal advice or took part in mediation?
- `7aae865f328e2012c31b41b6e2cccac715c14df5b56ec548d3fa9cb6bc46dcd1` `law_article_lookup` `boolean` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: boolean. Risk tier: high.
  question: Under Article 11 of the General Partnership Law 2004, is an unincorporated body of persons carrying on business for profit automatically deemed a partnership if there is an agreement specifying it as a body corporate?
- `9f48d8eca6d10cf26f60226078f0d9cb32d3aa2fd25c90c312549cb6265ebd84` `law_article_lookup` `free_text` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: authority_or_administration. Risk tier: high.
  question: According to Article 2 of the DIFC Personal Property Law 2005, who made this Law?
- `bce4c288236518dfd08f6bac5a75c75ea79b1250347c4b998252fa9d7265a7c3` `law_article_lookup` `free_text` `high`
  reason: Selected to cover high-risk single-document law/article retrieval and direct provision lookup. Theme: free_text. Risk tier: high.
  question: What kind of liability do Partners have under Article 28(1) of the General Partnership Law 2004?
- `9596fb754439e6752034890c1272a2df7c0f9000db7d186db21aa232a253fca4` `law_relation_or_history` `free_text` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: What is the effective date for due diligence requirements for Pre-existing Accounts and New Accounts under the Common Reporting Standard Law 2018?
- `98d473221f50a845466544b43d6bb52b0497893aade63a8659db228459c271b4` `law_relation_or_history` `free_text` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: When was the consolidated version of the Law on the Application of Civil and Commercial Laws in the DIFC published?
- `b2fcc22c0bfc27e799fec5df74c911114a91f83d0aa2995729390d6c8cb80c1a` `law_relation_or_history` `free_text` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: On what date was the DIFC Personal Property Law 2005 enacted?
- `fcabd6aa14e2df4b7ca00fa516a70eba6de58b74dfde30270e3fe3eec6d1da7a` `law_relation_or_history` `free_text` `high`
  reason: Selected to cover law amendment, enactment, publication, or effective-date history questions. Theme: history_or_version. Risk tier: high.
  question: Which specific DIFC Laws were amended by DIFC Law No. 2 of 2022?
- `a341025df493b0e6a962fa637e3df6fe053c3de28cb2f5c8eb0814067af32b95` `cross_law_compare` `free_text` `high`
  reason: Selected to cover cross-law comparison behavior across multiple legal instruments. Theme: compare_dimension. Risk tier: high.
  question: According to Article 12(4) of the Common Reporting Standard Law and Article 18(2)(b) of the General Partnership Law, what are the retention periods for records?
- `5d271fced60d88e008a69adc2da21de427906206bfb49f5554a3bf1dd6f72772` `law_scope_or_definition` `number` `high`
  reason: Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented. This row fills an unavoidable route-composition gap. Theme: title_identity. Risk tier: high.
  question: According to the title page of the Common Reporting Standard Law, what is its official DIFC Law number?
- `042ddf2ed161068fab8072f16e01a15e11da9d741d207bfc0185e5133a810193` `law_scope_or_definition` `boolean` `high`
  reason: Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented. This row fills an unavoidable route-composition gap. Theme: boolean_norm. Risk tier: high.
  question: Does the Law on the Application of Civil and Commercial Laws in the DIFC Law No. 3 of 2004 apply in the jurisdiction of the Dubai International Financial Centre?
- `095cb50318776a3b8ef11769cd941775694c194924783ee31109c25e3306600e` `law_scope_or_definition` `free_text` `high`
  reason: Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented. This row fills an unavoidable route-composition gap. Theme: authority_or_administration. Risk tier: high.
  question: Who is responsible for administering the Employment Law and any Regulations made under it?
- `1097af38db84c4d507357bfbdcbbcc1de60a0ccb10752bad8091a75b8f53eb5c` `law_scope_or_definition` `free_text` `high`
  reason: Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented. This row fills an unavoidable route-composition gap. Theme: free_text. Risk tier: high.
  question: What is the minimum period for which a DIFC-incorporated General Partnership and a DIFC-incorporated Limited Liability Partnership must preserve their accounting records?
- `150d4428704ea7ce7452509bda9c25f4d242b2395114ed0ed59388b87660f218` `law_scope_or_definition` `free_text` `high`
  reason: Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented. This row fills an unavoidable route-composition gap. Theme: identity_lookup. Risk tier: high.
  question: Under the Operating Law - DIFC Law No. 7 of 2018, who is responsible for appointing and dismissing the Registrar?
- `30040cc854022341de6bb9ee7dc3e932d540666a1addda4750bf974ce9d9292f` `case_family` `name` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: compare_dimension. Risk tier: high.
  question: Which case has an earlier Date of Issue: CFI 016/2025 or ENF 269/2023?
- `331b267822eaa013b4a79d92f2ac5118052a57150df9a29d7d11c531f02d23cf` `case_family` `date` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: date. Risk tier: high.
  question: What is the Date of Issue of the document in case CFI 057/2025?
- `3c33f9a4de9bac177c65e3c3bd986ef05e527095e4c96aabbbed76599b727eb0` `case_family` `names` `high`
  reason: Selected to cover case identity, outcome/value, and case-cross-compare review patterns. Theme: identity_lookup. Risk tier: high.
  question: Who are listed as the claimants in the case documents for SCT 295/2025?
- `0a414e1d999bcde13b5dac055194ed52527555ac577946acef75372eaad360fa` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: What did the jury decide in case ENF 269/2023?
- `84941458c4ade946dae84cf5ebc4abf362a6f6e6fec835ba5c43ad2d3b4b14d7` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: Is there any information about parole hearings in case CFI 057/2025?
- `84a7c3564026e528c0a5e6a86a72447b4be016d6aa26ce5ce87843c58a975629` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: What was the plea bargain in case ARB 034/2025?
- `89f4b2e86cf7e48e185b9d5775d67e7c8a51beccbb20abce8dac2a1b0e80b723` `negative_or_unanswerable` `free_text` `high`
  reason: Selected to preserve adversarial/no-answer guardrail coverage. Theme: adversarial_no_answer. Risk tier: high.
  question: Were the Miranda rights properly administered in case ENF 269/2023?
