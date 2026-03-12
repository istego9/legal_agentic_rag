# corpus_regulation_title_identity_v1

## Purpose
Extract identity metadata from the title page of a regulation or regulatory instrument.

## Rules
- The document is expected to be a regulation, not a court order.
- Use only the supplied title-page text.
- Extract the regulation's own number, not amendment references.
- If the text clearly shows a court order or judgment, do not force a
  regulation interpretation.
- If title-page text lists amendment laws using phrases such as `is amended by`
  or `as amended by`, include them in
  `processing_candidates.title_page_amending_law_refs`.
- Do not emit case fields.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` must be `regulation`
- `type_specific_document` may contain only regulation fields
- `processing_candidates` may contain:
  - `consolidated_version_number`
  - `consolidated_version_date`
  - `enabled_by_law_number`
  - `enabled_by_law_year`
  - `family_anchor_candidate`
  - `title_page_amending_law_refs`
