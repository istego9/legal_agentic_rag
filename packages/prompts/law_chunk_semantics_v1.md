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

## Hard examples

Example: Employment Law Article 11

Text pattern:
- `... a provision in an agreement to waive any of those requirements ... is void ...`
- `Nothing in this Law precludes an Employer from providing an Employee with terms and conditions ... more favourable ...`
- `Nothing in this Law precludes an Employee from waiving any right ... by written agreement ... subject to Article 66(13) ... opportunity to seek independent legal advice ... or ... mediation ...`

Expected extraction shape:
- proposition 1:
  - `relation_type = "is_void"`
  - object must clearly state that the waiver provision is void
- proposition 2:
  - permission for employer to provide more favourable terms
- proposition 3:
  - permission for employee to waive rights
  - conditions must include the written-agreement / settlement-or-termination / legal-advice-or-mediation constraints

Do not:
- collapse all three norms into one proposition
- drop `subject to ...` conditions
- rewrite `Nothing in this Law precludes ...` as prohibition
