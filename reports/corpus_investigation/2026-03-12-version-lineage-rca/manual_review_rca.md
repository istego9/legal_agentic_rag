## Manual Review RCA After Successful Azure Run

### Scope

This report explains why the Azure-backed full-corpus run still left
`15/30` documents in manual review even after transport issues were fixed.

Reference run artifact:

- `reports/competition_runs/prepare_report.azure_fast_classifier_pg.json`

Reference evidence payload:

- `reports/corpus_investigation/2026-03-12-version-lineage-rca/manual_review_rca.json`

### What Did Not Happen

The remaining manual-review queue is not caused by a failed Azure run.

Verified facts from the completed run:

- `metadata_normalization_job.status = completed`
- `failed_document_ids_count = 0`
- `failed_group_ids = []`
- `rate_limit_retry_count = 7`
- total token usage was `49,119`, which is operationally small for this corpus

This means the remaining problems are semantic normalization defects, not
transport or quota failures.

### Final Manual Review Inventory

- manual review docs: `15`
- by type:
  - `case = 11`
  - `regulation = 2`
  - `law = 2`
- explicit review reasons that survived into PG:
  - `missing_case_anchor = 4`
  - `missing_legislative_number = 2`
  - `insufficient details for full normalization = 1`
- manual-review docs with `manual_review_required=true` but empty reasons: `8`

### Root Cause 1: Prompt Contract Allows Empty Review Reasons

This is the largest bucket.

Evidence:

- `8` documents were persisted with `manual_review_required=true` and
  `manual_review_reasons=[]`
- examples:
  - `0471e83c1ea18086cfb6b3ff51da6f22b0efee337f10315b2593f782297ccb84`
  - `1a255edc261961ec64870466a27ac4e25b5ebc2abe298e1b69f8dd2fc27288f6`
  - `1b446e196b4d1752241c8ff689a31ea705e98ad0c16b9d343c303664f72b64a1`
  - `437568a801115019fe8278385c0484bdf07ab86f9a499ecaba2b7969b37c764b`
  - `443e04bc1a78940b3fcd5438d24b6c5f182a276d354a3108e738b193675de032`
  - `4e387152960c1029b3711cacb05b287b13c977bc61f2558059a62b7b427a62eb`
  - `536bbce854b9406cc22697e04fcdabd645e030c0e55b918252643b00e0b2b25f`
  - `c98c1475692bc22f4abab6a7a7d7969467c94e46a7e68919aaf127179ebf3f54`

Why it happened:

- the runtime prompt explicitly asks for an envelope where
  `manual_review_reasons` is an empty list shape instead of requiring reasons:
  - `services/ingest/corpus_metadata_normalizer.py:441-443`
  - `packages/prompts/corpus_title_page_metadata_normalizer_v1.md:16-27`
- the prompt spec examples also repeat the same empty-array shape:
  - `reports/corpus_investigation/2026-03-12-version-lineage-rca/prompt_specs.md:433-445`
  - `reports/corpus_investigation/2026-03-12-version-lineage-rca/prompt_specs.md:485-488`
  - `reports/corpus_investigation/2026-03-12-version-lineage-rca/prompt_specs.md:568-570`
- after the LLM call, the merge path accepts the `review` section as-is and
  persists it without any invariant check:
  - `services/ingest/corpus_metadata_normalizer.py:400-431`
  - `services/ingest/corpus_metadata_normalizer.py:751-769`

Impact:

- the review queue becomes non-diagnostic
- external reviewers cannot tell whether the issue is anchor quality, title
  quality, doc-type ambiguity, or prompt failure
- triage cost goes up because each document must be reopened manually

### Root Cause 2: Prompt Output Can Contradict Its Own Anchor Fields

Two documents say `missing_case_anchor` while still returning a non-empty
`same_case_anchor_candidate`.

Examples:

- `09660f78c26cd56c08c7253ed21ba01fb246092f482ccd8acd8e6f9b6fd2d917`
  - extracted anchor: `S CT 295/2025`
  - review reason: `missing_case_anchor`
- `3a574fc4f0baa5ec7ff0dcc822d7c55e4f9c493c24addc217c8df3d848c16fa5`
  - extracted anchor: `S CT 169/2025`
  - review reason: `missing_case_anchor`

Why it happened:

- the prompt does not define a consistency rule between
  `same_case_anchor_candidate` and `manual_review_reasons`
- the merge layer does not validate that a claimed missing anchor is actually
  missing before persisting the LLM review block

Relevant code:

- `services/ingest/corpus_metadata_normalizer.py:373-385`
- `services/ingest/corpus_metadata_normalizer.py:400-431`

Impact:

- this creates false manual-review load
- it also makes the review reason unreliable as a signal for routing or fallback

### Root Cause 3: Real Anchor Extraction Gaps Remain On Noisy Case Title Pages

There are still genuine case-anchor misses.

Examples:

- `62930da32fa3172edf2f2bbf3da268455bd99a7b5fab34d72358730d8cd5da30`
  - compact summary clearly shows `TCD 001/2024`
  - persisted `same_case_anchor_candidate = null`
- `6306079a16b1dec85690f75c715cdbd78b0685a3e19ee30250d481bc32f2e29a`
  - compact summary clearly shows `S CT 514/2025`
  - persisted `same_case_anchor_candidate = null`
- `c98c1475692bc22f4abab6a7a7d7969467c94e46a7e68919aaf127179ebf3f54`
  - compact summary clearly shows `TCD 001/2024`
  - persisted `case_number = null`
  - persisted `same_case_anchor_candidate = null`
- `58eae81bf668e7f6c58619f419a49b5e35e2e5c9c7475475ace28ec562580545`
  - compact summary clearly shows `ARB 034/2025`
  - persisted payload did not produce a case-family anchor

Why it happened:

- parser text is noisy on these title pages
- the current title-page prompt is too weak for DIFC case-number variants such as:
  - `S CT 295/2025`
  - `TCD 001/2024`
  - `ARB 034/2025`
- there is no deterministic post-LLM fallback that says:
  - if `claim_number` is present but `same_case_anchor_candidate` is empty,
    derive the anchor from `claim_number`

Relevant code:

- `services/ingest/corpus_metadata_normalizer.py:348-371`
- `services/ingest/corpus_metadata_normalizer.py:383-385`

Impact:

- same-case grouping stays incomplete for a subset of orders and reasons
- review load concentrates in case documents even after LLM normalization

### Root Cause 4: Case Documents Are Sometimes Misclassified As Regulations

Two court orders were normalized as `regulation`, which then created the
misleading review reason `missing_legislative_number`.

Examples:

- `897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13`
  - final `doc_type = regulation`
  - `case_id = CFI 067/2025`
  - compact summary is a DIFC court order
- `839de9798f377492eee68f82b202d7cd3544be83d799f6226a02f3678c9bb914`
  - final `doc_type = regulation`
  - `case_id = DEC 001/2025`
  - compact summary is a Digital Economy Court order

Why it happened:

- the current prompt is shared across multiple document families
- the model can still interpret court orders as a quasi-regulatory instrument
- once `doc_type=regulation` lands, the deterministic review logic correctly
  asks for a legislative number, but that review reason is semantically false

Relevant code:

- `services/ingest/corpus_metadata_normalizer.py:316-332`
- `services/ingest/corpus_metadata_normalizer.py:348-371`
- `packages/prompts/corpus_title_page_metadata_normalizer_v1.md:30-39`

Impact:

- manual review is inflated by type confusion rather than by missing data
- these documents also poison any downstream regulation-family logic

### Root Cause 5: The Merge Path Accepts Mixed-Type Payload Shapes

One document came back as a `case` with a hybrid `type_specific_document`
containing regulation fields.

Example:

- `58eae81bf668e7f6c58619f419a49b5e35e2e5c9c7475475ace28ec562580545`
  - final `doc_type = case`
  - payload also contains:
    - `regulation_type`
    - `regulation_year`
    - `regulation_number`

Why it happened:

- the merge logic merges keys opportunistically by section
- it checks `doc_type` and `document_role`, but it does not reject
  mutually-exclusive type-specific fields

Relevant code:

- `services/ingest/corpus_metadata_normalizer.py:405-431`
- `services/ingest/corpus_metadata_normalizer.py:791-803`

Impact:

- we keep semantically invalid payloads
- those payloads are hard to route to the right fallback strategy

### Root Cause 6: Synthetic Placeholder Titles Leak Into Final Metadata

This is not the main reason for review, but it noticeably degrades quality.

Examples:

- `0471e83c1ea18086cfb6b3ff51da6f22b0efee337f10315b2593f782297ccb84`
- `1b446e196b4d1752241c8ff689a31ea705e98ad0c16b9d343c303664f72b64a1`
- `437568a801115019fe8278385c0484bdf07ab86f9a499ecaba2b7969b37c764b`
- `443e04bc1a78940b3fcd5438d24b6c5f182a276d354a3108e738b193675de032`
- `62930da32fa3172edf2f2bbf3da268455bd99a7b5fab34d72358730d8cd5da30`
- `839de9798f377492eee68f82b202d7cd3544be83d799f6226a02f3678c9bb914`
- `c98c1475692bc22f4abab6a7a7d7969467c94e46a7e68919aaf127179ebf3f54`

Why it happened:

- the base envelope seeds `title_raw`, `short_title`, and `citation_title` from
  the existing fallback title, which is often `Document <hash>`
- if the model does not confidently replace that field, the placeholder survives

Relevant code:

- `services/ingest/corpus_metadata_normalizer.py:281-286`
- `services/ingest/corpus_metadata_normalizer.py:776-782`

Impact:

- review quality is worse for humans
- title-based family anchoring becomes weaker than it should be

### Why The Outcome Looks “Strange”

The outcome is a mixture of true uncertainty and our own contract weakness:

- some documents really do need stronger extraction
- some documents were marked for review for the wrong reason
- some documents were marked for review without any reason at all

So the final `15` manual-review documents are not a clean queue of genuine
hard cases. They are a mixed queue:

- real extraction gaps
- prompt inconsistency
- response-shape drift
- review invariant failures

### Action Items

1. Tighten the prompt contract.
   - If `manual_review_required=true`, require at least one non-empty
     `manual_review_reasons` item.
   - If `same_case_anchor_candidate` is present, `missing_case_anchor` must be
     forbidden.
2. Add post-LLM invariant validation before merge persistence.
   - Reject or rewrite invalid `review` blocks.
   - Reject mixed case/regulation type-specific payloads.
3. Add deterministic case-anchor fallback.
   - If `claim_number` or `case_number` is present, derive
     `same_case_anchor_candidate` even when the LLM leaves it empty.
4. Split the title-page prompt by document family.
   - separate prompts for `law`, `regulation`, `enactment_notice`, and `case`
   - do not use one generic cross-family prompt for court orders
5. Stop propagating synthetic fallback titles into the prompt as trusted base
   metadata.
   - mark them as placeholders or exclude them from the merge seed
6. Reprocess the same corpus after the invariant fixes and compare:
   - manual-review count
   - empty-reason count
   - doc-type-confusion count
   - case-anchor-miss count

### Expected Outcome After Fixes

If the above fixes are implemented, the manual-review queue should become both
smaller and cleaner:

- false `missing_legislative_number` reviews should disappear for case orders
- empty-reason reviews should drop to zero
- a portion of `TCD` / `S CT` / `ARB` case documents should auto-resolve into
  stable same-case anchors
- the remaining manual-review queue will become a true uncertainty queue instead
  of a mixed prompt-quality queue
