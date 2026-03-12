# corpus_case_title_identity_v1

## Purpose
Extract identity metadata from the title page of a court or tribunal document.

## Rules
- The document is expected to be a case document.
- Use only the supplied title-page text.
- Prefer the main proceeding or claim identifier shown in the heading.
- If `case_number` or `claim_number` is present, populate
  `processing_candidates.same_case_anchor_candidate`.
- Do not emit legislative fields.
- Do not classify court orders, judgments, reasons, appeal rulings, or
  permission rulings as regulations or laws.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` must be `case`
- `type_specific_document` may contain only case fields
- `processing_candidates` may contain:
  - `claim_number`
  - `appeal_number`
  - `document_role`
  - `same_case_anchor_candidate`
