# corpus_case_relation_resolver_v1

## Purpose
Resolve relations between multiple documents that appear to belong to the same
case family.

## System Prompt
You resolve same-case document relations from normalized title-page metadata.
Return strict JSON only.
Do not explain your reasoning.
Do not invent relation types that are not supported.

## User Prompt Template
Return strict JSON with this shape:

```json
{
  "case_family_id": "string|null",
  "primary_merits_document_id": "string|null",
  "document_role_confirmations": {},
  "relations": [],
  "family_review_required": true,
  "family_review_reasons": []
}
```

Rules:
- Supported relation values in `relations[*].case_relation_type`:
  - `order_for`
  - `reasons_for`
  - `appeal_in`
  - `permission_for`
  - `related`
- Use only the supplied normalized metadata.
- If the same-case relation is ambiguous, set `family_review_required=true`.
- Prefer a merits judgment as `primary_merits_document_id` when one exists.
- Do not apply legislative `current version` semantics to case documents.

## Notes
- Use `temperature=0`.
- Keep the prompt input compact.
- Return one JSON object only.
