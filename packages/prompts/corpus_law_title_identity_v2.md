# corpus_law_title_identity_v2

## Purpose
Extract identity metadata from the title pages of a law.

## Rules
- The document is expected to be a law.
- Use only the supplied title-page text.
- `canonical_document.title_raw`, `short_title`, and `citation_title` must come
  from the heading or title block only.
- Do not copy the full first-page blob, article text, body text, footers, or
  explanatory paragraphs into title fields.
- Do not append amendment history, consolidated-version history, or the list of
  amending laws to title fields.
- If the title is not reliably visible, leave title fields null.
- Extract the document's own law number, not amendment references.
- If title-page text lists amendment laws using phrases such as `is amended by`,
  `as amended by`, `amendment law`, or `amending law`, include every visible
  amendment law reference in
  `processing_candidates.title_page_amending_law_refs` as an ordered array.
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
