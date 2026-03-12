# corpus_enactment_notice_title_identity_v2

## Purpose
Extract identity metadata from the title pages of an enactment or commencement notice.

## Rules
- The document is expected to be an enactment or commencement notice.
- Use only the supplied title-page text.
- `canonical_document.title_raw`, `short_title`, and `citation_title` must come
  from the heading or title block only.
- Do not copy the full first-page blob or body text into title fields.
- Do not append amendment history or explanatory text to title fields.
- If the title is not reliably visible, leave title fields null.
- Focus on the notice identity and the target law identity.
- Do not emit case fields.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` must be `enactment_notice`
- `type_specific_document` may contain only enactment-notice fields
