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
- Preserve negation, conditions, and exceptions exactly.
- If one chunk contains multiple norms, emit multiple propositions.
- If the text says a clause is void, capture that explicitly.
- If the text says nothing precludes an action, do not rewrite that as a prohibition.
- If the text contains condition-bearing cues such as `subject to`, `unless`, `except`, `provided that`, `if`, `only if`, or `nothing in this Law precludes`, the affected proposition must carry explicit `conditions` or `exceptions`.
- If a proposition depends on conditions or exceptions, do not mark it as eligible for direct answer.
- Keep `semantic_dense_summary` to one short sentence.
- Keep `semantic_query_terms` short and retrieval-oriented.
- If no grounded proposition exists, return an empty `propositions` array.

## Hard examples

Example: mixed invalidity + permission + conditional permission in one legislative chunk

Text pattern:
- `... a provision in an agreement to waive minimum statutory requirements ... is void ...`
- `Nothing in this Law precludes an employer from providing terms more favourable to an employee ...`
- `Nothing in this Law precludes an employee from waiving rights ... by written agreement ... subject to another Article ... opportunity to seek independent legal advice ... or ... mediation ...`

Expected extraction shape:
- proposition 1:
  - `relation_type = "is_void"`
  - object must clearly state that the waiver provision itself is void
- proposition 2:
  - permission for an employer to provide more favourable terms
- proposition 3:
  - permission for an employee to waive rights
  - `conditions` must include the written-agreement / settlement-or-termination / legal-advice-or-mediation constraints

Do not:
- collapse all three norms into one proposition
- drop `subject to ...` conditions
- rewrite `Nothing in this Law precludes ...` as prohibition
- convert invalidity of a clause into a generic procedural statement
