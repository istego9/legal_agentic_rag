# corpus_law_title_identity_v1

## Purpose
Extract identity metadata from the title page of a law.

## Rules
- The document is expected to be a law.
- Use only the supplied title-page text.
- Extract the document's own law number, not amendment references.
- If title-page text lists amendment laws using phrases such as `is amended by`
  or `as amended by`, include them in
  `processing_candidates.title_page_amending_law_refs`.
- Do not emit case fields.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` must be `law`
- `type_specific_document` may contain only law fields
- `processing_candidates` may contain:
  - `consolidated_version_number`
  - `consolidated_version_date`
  - `enabled_by_law_number`
  - `enabled_by_law_year`
  - `family_anchor_candidate`
  - `title_page_amending_law_refs`
