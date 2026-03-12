# Execution Plan: Corpus Version and Lineage Hardening

## Objective

Make full-corpus `prepare` trustworthy for versioning, lineage, and manual
review without changing runtime architecture.

## Why This Plan Exists

The corpus is parser-stable and deterministic, but current lineage/version
metadata is not safe:

- law metadata extraction collapses multiple laws into `law:difc`
- case metadata extraction creates fake anchors such as `case:no`
- legislative temporal heuristics leak into case documents
- canonical PG and compact diagnostics do not expose enough lineage fields

Research package:

- `reports/corpus_investigation/2026-03-12-version-lineage-rca/`

## Non-Goals

- no runtime QA behavior changes in iteration 1
- no online LLM dependency
- no OCR-by-default pipeline

## Iteration 1: Evidence and Contract Hardening

### Tasks

- [ ] Preserve lineage/version fields in canonical PG top-level rows:
  - `effective_start_date`
  - `effective_end_date`
  - `is_current_version`
  - `version_group_id`
  - `version_sequence`
  - `ocr_used`
  - `extraction_confidence`
- [ ] Stop dropping lineage fields from `prepare_report.json` diagnostics.
- [ ] Add explicit `manual_review_required` and `manual_review_reasons`.
- [ ] Add contract fixtures for:
  - `law:difc` false-family regression
  - `case:no` false-family regression
  - case temporal false-positive regression

### Validation

- [ ] PG rows expose the same top-level fields expected by the contract.
- [ ] `prepare_report.json` contains enough evidence for external audit.
- [ ] Existing deterministic fingerprints remain stable for unaffected fields.

### Rollback

- Keep additive schema change only.
- If diagnostics expansion causes consumer issues, keep old keys and add new
  optional fields rather than removing anything.

## Iteration 2: Deterministic Candidate Extractor Hardening

### Tasks

- [ ] Replace current `law_number` regex with structured legislative-title
  parsing that prefers:
  - `Law No. X of YYYY`
  - `Act No. X of YYYY`
  - `Code No. X of YYYY`
- [ ] Replace current `case_id` regex with parser that handles:
  - `Case No:`
  - `Case No.`
  - `Claim No.`
  - `Appeal No.`
  - `DEC 001/2025`, `CA 004/2025`, `CFI-016-2025/3`
- [ ] Restrict legislative temporal heuristics to legislative doc types only.
- [ ] For case docs, emit:
  - `case_number`
  - `claim_number`
  - `neutral_citation`
  - `document_role_candidate`
  instead of `current_version`.

### Validation

- [ ] Minimal regex reproductions from `regex_reproduction.json` no longer fail.
- [ ] `case:no` disappears.
- [ ] `law:difc` disappears or is reduced to a review-only bucket.

### Rollback

- Keep old candidate extraction behind a fallback function while new tests settle.

## Iteration 3: Title-Page LM Metadata Normalization

### Tasks

- [ ] Add offline page-window selector:
  - default: page 1
  - add page 2 if page 1 is ambiguous
  - use image/OCR only if title-page parser quality is below threshold
- [ ] Implement title-page normalization prompts:
  - `legislative_title_metadata_v1`
  - `enactment_notice_title_metadata_v1`
  - `case_title_metadata_v1`
  - `document_router_title_metadata_v1`
- [ ] Cache by `content_hash + prompt_version + model_version + page_window`.
- [ ] Record model version, prompt version, and normalization payload.

### Validation

- [ ] Cost report for full bundle.
- [ ] Regression set covers all currently bad groups.
- [ ] Manual review volume stays bounded.

### Rollback

- Feature flag the LM normalization stage.
- Fall back to deterministic candidate extractor only.

## Iteration 4: Family Resolver

### Tasks

- [ ] Build candidate family buckets from normalized title-page fields.
- [ ] Add legislative family resolver prompt:
  - `legislative_family_resolution_v1`
- [ ] Add case relation resolver prompt:
  - `case_relation_resolution_v1`
- [ ] Emit relation edges instead of forced linear supersession when ambiguous.
- [ ] Only legislative families may emit `current_document_id`.
- [ ] Case families emit relation edges and primary merits document only.

### Validation

- [ ] `law:difc` false family is eliminated.
- [ ] case documents are grouped by real dispute anchors, not `No` or truncated prefixes.
- [ ] ambiguous groups route to manual review instead of silent bad lineage.

### Rollback

- If resolver quality is weak, keep normalized metadata but disable automatic
  family ordering.

## Iteration 5: Reporting and Manual Review Surface

### Tasks

- [ ] Extend `prepare_report.json` with:
  - failed docs/pages
  - high-risk docs
  - version-group review queue
  - OCR/manual fallback queue
- [ ] Add exported verification bundle manifest.
- [ ] Ensure UI/API can read lineage diagnostics from canonical storage.

### Validation

- [ ] External reviewer can inspect corpus quality from report artifacts alone.
- [ ] No rerun of deterministic ingest is required just to answer lineage questions.

### Rollback

- Diagnostics are additive and can remain even if UI work lags.

## Document-Type Strategy

### Laws

- deterministic parser:
  - page ids
  - article refs
  - candidate dates
  - candidate law number
- title-page LM:
  - normalized law number and year
  - consolidated version label
  - title and short title
  - family anchor candidate
- family resolver:
  - current version
  - order
  - relation edges

### Regulations

- deterministic parser:
  - refs, dates, candidate title
- title-page LM:
  - regulation number/year
  - authority
  - enabling law
  - family anchor candidate
- family resolver:
  - current version when justified
  - relation edges

### Enactment Notices

- deterministic parser:
  - dates and candidate law refs
- title-page LM:
  - notice number/year
  - target law identity
  - commencement date and scope
- target resolver:
  - link to target family
  - no fake supersession unless explicit

### Cases

- deterministic parser:
  - page ids
  - candidate citations and refs
  - document-role candidate
- title-page LM:
  - case number
  - claim number
  - neutral citation
  - court
  - role of this document
- case relation resolver:
  - same-case grouping
  - relation edges such as `order_for` and `reasons_for`
- forbidden:
  - no legislative `current_version`

### Other

- deterministic parser:
  - route candidate only
- title-page router LM:
  - classify or send to manual review
- forbidden:
  - no automatic version grouping

## Validation Matrix

- [ ] exact duplicate fixture
- [ ] same law, multiple editions fixture
- [ ] same case, multiple roles fixture
- [ ] low-quality title page fixture
- [ ] legislative reference inside case text fixture
- [ ] ambiguous DIFC law family fixture

## Deliverables

- [ ] contract-preserving schema update
- [ ] deterministic extractor fixes
- [ ] offline title-page metadata normalization
- [ ] family resolver
- [ ] expanded `prepare_report.json`
- [ ] reviewable verification bundle
