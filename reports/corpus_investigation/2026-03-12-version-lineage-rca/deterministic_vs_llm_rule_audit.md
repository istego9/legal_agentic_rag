# Deterministic vs LLM Rule Audit

## Scope

This memo covers the current **rules-first chunk/proposition pilot** path only:

- structural chunking and projection
- route-aware retrieval narrowing
- deterministic history/article intent resolution
- chunk semantic post-processing and assertion normalization
- proposition/direct-answer runtime helpers

It does **not** cover document-level metadata normalization or full-corpus rollout policy.

## Decision Principle

Use deterministic logic only when at least one of these is true:

1. the operation is identity/structure/provenance preserving
2. the operation is an exact normalization of already known fields
3. the operation is a narrow typed extraction with low semantic ambiguity
4. the operation is a safety guard that should prefer abstain over inference

Use LLM semantics when any of these is true:

1. modality depends on legal phrasing, not tokens
2. negation, carve-outs, or conditions can invert the answer
3. multiple propositions can live in one chunk
4. answerability itself requires semantic judgment, not lexical overlap

## Immediate Diagnosis

The current failing frozen queries show three classes of rule-based overreach:

1. `boolean_text_negation`
   - legal boolean questions are answered by token heuristics (`no`, `not`, `void`, `precludes`)
   - this is wrong for normative legal chunks
   - verdict: move to LLM semantic adjudication or force abstain

2. `number_abstain_conflict`
   - numeric extraction currently grabs unrelated numbers from chunk text
   - this is mostly a scoping/hygiene problem, not a reasoning problem
   - verdict: keep deterministic, but tighten unit-scoped extraction

3. `free_text_evidence_extract`
   - adversarial/no-answer questions still get answered from lexically similar but irrelevant chunks
   - this is an answerability problem, not a retrieval problem
   - verdict: use LLM no-answer verifier on top candidates

## Decision Table

| Layer | Current rule/check | File | Current role | Why it could stay deterministic | Why it should move to LLM | Verdict |
|---|---|---|---|---|---|---|
| Structure | Section-aware chunk boundaries (`Part`, `Chapter`, `Section`, `Article`, schedules, case order/disposition splits) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_processing.py` | creates chunk structure | pure structure, no semantic judgment | none | **Rule-based** |
| Structure | `parent_section_id`, `prev_chunk_id`, `next_chunk_id`, real offsets | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_processing.py` | navigation/provenance | identity and lineage only | none | **Rule-based** |
| Structure | `source_page_id`, page grounding, inherited document fields | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_processing.py`, `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/agentic_enrichment.py` | grounding | must remain auditable and exact | none | **Rule-based** |
| Structure | `LawChunkFacet` anchors (`part_ref`, `article_number`, `article_title`, `schedule_number`) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_processing.py` | legal structure | structural labels, not meaning | none | **Rule-based** |
| Structure | `CaseChunkFacet` anchors (`case_number`, `court_name`, `section_kind_case`) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_processing.py` | case structure | inherited or heading-based metadata | none | **Rule-based** |
| Retrieval | Route taxonomy selection (`article_lookup`, `history_lineage`, `cross_law_compare`, `single_case_extraction`, `no_answer`) | `/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/routers/qa.py` | runtime route split | cheap and stable when based on explicit cues | semantics of legal answer still not decided here | **Rule-based** |
| Retrieval | `law_article_lookup` intent parsing for explicit provision references | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_article_lookup.py` | extracts article/section/paragraph/clause ids | explicit identifiers parse well with regex | none | **Rule-based** |
| Retrieval | `law_history_lookup` relation-kind parsing (`amended_by`, `enacted_on`, `effective_from`, etc.) | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | history route narrowing | useful as coarse routing hint | relation semantics can be ambiguous | **Rule-based for routing only** |
| Retrieval | `_article_resolution_guard` / `_history_resolution_guard` no-silent-fallback blocks | `/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/routers/qa.py` | prevents hallucinated broad search | strong safety function | none | **Rule-based** |
| Retrieval | structural candidate matching from explicit article/section refs | `/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/routers/qa.py` | narrows article route | explicit matching is stable | none | **Rule-based** |
| Retrieval | article text marker recovery when projection lacks `article_number` | `/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/routers/qa.py` | low-structure backstop | still explicit text alignment, not legal meaning | none | **Rule-based** |
| Retrieval | compare-safe article narrowing (`same year`, `compare`, `versus` bypass) | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | avoids collapsing compare questions | query-shape guard only | none | **Rule-based** |
| Retrieval | history retrieval hints (`doc_type_priority`, lineage expansion, notice priority) | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | retrieval shaping | good as heuristic recall hints | not sufficient for final answer | **Rule-based for retrieval only** |
| Semantics | semantically rich chunk gating | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | decides which chunks go to LLM | low-cost triage | can miss subtle chunks, but acceptable as recall-first heuristic | **Rule-based** |
| Semantics | relation alias normalization (`invalidates -> is_void`, `comes_into_force_on -> governs`) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | canonicalizes LLM output | pure schema normalization | none | **Rule-based** |
| Semantics | modality alias normalization (`required -> obligation`, etc.) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | schema normalization | pure canonicalization | none | **Rule-based** |
| Semantics | automatic `is_void -> boolean true` direct-answer stub | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | seeds boolean direct answer | simple only in non-conditional contexts | dangerous when clause includes exceptions or carve-outs | **LLM or abstain** |
| Semantics | derived legislative `conditions` / `exceptions` from cue windows (`subject to`, `unless`, `except`, etc.) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | patches incomplete LLM outputs | useful as safety backfill | exact legal scope of conditions is semantic | **Hybrid: keep as safety backfill, not final truth** |
| Semantics | case operative amount derivation from money spans in order chunks | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | fills missing amount proposition | numerics near operative verbs are scoping-safe | if chunk mixes background and order, semantics matter | **Hybrid: deterministic backfill allowed, final proposition LLM-owned** |
| Semantics | case interest consequence derivation from `% + interest + condition` patterns | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` | fills missing interest proposition | stable if scoped to conditional sentence | legal effect still semantic | **Hybrid: deterministic backfill allowed, final proposition LLM-owned** |
| Semantics | chunk semantic extraction itself (`provision_kind`, propositions, conditions, exceptions) | `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/chunk_semantics.py` with prompts | legal meaning | none; this is exactly semantic interpretation | legal semantics, negation, carve-outs, multi-proposition chunks | **LLM** |
| Direct answer | proposition rerank by token overlap | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | ranks candidate propositions | cheap and good as secondary ranking signal | not sufficient to infer legal truth | **Rule-based for ranking only** |
| Direct answer | typed-only eligibility (`boolean`, `number`, `date`, `name`, `names`) | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | output safety | pure policy gate | none | **Rule-based** |
| Direct answer | one-instrument / one-page / one-dominant-assertion guard | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | safety gate | explicit conservative gate | none | **Rule-based** |
| Direct answer | no direct-answer when `conditions` / `exceptions` present | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | safety gate | exactly the right abstain behavior | none | **Rule-based** |
| Direct answer | `_extract_number_from_candidates()` for `%`, `within X days`, money spans | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | typed shortcut | stable for percent/days when scoped | current money path still noisy if candidate pool is wrong | **Rule-based for `%/days`, tighten for money** |
| Direct answer | `_extract_name_from_candidates()` for court names | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/proposition_layer.py` | typed shortcut | inherited metadata is stable | none | **Rule-based** |
| Deterministic solver | `_solve_boolean()` lexical entailment/negation | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | answers boolean without LLM | acceptable for non-legal factual booleans | fails hard on legal norms (`void`, `nothing precludes`, conditional permissions) | **LLM for legal booleans; deterministic only for factual booleans** |
| Deterministic solver | `_extract_same_year_boolean()` | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | compare years across laws/cases | explicit dates/years, low ambiguity | none | **Rule-based** |
| Deterministic solver | `_solve_number()` generic numeric extraction from candidates | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | answers numeric lookups | useful when question unit is explicit | current implementation leaks article numbers, years, ids, hashes | **Rule-based but must be narrowed to unit-scoped extraction** |
| Deterministic solver | `_solve_date()` generic date extraction | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | answers dates | explicit date normalization is safe | none | **Rule-based** |
| Deterministic solver | `_solve_name()` / `_solve_names()` | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | entity outputs | inherited/canonical names are stable | party-role inference from local chunk alone can be semantic | **Rule-based for inherited names only** |
| Deterministic solver | `_solve_free_text()` top extract return | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | extractive fallback | useful only for very short, obviously grounded asks | unsafe on adversarial/no-answer and semantically mismatched chunks | **LLM verifier or abstain for nontrivial free-text** |
| Deterministic solver | low-overlap abstain guard | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | blocks nonsense answers | good safety default | short queries need limited exception | **Rule-based** |
| Deterministic solver | short-query extract exception | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | avoids over-abstaining on tiny queries | practical for short operational prompts | still unsafe if used broadly | **Rule-based, but narrow** |
| History solver | `_candidate_matches_law_anchor()` / `_candidate_matches_notice_anchor()` | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | narrows target instrument | explicit anchor alignment | none | **Rule-based** |
| History solver | `_extract_scoped_effective_dates()` | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | scopes `effective_from` by local phrase | very good deterministic scoping | none | **Rule-based** |
| History solver | `_solve_date()` in history route | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | typed date answer | explicit anchored dates are safe | none | **Rule-based** |
| History solver | `_POSITIVE_BOOLEAN_PATTERN` / `_NEGATIVE_BOOLEAN_PATTERN` in history route | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/law_history_lookup.py` | boolean application/jurisdiction answers | can work for narrow factual/legal-status prompts | still risky on nuanced legal applicability | **Hybrid: rule-based only for narrow status questions, otherwise LLM/adjudicator** |
| Source selection | `choose_used_sources_with_trace()` coverage rules | `/Users/artemgendler/dev/legal_agentic_rag/services/runtime/solvers.py` | page selection and trace | provenance/coverage only | none | **Rule-based** |

## Explicitly Wrong to Keep Deterministic

These should not remain primary deterministic answer rules:

| Failure class | Current path | Why wrong |
|---|---|---|
| legal normative booleans | `_solve_boolean()` -> `boolean_text_negation` | token negation is not legal interpretation |
| conditional permissions / carve-outs | deterministic boolean shortcut | `unless`, `subject to`, `except`, `nothing precludes` need semantic adjudication |
| adversarial/no-answer free text | `_solve_free_text()` -> `free_text_evidence_extract` | lexical overlap is not answerability |

## Explicitly Fine to Keep Deterministic

These are not the problem and should remain rule-based:

- page/document/chunk ids
- source page provenance
- article/section/paragraph anchors
- route gating and no-silent-fallback guards
- compare/date/year extraction when explicit
- court name / case number / law number inheritance
- alias normalization of LLM outputs

## Recommended Migration

### Move to LLM semantic layer

1. legal boolean adjudication for article/history questions
2. no-answer verifier for free-text/adversarial questions
3. final proposition truth for conditional/exception-bearing clauses

### Keep deterministic, but tighten

1. number extraction
   - unit-scoped only: `hours`, `months`, `days`, `business days`, `years`
   - sentence-scoped only
   - exclude article numbers / years / ids / hashes

2. history factual date/name extraction
   - only when target anchor and date span are explicit

3. proposition/direct-answer guards
   - keep narrow and typed-only

## Bottom Line

The current mistake is not “too many rules” in general. The mistake is using deterministic rules for **semantic adjudication**.

The correct split is:

- **Deterministic**:
  - structure
  - provenance
  - explicit identifiers
  - routing
  - typed extraction from already grounded proposition/text spans
  - safety guards

- **LLM**:
  - legal meaning
  - normative boolean judgment
  - condition/exception preservation
  - answerability on adversarial/no-answer free-text

If we keep this split, conditional legislative boolean questions and adversarial free-text stop being regex problems and become what they actually are: semantic interpretation problems.
