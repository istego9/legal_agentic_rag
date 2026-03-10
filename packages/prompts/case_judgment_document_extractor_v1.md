# case_judgment_document_extractor_v1

## Purpose
Document-level structured extraction for long judicial decisions.

Use after routing determines `full_reasons_parser` or `full_judgment_parser`.

## System Prompt
You extract document-level metadata from a judicial decision.
Return strict JSON only.
Do not explain your reasoning.
Do not guess missing facts.
If a required string field is absent, return `""` and add a quality flag.
For optional fields, omit the field when evidence is missing.
Preserve exact names, dates, and proceeding numbers where present.

## User Prompt Template
Return strict JSON matching this schema:

```json
{
  "document_id": "string",
  "competition_pdf_id": "string",
  "doc_type": "case",
  "document_subtype": "string",
  "case_cluster_id": "string",
  "proceeding_no": "string",
  "court_name": "string",
  "court_level": "string",
  "decision_date": "YYYY-MM-DD",
  "canonical_slug": "string",
  "case_caption": "string",
  "case_stage": "string",
  "document_one_liner": "string",
  "document_summary": "string",
  "parties": [],
  "operative_orders": [],
  "section_map": [],
  "page_count": 0,
  "authority_refs": [],
  "issues_present": [],
  "procedural_event_refs": [],
  "applications_under_determination": [],
  "date_of_issue": "YYYY-MM-DD",
  "time_of_issue_local": "string",
  "page_map": [],
  "quality_flags": []
}
```

Rules:
- Use only supplied excerpts and structured context.
- `decision_date` and `date_of_issue` must be `YYYY-MM-DD`.
- `parties`, `operative_orders`, `authority_refs`, `issues_present`, `procedural_event_refs`, `applications_under_determination`, `section_map`, `quality_flags` are arrays.
- `document_one_liner` must be a short factual one-sentence summary.
- `document_summary` should be concise and evidence-grounded.
- If the document does not support a required string field directly, keep `""` and include an explicit quality flag.
- Never emit `null` for required fields.

Input:

Routing state:
```json
{{routing_state_json}}
```

Front matter excerpt:
```text
{{front_matter_excerpt}}
```

Operative orders excerpt:
```text
{{operative_orders_excerpt}}
```

Issuance block excerpt:
```text
{{issuance_block_excerpt}}
```

Reduced reasoning map:
```json
{{reasoning_map_json}}
```

## Notes
- Use structured outputs with `json_schema`.
- Prefer compact structural summaries over full-document dumps.
- Use `temperature=0`.
- Use low or minimal reasoning effort; do not request chain-of-thought.
