# Execution Plan: Rules-First Chunk/Proposition Pilot v2

## Verdict

Approve as a gated retrieval and evidence program, not as a monolithic rollout.

This plan keeps the current clean document corpus intact and upgrades the chunk layer in tightly scoped slices. The operational run remains a 5-document pilot until every gate below is green.

## Frozen Invariants

- page remains the canonical grounding and export unit
- chunk remains the retrieval unit
- proposition layer stays internal-only in v1
- deterministic structure comes before LLM semantics
- parent / prev / next local expansion only
- no query-time LLM for chunk interpretation
- no public API or schema bump in v1

## Explicitly Deferred In v1

- no free-text direct-answer shortcut
- no proposition-first retrieval for case-family by default
- no proposition-driven source export replacing page-grounded source selection
- no full-corpus proposition rollout before all pilot gates are green

## Scope By Route Family

### Primary v2 beneficiaries

- `law_article_lookup`
- `law_relation_or_history`
- `cross_law_compare`

### Secondary / later beneficiaries

- `single_case_extraction`
- `case_cross_compare`

## Delivery Model

### Slice A — Structural Chunker V2

Implement only:

- deterministic section-aware splitting
- real char offsets
- parent / prev / next links
- typed chunk facets and retrieval projections
- explicit `title_page`, `caption`, and `header_identity` chunk types

### Slice B — Semantic Assertions V2

Implement only:

- typed semantic prompts
- proposition / assertion extraction
- span-level provenance
- assertion merge and projection
- no retrieval behavior changes yet

### Slice C — Proposition Retrieval Pilot

Implement only:

- proposition reranking over top chunk candidates
- direct-answer eligibility logic
- baseline delta reporting
- 5-document operational pilot only

## Structural Rules

### Laws / Regulations / Notices

- split on `Part`, `Chapter`, `Section`, `Article`, sub-item, and `Schedule` item
- never allow cross-article chunks
- keep definitions as standalone chunks
- preserve title page, enactment, commencement, and administration sections as explicit chunks

### Cases

- separate caption / header identity from body
- separate order / disposition / costs / interest / deadline blocks
- split numbered reasoning paragraphs where present
- never merge caption, order, and reasons into a single chunk

## Mandatory Provenance

Every semantic assertion must carry:

- `doc_id`
- `page_id`
- `chunk_id`
- `support_span_start`
- `support_span_end`
- `assertion_id`

Every inherited document-level field used in chunk processing must also keep page-level provenance.

## Direct-Answer Policy v1

Direct-answer is allowed only when all are true:

- typed answer only:
  - `boolean`
  - `number`
  - `date`
  - `name`
  - `names`
- single instrument
- single dominant page
- single dominant proposition / assertion
- no compare intent
- no version / history ambiguity
- no condition / exception ambiguity
- no conflict across evidence

Free-text direct-answer is disabled in v1.

## Pilot Corpus Policy

Operational run remains 5 documents.

Before broader approval, add mandatory audit fixtures outside the 5-document operational pilot:

- 1 regulation-focused fixture
- 1 enactment / commencement-notice fixture
- 1 adversarial / no-answer fixture

These may be fixture-backed rather than a second operational run.

## Mandatory Frozen Fixtures

- Employment Law Article 11 must preserve:
  - invalid waiver
  - more favourable employer terms
  - conditional employee waiver
  - the condition explicitly
- one regulation obligation / penalty fixture
- one notice-mediated commencement fixture
- one case order / costs / interest fixture
- one no-answer / adversarial fixture

## Acceptance Gates Before Full Proposition Rollout

### Gate 1 — Structural

- `cross_article_chunk_ids = 0` on pilot laws / regulations / notices
- `caption_order_merge_count = 0` on pilot cases
- `missing_parent_section_id < 2%` of non-root chunks
- `real_offset_coverage = 100%`
- `parent / prev / next coverage = 100%` where applicable

### Gate 2 — Semantic

- Employment Law Article 11 condition preserved = true
- Coinmena amount extraction correct
- CA 004 target semantic extraction non-empty
- no polarity loss on negation-heavy fixtures
- assertion provenance coverage = 100%

### Gate 3 — Retrieval

- top-3 expected hit ratio = 100% on frozen pilot queries
- chunk + proposition reranking improves or preserves top-hit precision versus chunk-only baseline
- structural filters narrow article / case lookup before semantic ranking
- baseline delta report is generated

### Gate 4 — Direct Answer

- direct-answer precision on eligible frozen set = 100%
- direct-answer used only on allowed typed questions
- ambiguous or multi-proposition questions abstain from direct-answer
- direct-answer provenance coverage = 100%

## Rollout Policy

- no full-corpus proposition rollout until all 4 gates are green in 2 consecutive pilot runs
- first production enablement is law-family only
- case-family proposition usage remains opt-in until a separate case pilot passes

## Action Items

### Slice A — Structural Chunker V2

- [x] Replace length-only splitting with deterministic structure-aware splitting for pilot laws and cases.
- [x] Populate real offsets, `parent_section_id`, `prev_chunk_id`, and `next_chunk_id`.
- [x] Eliminate cross-article chunks on the current 5-document pilot.
- [ ] Add explicit regulation and notice structural fixtures outside the operational pilot.
- [ ] Add a dedicated adversarial / no-answer structural fixture.

### Slice B — Semantic Assertions V2

- [x] Add generalized typed prompts:
  - [law_chunk_semantics_v1.md](/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/law_chunk_semantics_v1.md)
  - [case_chunk_semantics_v1.md](/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/case_chunk_semantics_v1.md)
- [x] Remove document-named prompt examples and keep only generalized failure-class examples.
- [x] Keep assertion provenance mandatory.
- [ ] Preserve explicit conditions for Employment Law Article 11.
- [ ] Extract the operative amount correctly on the case order fixture.
- [ ] Extract the interest consequence correctly on the case order / rate fixture.
- [ ] Add regulation and notice semantic fixtures before any broader rollout.

### Slice C — Proposition Retrieval Pilot

- [x] Keep proposition reranking internal and additive.
- [x] Keep page-grounded source selection canonical.
- [x] Restrict direct-answer to typed answers only; free-text shortcut disabled.
- [ ] Generate and store baseline delta reporting versus chunk-only ranking for every pilot run.
- [ ] Prove 2 consecutive green pilot runs before any full proposition rollout.

### Evaluation And Audit

- [x] Generate structural, semantic, retrieval, direct-answer, and provenance reports for the operational pilot.
- [ ] Add regulation / notice / adversarial fixtures to frozen evaluation.
- [ ] Expand the frozen query set after the semantic blockers are closed.
- [ ] Keep generated artifacts in external artifact storage, not tracked `reports/`.

## Current Status

The current pilot is strong on:

- structural chunking
- provenance coverage
- retrieval top-3 hit ratio
- external audit packaging

The current blockers are semantic, not structural:

- conditional legislative clause semantics still lose conditions in one mandatory fixture
- case order amount extraction is not yet reliable enough
- one interest-rate target semantic extraction is still empty

Because of that, the next sprint stays inside Slice B and Slice C hardening. No full-corpus proposition rollout is allowed yet.
