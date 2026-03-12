# Execution Plan: Chunk Processing and Proposition Layer

## Objective

Make the corpus chunk layer production-ready for:

- fast hybrid retrieval
- grounded answer generation
- partial direct answering without LLM on simple lookup questions
- auditable semantic interpretation of legal text

This plan explicitly starts from the current state:

- document-level corpus is in a clean metadata state
- page-level grounding remains canonical
- chunk-level processing exists, but is still a bootstrap scaffold

## Why This Plan Exists

The current chunk layer is not yet suitable as the main semantic retrieval unit.

Current limitations:

- chunk splitting is still length-based rather than structure-based
  - [ingest.py](/Users/artemgendler/dev/legal_agentic_rag/services/ingest/ingest.py#L357)
- chunk structural fields are mostly placeholders
  - `parent_section_id=None`
  - `prev_chunk_id=None`
  - `next_chunk_id=None`
  - `heading_path=[doc_type, parse_policy]`
  - [ingest.py](/Users/artemgendler/dev/legal_agentic_rag/services/ingest/ingest.py#L1235)
  - [ingest.py](/Users/artemgendler/dev/legal_agentic_rag/services/ingest/ingest.py#L1290)
- chunk enrichment completed for all chunks, but in `rules_only` mode rather than LLM semantic mode
  - [prepare_report.azure_gpt5mini_full_corpus_v3_titles.json](/Users/artemgendler/dev/legal_agentic_rag/reports/competition_runs/prepare_report.azure_gpt5mini_full_corpus_v3_titles.json#L1161)

This means the corpus is ready on the document layer, but not yet ready on the chunk semantic layer.

## Frozen Invariants

These invariants are not changed by this plan:

- page-level grounding remains canonical
- `source_page_id = pdf_id_page`
- paragraphs/chunks remain retrieval units, not submission export units
- public document/page contracts remain additive-only unless separately versioned
- every normalized document field and every semantic chunk assertion must retain page-level provenance
- no field promoted to canonical truth may lose the page window or source page ids used to derive it

Source of truth:

- [contracts.py](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L328)

## Scope

In scope:

- structural chunking redesign
- deterministic chunk anchors and navigation
- chunk-level lexical retrieval projections
- chunk-level semantic assertion extraction
- chunk-level evaluation and audit reports
- retrieval use of chunk assertions and structural anchors
- simple direct-answer path for narrow lookup questions

Out of scope:

- changing page-level submission grounding
- replacing the document metadata pipeline
- introducing a new public API contract immediately
- dense-only retrieval as a primary strategy
- freeform LLM summarization as the source of truth

## Data Flow Map

### Current

`source PDF` -> parser text -> page rows -> length-based paragraph chunks -> chunk projections -> rules-only enrichment -> retrieval/runtime

### Target

`source PDF`
-> `Structural Chunker V2`
-> `ChunkBase + typed chunk facets`
-> `Lexical Retrieval Projection`
-> `Typed Semantic Assertion Extraction`
-> `Assertion-backed Retrieval Projection`
-> `Runtime retrieval + optional direct-answer shortcut`

## Canonical Layers

### Layer 1. Structural Chunk Layer

This is deterministic and parser-backed.

Owned fields are the existing chunk contracts:

- [ChunkBase](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1110)
- [ParagraphChunk](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L411)
- typed facets:
  - [LawChunkFacet](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1159)
  - [RegulationChunkFacet](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1178)
  - [EnactmentNoticeChunkFacet](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1193)
  - [CaseChunkFacet](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1207)

This layer must answer:

- where is this chunk in the document?
- what article / part / chapter / section / schedule / case section does it belong to?
- what are its neighboring chunks?
- what document-level identity does it inherit?
- which source page ids and page numbers support each inherited field?

### Layer 2. Lexical Retrieval Layer

This is also deterministic.

Owned fields:

- [ChunkSearchDocument](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1239)

This layer must answer:

- which exact legal terms does this chunk contain?
- which normalized references are attached to it?
- how should it be surfaced to lexical and hybrid retrieval?

### Layer 3. Semantic Assertion Layer

This is LLM-assisted and grounded.

Owned fields:

- [ChunkOntologyAssertion](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L484)
- [DocumentOntologyView](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L504)

This layer must answer:

- what legal propositions are expressed in this chunk?
- what is prohibited, permitted, required, void, held, ordered, or conditioned?
- what are the conditions, exceptions, and cross-references?
- which page ids and chunk offsets support each proposition?

### Layer 4. Proposition Retrieval Layer

This plan treats proposition retrieval as an internal derived projection, not a new public contract.

In iteration 1-2 it should be materialized from:

- chunk assertions
- chunk structural anchors
- chunk lexical projection

This layer must answer:

- which atomic proposition is most relevant to a query?
- can a question be answered by one proposition or does it require multiple chunks?

## Deterministic vs LLM Boundary

### Deterministic only

The following should never be model-owned:

- `document_id`
- `pdf_id`
- `page_id`
- `source_page_id`
- `doc_type`
- `chunk_id`
- `chunk_index_on_page`
- `char_start`
- `char_end`
- `prev_chunk_id`
- `next_chunk_id`
- `parent_section_id`
- `structural_level`
- `heading_path`
- `part_ref`
- `chapter_ref`
- `section_ref`
- `article_number`
- `article_title`
- `schedule_number`
- `case_number`
- `court_name`
- `court_level`
- `decision_date`
- deterministic lexical refs
- document field provenance maps
- chunk provenance maps
- page windows supplied to LLM

### LLM-owned

The following should be model-owned but schema-bound:

- semantic `provision_kind` when meaning is not purely structural
- chunk modality where negation and carve-outs matter
- atomic legal assertions
- conditions and exceptions
- one short dense retrieval paraphrase

### Provenance rule

The model may interpret text, but it does not own provenance.

Deterministic processing must attach:

- `source_page_ids`
- source page numbers
- chunk `char_start`
- chunk `char_end`
- evidence field names

This applies to:

- document-level normalized metadata inherited into chunks
- semantic chunk assertions
- proposition retrieval projections

If a value does not have page provenance, it is not promoted beyond processing state.

## Why Negation Must Be LLM-Owned

Employment Law Article 11 is the canonical example.

The same local text contains:

- invalidity of waiver clauses for statutory minimums
- explicit allowance for more favourable employer terms
- conditional permission for employee waiver in settlement/termination agreements

So the chunk cannot be flattened to one tag like `prohibition`.

Reference note:

- [chunk_layer_strategy_and_llm_pilot.md](/Users/artemgendler/dev/legal_agentic_rag/reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_layer_strategy_and_llm_pilot.md)

Pilot evidence:

- [chunk_llm_pilot.json](/Users/artemgendler/dev/legal_agentic_rag/reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_llm_pilot.json)

## Target Chunk Representation

### Laws / Regulations / Notices

For each chunk we want:

- document identity inherited from the normalized document row
- structural anchors:
  - `part_ref`
  - `chapter_ref`
  - `section_ref`
  - `article_number`
  - `article_title`
  - `schedule_number`
- semantic local representation:
  - one or more atomic assertions
  - each with modality, polarity, conditions, exceptions, and citations

Example shape for a law chunk, represented through existing structures:

- `ChunkBase`:
  - structural anchors and lexical search fields
- `LawChunkFacet`:
  - article and provision metadata
- `ChunkOntologyAssertion[]`:
  - one chunk may yield multiple assertions
- `processing.evidence`:
  - page ids and offsets for inherited document fields
  - page ids and offsets for each assertion/proposition

### Cases

For each chunk we want:

- case identity inherited from the normalized document row
- structural anchors:
  - `case_number`
  - `court_name`
  - `court_level`
  - `section_kind_case`
- semantic local representation:
  - issue / order / holding / disposition / costs / timing assertions

## Retrieval Design

The target runtime retrieval loop should be:

1. deterministic query parse
2. deterministic filter narrowing
3. hybrid lexical + semantic chunk ranking
4. proposition-level reranking
5. local context expansion
6. answer generation only if needed

### Step 1. Query parse

Deterministically try to extract:

- `doc_type`
- `article_number`
- `law_number`
- `case_number`
- `court_name`
- exact legal terms
- actor labels
- temporal or current-version intent

### Step 2. Filter narrowing

Use current search filters:

- [SearchFilters](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L1291)

Main target filters:

- `doc_type`
- `law_number`
- `article_number`
- `case_number`
- `court_name`
- `version_lineage_id`
- `canonical_concept_id`

### Step 3. Hybrid ranking

Use:

- exact terms / keywords
- `heading_path`
- chunk lexical refs
- dense semantic match on short chunk/proposition summaries

This matches OpenAI retrieval guidance:

- hybrid keyword + semantic search improves retrieval relevance
- ranking weights should be tuned rather than relying on embeddings alone

Primary references:

- [Retrieval ranking](https://developers.openai.com/api/docs/guides/retrieval/#ranking)
- [File search how it works](https://developers.openai.com/api/docs/assistants/tools/file-search/#how-it-works)

### Step 4. Proposition reranking

For top candidate chunks, compare query intent against:

- proposition subject
- predicate
- object
- conditions / exceptions
- citations

### Step 5. Context expansion

Do not expand to the full document.

Expand only:

- the matched chunk
- its parent section heading / anchor
- `prev_chunk_id`
- `next_chunk_id`

## Direct Answer Shortcut

This plan includes a direct-answer path for narrow lookup questions.

Use direct answering without LLM only if:

- one high-confidence proposition dominates
- citation anchor is explicit
- no conflicting propositions are returned
- the question is lookup-like:
  - boolean
  - amount
  - deadline
  - direct permission/prohibition/invalidity

Example answer style:

- `Yes, but only if ...`
- `No, except where ...`
- `The clause is void unless ...`

If multiple propositions or conflicts are present, fall back to answer synthesis with LLM.

## Processing Stages

## Iteration 0. Freeze Baseline and Build Evaluation Fixtures

### Tasks

- [ ] Freeze the current full-corpus document snapshot as the chunk baseline.
- [ ] Build an explicit chunk pilot fixture set:
  - 3 laws
  - 2 cases
- [ ] Add query fixtures for:
  - article lookup
  - conditional permission
  - invalidity / void clause
  - costs order
  - interest / payment deadline
- [ ] Add provenance fixtures for:
  - document-level field page windows
  - chunk-level assertion page grounding
- [ ] Add a negative/exception fixture anchored on Employment Law Article 11.

### Validation

- [ ] Pilot fixture set is reproducible from the current corpus bundle.
- [ ] Each fixture has expected article/case anchors and expected answer topology.
- [ ] Each fixture declares expected page provenance for key fields and target assertions.

## Iteration 1. Structural Chunker V2

### Tasks

- [ ] Replace length-only chunk splitting with structure-aware chunk splitting.
- [ ] For laws/regulations/notices, split by:
  - part
  - chapter
  - section
  - article
  - sub-item
  - schedule item
- [ ] For cases, split by:
  - caption
  - heading / court section
  - numbered reasoning paragraphs
  - order section
  - disposition / costs / timing section
- [ ] Populate:
  - `char_start`
  - `char_end`
  - `prev_chunk_id`
  - `next_chunk_id`
  - `parent_section_id`
  - `heading_path`
  - `structural_level`
- [ ] Persist deterministic provenance payload for each chunk:
  - `source_page_id`
  - page number
  - offsets
  - inherited document field page windows

### Validation

- [ ] No structural chunk crosses article boundaries on pilot laws.
- [ ] No order/disposition chunk is merged into the case caption chunk on pilot cases.
- [ ] Offsets are populated for all pilot chunks.
- [ ] All pilot chunks retain non-null source page provenance.

### Rollback

- Keep the current splitter behind a flag until structural tests stabilize.

## Iteration 2. Deterministic Typed Chunk Anchors

### Tasks

- [ ] Populate `LawChunkFacet` from structural anchors:
  - `part_ref`
  - `chapter_ref`
  - `section_ref`
  - `article_number`
  - `article_title`
  - `schedule_number`
  - `schedule_title`
  - `definition_term`
- [ ] Populate `CaseChunkFacet` from structural anchors and normalized case metadata:
  - `case_number`
  - `court_name`
  - `court_level`
  - `decision_date`
  - `section_kind_case`
  - party and judge inheritance where explicit
- [ ] Populate `ChunkSearchDocument` with inherited document identity and structural anchors.
- [ ] Attach per-field provenance for inherited document metadata used in chunk projections:
  - title
  - citation
  - law/case number
  - court name
  - decision/effective dates

### Validation

- [ ] Article lookup queries can be narrowed by deterministic filters alone.
- [ ] The Employment Law Article 11 chunk carries `article_number=11`.
- [ ] Coinmena order chunk carries `case_number=CFI 067/2025` and normalized court.
- [ ] No inherited non-null document field in pilot chunks lacks page provenance.

## Iteration 3. Lexical Retrieval Projection V2

### Tasks

- [ ] Rebuild `retrieval_text` so it includes:
  - document identity
  - structural path
  - local chunk text
- [ ] Normalize `exact_terms`
- [ ] Normalize `search_keywords`
- [ ] Improve `rank_hints`
- [ ] Improve `answer_candidate_types`
- [ ] Add query-side deterministic synonym normalization where possible.
- [ ] Carry provenance references through retrieval projections so top hits can be audited without re-derivation.

### Validation

- [ ] Lookup queries improve on lexical-only pilot search.
- [ ] Structural anchors materially improve precision before embeddings are used.
- [ ] Top retrieval hits expose their supporting page ids and offsets in evaluation output.

## Iteration 4. Typed Semantic Assertion Extraction

### Tasks

- [ ] Add `law_chunk_semantics_v1` prompt.
- [ ] Add `case_chunk_semantics_v1` prompt.
- [ ] Use strict structured output.
- [ ] Use GPT-5-mini with low or minimal reasoning effort only where evals justify it.
- [ ] Restrict extraction to semantically rich chunks:
  - definitions
  - obligations
  - prohibitions
  - permissions
  - invalidity / exception clauses
  - orders
  - holdings
  - dispositions
  - cost and timing rulings
- [ ] Attach assertion-level provenance:
  - source page ids
  - local offsets
  - source chunk id
  - citation refs used in the assertion

### Validation

- [ ] Employment Law Article 11 pilot preserves:
  - invalidity rule
  - favourable-terms permission
  - conditional waiver permission
- [ ] Case order pilot preserves:
  - amount
  - deadline
  - interest consequence
- [ ] Assertions remain grounded to source chunk/page citations.
- [ ] No assertion is emitted without page provenance.

### Rollback

- Keep assertion extraction behind a feature flag and preserve deterministic chunk projections.

## Iteration 5. Proposition Retrieval Projection

### Tasks

- [ ] Derive proposition-level retrieval rows from chunk assertions.
- [ ] Index:
  - subject
  - relation / predicate
  - object
  - modality
  - conditions
  - exceptions
  - citations
  - dense paraphrase
- [ ] Add proposition-to-chunk linkage.
- [ ] Keep this projection internal and additive in iteration 1.
- [ ] Preserve provenance in proposition projection:
  - source page ids
  - source chunk id
  - source assertion id

### Validation

- [ ] Query `can employee waive rights` hits the conditional waiver proposition before generic article text blobs.
- [ ] Query `void waiver clause` hits the invalidity proposition before the permission proposition.
- [ ] Proposition hits can be traced back to source page ids and chunk offsets in a single step.

## Iteration 6. Chunk Evaluation Harness

### Tasks

- [ ] Build structural chunk quality report:
  - chunk length distribution
  - missing offsets
  - missing parent links
  - missing prev/next
  - chunks crossing section boundaries
  - orphan chunks
- [ ] Build semantic chunk quality report:
  - chunks with zero assertions despite semantic richness
  - contradictory assertions
  - missing conditions / exceptions on conditional rules
  - missing citations
- [ ] Build retrieval evaluation:
  - article lookup recall@k
  - proposition hit rate@k
  - direct-answer eligibility rate
  - direct-answer correctness on pilot set
- [ ] Build latency report:
  - query parse time
  - filter time
  - lexical rank time
  - semantic rank time
  - answer generation time
- [ ] Build provenance coverage report:
  - document-field provenance coverage
  - assertion provenance coverage
  - proposition provenance coverage
  - top-hit provenance visibility

### Validation

- [ ] Quality report is generated for pilot set before any full-corpus rollout.
- [ ] Retrieval eval shows whether proposition layer is helping or adding noise.
- [ ] Provenance coverage report shows zero non-null semantic outputs without page grounding.

## Evaluation Rubric

### Structural quality

- [ ] 100% pilot chunks have valid offsets
- [ ] 100% pilot chunks have correct parent/prev/next links
- [ ] 0 cross-article chunks on pilot laws
- [ ] 0 caption/order merges on pilot cases
- [ ] 100% pilot chunks have source page provenance

### Semantic quality

- [ ] conditional propositions preserve conditions
- [ ] negative statements preserve polarity
- [ ] exceptions remain explicit
- [ ] citations remain attached
- [ ] 100% emitted assertions have page-grounded provenance

### Retrieval quality

- [ ] article lookup recall improves
- [ ] top-hit precision improves for boolean legal lookup questions
- [ ] direct-answer shortcut does not answer conflicted queries incorrectly
- [ ] top retrieval hits expose supporting page ids and offsets

### Latency quality

- [ ] retrieval path stays near sub-second before answer synthesis
- [ ] direct-answer path stays materially below answer-synthesis latency

### Auditability quality

- [ ] document-level inherited fields retain field-level page provenance
- [ ] proposition rows retain source assertion and page provenance
- [ ] direct answers are explainable from a single grounded proposition bundle

## Implementation Order

Do not parallelize these large steps initially.

Recommended order:

1. freeze pilot fixtures
2. structural chunker
3. deterministic anchors
4. lexical retrieval projection
5. law semantic assertions
6. case semantic assertions
7. proposition retrieval
8. evaluation harness
9. provenance hardening pass
10. 5-document pilot run

## Deliverables

- [ ] `Structural Chunker V2`
- [ ] chunk anchor fill for law and case facets
- [ ] lexical retrieval projection v2
- [ ] typed semantic chunk prompts
- [ ] proposition retrieval projection
- [ ] chunk quality report
- [ ] retrieval pilot report
- [ ] direct-answer pilot report
- [ ] provenance coverage report
- [ ] audit checklist with explicit remaining risks

## Action Items

### Planning and fixtures

- [ ] Freeze the 5-document pilot bundle and frozen query set.
- [ ] Freeze expected provenance annotations for key document fields and pilot assertions.

### Deterministic chunk processing

- [ ] Implement and validate structural chunker v2 for laws and cases.
- [ ] Fill deterministic chunk anchors, navigation links, and offsets.
- [ ] Persist document-field provenance into chunk processing state.

### Semantic processing

- [ ] Implement typed law and case chunk semantic prompts.
- [ ] Emit assertion-level provenance alongside every semantic assertion.
- [ ] Project semantic assertions into internal proposition retrieval rows.

### Retrieval and direct answer

- [ ] Add proposition-aware reranking over hybrid chunk retrieval.
- [ ] Add guarded direct-answer shortcut with provenance checks.

### Evaluation and audit

- [ ] Generate structural, semantic, retrieval, direct-answer, and provenance coverage reports.
- [ ] Compare pilot output against frozen query expectations and provenance expectations.
- [ ] Record remaining failure modes before any wider rollout.
