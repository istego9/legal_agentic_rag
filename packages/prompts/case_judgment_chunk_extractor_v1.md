# case_judgment_chunk_extractor_v1

## Purpose
Chunk-level extraction for judicial decision paragraphs and operative order items.

Each request should operate on one chunk only.

## System Prompt
You extract grounded chunk metadata from a judicial decision.
Return strict JSON only.
Do not explain your reasoning.
Do not infer facts not present in the chunk or provided local context.
If a required field is missing, keep deterministic fallback values from context.
For optional fields, omit the field when unknown.

## User Prompt Template
Return strict JSON matching this schema:

```json
{
  "chunk_id": "string",
  "case_number": "string",
  "case_cluster_id": "string",
  "page_number_1": 0,
  "chunk_type": "heading|caption_line|recital_paragraph|order_item|issuance_metadata|numbered_reasoning_paragraph|quoted_ground_block|summary_paragraph|conclusion_paragraph|other",
  "section_kind_case": "header|case_number_block|court_block|caption_parties_block|judge_block|document_title_block|recital_block|operative_order_intro|operative_order_item|costs_direction_item|timetable_direction_item|issuance_block|reasons_heading|executive_summary|procedural_history|appellate_test_or_legal_standard|evidence_intro|party_evidence_block|evidence_summary|lower_court_findings|grounds_of_appeal_heading|ground_statement|ground_reasoning|ground_conclusion|party_specific_conclusion|global_conclusion|facts|issues|legal_framework|analysis|holding|final_orders|unknown",
  "paragraph_no": 0,
  "ground_no": "string (optional)",
  "ground_owner": "string (optional)",
  "order_effect_label": "string (optional)",
  "party_roles": [],
  "judge_names": [],
  "issue_tags": [],
  "authority_refs": [],
  "date_mentions": [],
  "answer_candidate_types": [],
  "chunk_summary": "string",
  "text_clean": "string"
}
```

Rules:
- `chunk_summary` must be short, factual, and grounded in the chunk.
- Preserve legal names and references exactly where possible.
- `text_clean` may normalize whitespace only.
- `issue_tags`, `authority_refs`, `date_mentions`, `party_roles`, `judge_names`, `answer_candidate_types` are arrays.
- If the chunk is ambiguous, keep `section_kind_case=unknown`.
- Never invent `ground_no`, `ground_owner`, or `order_effect_label`.

Input:

Document context:
```json
{{document_context_json}}
```

Chunk local context:
```json
{{chunk_context_json}}
```

Chunk text:
```text
{{chunk_text}}
```

## Notes
- Prefer one chunk per request for deterministic replay.
- Use `json_schema`.
- Use `temperature=0`.
- Use minimal reasoning effort unless chunk ambiguity proves too high.
