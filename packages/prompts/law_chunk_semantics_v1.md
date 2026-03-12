## Purpose

Extract grounded legal propositions from one legislative chunk.

## Output contract

Return strict JSON only with keys:

- `section_kind`
- `provision_kind`
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
- Preserve negation, conditions, and exceptions exactly.
- If one chunk contains multiple norms, emit multiple propositions.
- If the text says a clause is void, capture that explicitly.
- If the text says nothing precludes an action, do not rewrite that as a prohibition.
- Keep `semantic_dense_summary` to one short sentence.
- Keep `semantic_query_terms` short and retrieval-oriented.
- If no grounded proposition exists, return an empty `propositions` array.
