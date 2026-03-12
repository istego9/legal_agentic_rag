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

## Rules

- Use only supplied chunk text and deterministic structural context.
- Separate operative order content from procedural background and reasons.
- Preserve amounts, deadlines, percentages, and interest rates exactly when explicit.
- If one chunk contains multiple grounded propositions, emit multiple propositions.
- Keep `semantic_dense_summary` to one short sentence.
- Keep `semantic_query_terms` short and retrieval-oriented.
- If no grounded proposition exists, return an empty `propositions` array.
