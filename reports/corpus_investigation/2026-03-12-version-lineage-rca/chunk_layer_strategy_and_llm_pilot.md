# Rules-First Chunk/Proposition Pilot Strategy

## Scope

This note defines:

- what should be computed deterministically for chunk preparation
- what should be extracted by LLM
- what provenance must be attached deterministically
- what was observed on a two-document Azure GPT-5-mini pilot
- which v2 policy constraints now apply to semantic and direct-answer handling

The current full-corpus metadata snapshot is clean at the document layer, but the chunk layer is still a bootstrap scaffold rather than a final semantic retrieval layer.

## Policy Updates From Revised Chunk Strategy v2

The pilot continues under these constraints:

- direct-answer remains typed-only in v1
- free-text direct-answer is disabled
- proposition retrieval remains internal-only
- no full-corpus proposition rollout is allowed until pilot gates are green in consecutive runs
- regulation, notice, and adversarial fixtures must be added before broader approval

## Current State

- Chunk grounding invariants remain page-level:
  - `competition_source_unit=page`
  - `paragraph_is_retrieval_unit_only`
  - source: [contracts.py](/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/contracts.py#L328)
- Current chunking is still length-based:
  - `_split_paragraphs(..., max_chunk=900)`
  - source: [ingest.py](/Users/artemgendler/dev/legal_agentic_rag/services/ingest/ingest.py#L357)
- Current chunk enrichment completed for the full corpus, but in `rules_only` mode:
  - `llm_enabled=false`
  - `chunk_count=1932`
  - `processed_chunk_count=1932`
  - source: [prepare_report.azure_gpt5mini_full_corpus_v3_titles.json](/Users/artemgendler/dev/legal_agentic_rag/reports/competition_runs/prepare_report.azure_gpt5mini_full_corpus_v3_titles.json#L1161)

## Important Correction: Negation And Carve-Outs

The earlier shorthand interpretation of Employment Law Article 11 as a simple prohibition is wrong.

Actual text from Employment Law Article 11:

- `Article 11(1)` voids waiver clauses that attempt to waive minimum statutory requirements, except where expressly permitted under the law.
- `Article 11(2)(a)` says nothing in the law precludes more favourable terms for employees.
- `Article 11(2)(b)` says nothing in the law precludes an employee from waiving rights under the law by written agreement in termination/dispute resolution, subject to Article 66(13) and additional conditions.

This means:

- the chunk contains multiple norms
- one of them is invalidity/prohibition-like
- one is explicit allowance
- one is conditional permission

So modality cannot be assigned safely by surface cues like `waiver` or `no waiver` alone.

## What Must Be Deterministic

These fields should be computed on our side before any LLM extraction:

### Document inheritance

- `document_id`
- `pdf_id`
- `page_id`
- `source_page_id`
- `doc_type`
- document title and citation already normalized upstream
- current-version and lineage status
- field-level page provenance for inherited document metadata

Reason:
- they are canonical corpus identity, not interpretation
- the page window for each inherited field must remain auditable

### Structural chunk context

- `chunk_id`
- `chunk_index_on_page`
- `char_start`
- `char_end`
- `prev_chunk_id`
- `next_chunk_id`
- `parent_section_id`
- `structural_level`
- `heading_path`
- `heading_path_full`
- `section_kind` candidate from structure
- chunk-level provenance payload:
  - `source_page_ids`
  - source page numbers
  - `char_start`
  - `char_end`

Reason:
- this should come from parser/layout and section splitting
- LLM should consume this context, not invent it

### Typed structural anchors

For laws/regulations/notices:

- `part_ref`
- `chapter_ref`
- `section_ref`
- `article_number`
- `article_title`
- `schedule_number`
- `schedule_title`

For cases:

- `case_number`
- `court_name`
- `court_level`
- `decision_date`
- `section_kind_case` candidate

Reason:
- these are usually heading/path facts and should be parser- or rules-derived wherever possible
- they are perfect filter keys for fast retrieval

### Lexical retrieval scaffold

- exact citation strings
- normalized keywords
- deterministic article/law/case refs
- queryable aliases and normalized actor labels already available from document context
- page provenance references carried into retrieval projections

Reason:
- these feed low-latency hybrid retrieval and should not depend on generation

## What Should Be LLM-Owned

These fields should be produced by LLM over already-structured chunks:

### Normative / semantic representation

- `provision_kind` when interpretation is semantic rather than purely structural
- whether a chunk is:
  - obligation
  - prohibition
  - permission
  - invalidity rule
  - exception
  - conditional carve-out
  - factual holding
  - operative order
  - reasoning

### Assertion extraction

Use `ChunkOntologyAssertion`-style atomic statements:

- `subject`
- `relation`
- `object`
- `modality`
- `conditions`
- `exceptions`
- `citations`
- `source_page_ids`
- source chunk offsets

Reason:
- this is exactly where negation, carve-outs, conditionals, and multi-norm chunks matter
- but provenance still has to be deterministic and attached outside the model

### Retrieval summary / search intent projection

- one short dense retrieval summary
- query intent hits or normalized issue labels

Reason:
- useful for semantic matching
- should be short and evidence-bound

## Recommended Boundary

### Deterministic first

Build the chunk as a structural object first:

- identity
- section path
- article/part/chapter anchors
- prev/next
- document inheritance
- lexical refs

### LLM second

Run a typed prompt on that structural object:

- `law_chunk_semantics`
- `case_chunk_semantics`

The prompt should receive:

- document title
- doc type
- structural path
- article/part metadata
- local chunk text
- optional adjacent chunk text if needed

The prompt should not be responsible for discovering the chunk's structural place from scratch.
The prompt should also not be responsible for inventing provenance.

## Pilot Inputs

Two pilot documents were sent to Azure deployment `wf-gpt5mini-metadata`:

1. Employment Law, Article 11 No waiver
2. Coinmena v Foloosi, Order with Reasons

Raw LLM outputs are stored in:

- [chunk_llm_pilot.json](/Users/artemgendler/dev/legal_agentic_rag/reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_llm_pilot.json)

## Pilot Result: Employment Law Article 11

Observed quality:

- good:
  - model correctly split the chunk into multiple assertions
  - model preserved the non-prohibition of `Nothing in this Law precludes`
  - model captured the conditional waiver path and legal-advice / mediation conditions
- limitation:
  - `part_ref` was null because the prompt only saw the article text, not the structural heading context

This is the strongest evidence that:

- modality should not be deterministic here
- structural anchors should be deterministic and passed into the LLM

The model output correctly distinguished:

- invalid waiver clause -> void
- employer may offer more favourable terms
- employee may waive rights in a written agreement if conditions are met

## Pilot Result: Coinmena v Foloosi

Observed quality:

- good:
  - model recognized `order_with_reasons`
  - model extracted the money amount, timing, and interest consequence
  - model produced retrieval-useful lexical terms
  - model separated operative order content from explanatory reasons reasonably well
- limitation:
  - party/applicant alignment in case orders is still subtle and should inherit document/case context rather than rely on chunk-only inference

This means case chunk LLM extraction is already promising, but party-role normalization should be inherited from the case document layer.

## Assessment

Current position:

- document layer: ready
- chunk structural layer: not ready
- chunk semantic layer: promising on pilot, not yet productionized

### What is missing before chunk corpus can be called ready

1. Structural Chunker V2
   - section-aware splitting instead of length-only splitting
   - real offsets and parent/prev/next links
2. Deterministic structural anchors on every chunk
   - part/chapter/article for laws
   - reasoning/order/disposition anchors for cases
3. Typed LLM semantic prompts on top of structured chunks
4. Chunk quality report
   - orphan chunks
   - missing anchors
   - missing offsets
   - multi-norm chunks
   - semantic coverage
5. Provenance coverage report
   - document-field provenance coverage
   - assertion provenance coverage
   - proposition provenance coverage

## Recommended Fast Retrieval Design

To stay near sub-second retrieval:

1. Parse query deterministically first
   - article number
   - law/case number
   - exact legal terms
   - actor labels
2. Filter first on deterministic metadata
   - `doc_type`
   - `article_number`
   - `case_number`
   - `court_name`
   - `version_lineage_id`
3. Run hybrid ranking
   - exact text / keyword
   - embeddings / dense summary
   - reciprocal rank fusion or equivalent
4. Expand local context only after top hits
   - chunk
   - parent section
   - prev/next

## Recommendation

Do not start with full LLM chunking.

Do this next:

1. Structural Chunker V2
2. Deterministic chunk anchors
3. Typed law/case chunk semantic prompts
4. Provenance hardening for inherited fields and emitted assertions
5. Pilot on 5 documents: 3 laws + 2 cases
6. Chunk quality and provenance coverage reports

That is the fastest path to a chunk corpus that is both searchable and explainable.
