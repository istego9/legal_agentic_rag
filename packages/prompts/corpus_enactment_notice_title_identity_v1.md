# corpus_enactment_notice_title_identity_v1

## Purpose
Extract identity metadata from the title page of an enactment or commencement notice.

## Rules
- The document is expected to be an enactment or commencement notice.
- Use only the supplied title-page text.
- Focus on the notice identity and the target law identity.
- Do not emit case fields.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` must be `enactment_notice`
- `type_specific_document` may contain only enactment-notice fields
