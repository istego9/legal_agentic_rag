# corpus_other_title_router_v2

## Purpose
Handle title-page extraction when the deterministic router could not confidently
assign a document family.

## Rules
- Use only the supplied title-page text.
- `canonical_document.title_raw`, `short_title`, and `citation_title` must come
  from the heading or caption only.
- Do not copy the full first-page blob or body text into title fields.
- Do not append amendment history, consolidated-version text, or procedural
  narrative to title fields.
- If the title or caption is not reliably visible, leave title fields null.
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
