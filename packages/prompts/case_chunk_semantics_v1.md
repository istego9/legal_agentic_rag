## Purpose

Extract grounded legal propositions from one case chunk.

## Output contract

Return strict JSON only with keys:

- `section_kind_case`
- `semantic_dense_summary`
- `semantic_query_terms`
- `propositions`

Each proposition must contain:

- `subject_type`
- `subject_text`
- `relation_type`
- `object_type`
- `object_text`
- `modality`
- `polarity`
- `conditions`
- `exceptions`
- `citation_refs`
- `dense_paraphrase`
- `direct_answer`

`direct_answer` keys:

- `eligible`
- `answer_type`
- `boolean_value`
- `number_value`
- `date_value`
- `text_value`

`direct_answer.answer_type` must be one of:

- `boolean`
- `number`
- `date`
- `name`
- `names`
- `none`

Never use `free_text` for chunk-level direct-answer hints.

## Rules

- Use only supplied chunk text and deterministic structural context.
- Separate operative order content from procedural background and reasons.
- Preserve amounts, deadlines, percentages, and interest rates exactly when explicit.
- If one chunk contains multiple grounded propositions, emit multiple propositions.
- Keep `semantic_dense_summary` to one short sentence.
- Keep `semantic_query_terms` short and retrieval-oriented.
- If no grounded proposition exists, return an empty `propositions` array.

## Hard examples

Example: order chunk with amount + deadline + interest consequence

Text pattern:
- `The Applicant shall pay USD 155,879.50`
- `within 14 days`
- `interest at 9% per annum`

Expected extraction shape:
- emit separate grounded propositions where needed for:
  - payment amount
  - deadline
  - interest consequence
- preserve the exact numeric values in `object_text` or `dense_paraphrase`
- if a precise number is explicit, `direct_answer` may be eligible for `number`

Do not:
- hide the amount inside a generic summary
- omit the deadline when it is explicit
- omit the interest rate when it is explicit
- rely on party names or case-specific captions to infer the operative order

Example: heading chunk with court identity

Text pattern:
- case number or neutral citation
- court system heading
- specific court or division heading

Expected extraction shape:
- preserve the court identity in the semantic summary only if it is explicit
- do not rewrite the full heading blob as the answer
- prefer the normalized court name rather than the whole caption line
