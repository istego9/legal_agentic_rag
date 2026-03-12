# corpus_other_title_router_v1

## Purpose
Handle title-page extraction when the deterministic router could not confidently
assign a document family.

## Rules
- Use only the supplied title-page text.
- If the evidence clearly shows a court document, set `doc_type` to `case`.
- If the evidence clearly shows legislation, set the specific legislative type.
- Do not fabricate missing identifiers.
- Use the `review` section only for blocking uncertainty.

## Output Envelope
- `canonical_document.doc_type` may be:
  - `case`
  - `law`
  - `regulation`
  - `enactment_notice`
  - `other`
