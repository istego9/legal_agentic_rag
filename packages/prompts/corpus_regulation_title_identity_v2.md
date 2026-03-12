# corpus_regulation_title_identity_v2

## Purpose
Extract identity metadata from the title pages of a regulation or regulatory instrument.

## Rules
- The document is expected to be a regulation, not a court order.
- Use only the supplied title-page text.
- `canonical_document.title_raw`, `short_title`, and `citation_title` must come
  from the heading or title block only.
- Do not copy the full first-page blob, body text, or procedural paragraphs into
  title fields.
- Do not append amendment history, consolidated-version history, or amendment-law
  lists to title fields.
- If the title is not reliably visible, leave title fields null.
- Extract the regulation's own number, not amendment references.
- If the text clearly shows a court order or judgment, do not force a
  regulation interpretation.
- If title-page text lists amendment laws using phrases such as `is amended by`,
  `as amended by`, `amendment law`, or `amending law`, include every visible
  amendment law reference in
  `processing_candidates.title_page_amending_law_refs` as an ordered array.
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
