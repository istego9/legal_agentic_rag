# Competition Presentation Notes (2026-03-09)

## Purpose
- Зафиксировать rules extracted from the contest presentation screenshots.
- Сверить текущий repository state с этими rules без догадок.
- Сформировать explicit action items для score-critical gaps.

## Extracted Rules
### Final score formula
- `Total = (0.7 * S_det_avg + 0.3 * S_asst_avg) * G_avg * T_avg * F_avg`.
- `S_det_avg` = средний score по deterministic questions.
- `S_asst_avg` = средний LLM-as-judge score по `free_text`.
- `G_avg` = retrieval / grounding quality across all questions.
- `T_avg` = telemetry completeness modifier across all questions.
- `F_avg` = TTFT modifier across all questions.

### Answer type split
- Deterministic block = `70%`.
- Free-text block = `30%`.

### Deterministic answer types
- `number`
- `boolean`
- `name`
- `names`
- `date`
- Special answer: `null`

### Deterministic semantics
- `null` is allowed for all deterministic answer types when the information is absent from the corpus and cannot be found or inferred.
- `number`: numerical tolerance, slide shows `abs(predicted - actual) < 0.01 * actual`.
- `boolean`: exact match.
- `name`: exact match.
- `names`: Jaccard index, slide shows `len(A ∩ B) / len(A ∪ B)`.
- `date`: exact match in ISO 8601.
- `N/A (all types)`: exact match, slide shows `actual is None ? predicted is None`.

### Free-text contract
- Format: coherent text of `1-3 paragraphs`.
- Max length: `280 characters`.
- Purpose: evaluate the model's ability to assimilate multiple facts into one coherent answer and explain them in assistant-like UX, not only list facts.

### Question families shown in the presentation
- `single-document` -> primary answer types: `number`, `boolean`, `name`, `names`
- `clause-analysis` -> primary answer types: `free_text`, `names`
- `multi-document` -> primary answer type: `free_text`
- `negative` -> primary answer types: `number`, `boolean`, `name`, `names`, `free_text`
- `adversarial` -> primary answer type: `free_text`
- `uncertainty` -> primary answer type: `free_text`

### Free-text judge dimensions
- Correctness
- Completeness
- Grounding
- Appropriate confidence
- Clarity and relevance
- Slide formula: `Judge_Score = sum(count of 1s) / sum(count of 1s + count of 0s)`.
- Slide also mentions an LLM cascade for judging: `Gemini Flash 3`, `Claude Haiku`, `GPT 5.2`.

### Grounding metric
- Precision = `|predicted ∩ gold| / |predicted|`
- Recall = `|predicted ∩ gold| / |gold|`
- Final grounding score uses `F-beta` with `beta = 2.5`
- Organizer example implies recall is weighted more heavily than precision.

### TTFT modifier
- `< 1.0 sec` -> `1.05`
- `1.0-2.0 sec` -> `1.02`
- `2.0-3.0 sec` -> `1.00`
- `3.0-5.0 sec` -> `0.95`
- `> 5.0 sec` -> `0.85`

### Telemetry modifier
- Presentation slide shows `T_avg` range `[0.90, 1.00]`.
- The screenshots provided do not show the exact per-question telemetry scoring rule.

## Repository Fit Review
### Strong alignment
- `datasets/official_fetch_2026-03-11/questions.json` is the canonical public-question set for current baselines and review flows.
- Shared contracts already match the six contest answer types in [`contracts.py`](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py).
- Page-level grounding/export semantics are frozen through `PageRef.source_page_id = pdf_id_page` and submission export uses page ids only.
- Default scorer constants already match the presentation for grounding and TTFT:
  - `beta = 2.5`
  - TTFT curve `1.05 / 1.02 / 1.00 / 0.95 / 0.85`
- QA runtime already enforces empty-source semantics for abstained answers by clearing `used_source_page_ids` and returning `sources=[]` for abstained responses.
- Runtime already follows deterministic-first handling for `boolean`, `number`, `date`, `name`, and `names`.

### Partial alignment
- Eval and experiments already slice by `answer_type`, `route_family`, `document_scope`, `corpus_domain`, and `temporal_scope`, which is useful, but this is not yet the same as the contest question-family taxonomy shown in the presentation (`single-document`, `clause-analysis`, `negative`, `uncertainty`, etc.).
- Telemetry is captured and persisted, and a shadow OTel mapping exists, but the repository still assumes a locally defined telemetry-completeness policy rather than an organizer-confirmed `[0.90, 1.00]` modifier contract.

### Material gaps
- Current scorer does **not** implement the presentation's weighted answer score split. [`services/eval/engine.py`](/Users/artemgendler/dev/legal_agentic_rag/services/eval/engine.py#L894) computes one global `answer_score_mean`, and [`services/eval/engine.py`](/Users/artemgendler/dev/legal_agentic_rag/services/eval/engine.py#L902) multiplies it directly into `overall_score`.
- Free-text runtime path is not grounded enough. [`qa.py`](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/routers/qa.py#L442) builds the LLM call from route name, scoring policy, and question text only; it does not pass an evidence pack into the synthesis call.
- The free-text format contract from the slides is not enforced in runtime output. There is no explicit `280`-character cap or `1-3 paragraphs` constraint on QA responses.
- `services/runtime/README.md` is stale relative to the code: it still says `article_lookup_recall_v1` and says other routes use the default profile, while runtime code already uses `article_lookup_recall_v2`, `single_case_extraction_compact_v2`, and `history_lineage_graph_v1`.

## Action Items
- [ ] Update contest-emulation scoring so `S` is computed as `0.7 * S_det_avg + 0.3 * S_asst_avg`, not as a single global answer mean.
- [ ] Extend scorer payloads, compare reports, and experiment gates with explicit `S_det_avg` and `S_asst_avg` fields.
- [ ] Add scorer regression tests for the weighted `70/30` formula and for mixed deterministic/free-text runs.
- [ ] Confirm organizer telemetry semantics; until confirmed, keep current telemetry policy versioned and marked as provisional.
- [ ] Enforce free-text answer formatting in runtime/export:
  - `1-3 paragraphs`
  - `<= 280 characters`
- [ ] Change free-text LLM synthesis to consume a compact evidence pack rather than the bare question.
- [ ] Add contest-family tagging or derived slices for:
  - `single-document`
  - `clause-analysis`
  - `multi-document`
  - `negative`
  - `adversarial`
  - `uncertainty`
- [ ] Update stale docs so runtime profile descriptions match the actual code paths.

## Working Verdict
- Архитектурно направление в целом правильное: `page-level grounding`, `deterministic-first`, explicit `no_answer`, scorer/reporting discipline и TTFT awareness хорошо совпадают с условиями.
- Самые опасные расхождения сейчас не в ingest или contracts, а в `contest-emulation math` и `free_text runtime discipline`.
- До фикса weighted scorer и grounded free-text synthesis нельзя считать repo полностью aligned with the presentation rules.
