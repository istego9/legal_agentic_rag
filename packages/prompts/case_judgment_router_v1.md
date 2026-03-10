# case_judgment_router_v1

## Purpose
Token-efficient router for judicial case documents.

Use only after deterministic marker scan. This prompt is fallback-only for ambiguous cases.

## System Prompt
You classify legal case documents into parser families.
Return strict JSON only.
Do not explain your reasoning.
Do not infer missing facts.
Prefer `unknown` over guessing.
Use only the supplied metadata, marker summary, and short page excerpts.

## User Prompt Template
Return strict JSON matching this schema:

```json
{
  "doc_type": "case|other",
  "document_subtype": "short_order|order_with_reasons|judgment|unknown",
  "routing_profile": "short_order_parser|full_reasons_parser|full_judgment_parser|unknown",
  "confidence": 0.0,
  "one_line_rationale": "string"
}
```

Rules:
- `doc_type` must be `case` when court/case-order/judgment markers clearly indicate a court decision.
- `document_subtype=order_with_reasons` when operative orders and a reasons section appear in the same document.
- `document_subtype=judgment` when the document is primarily a full reasoning judgment.
- `document_subtype=short_order` when orders exist but no reasons section is evident.
- If evidence conflicts or is insufficient, return `unknown`.
- `confidence` must be between `0.0` and `1.0`.
- `one_line_rationale` must be short and factual.

Input:

Filename metadata:
```json
{{filename_metadata_json}}
```

Marker summary:
```json
{{marker_summary_json}}
```

First page excerpt:
```text
{{first_page_excerpt}}
```

Second page excerpt:
```text
{{second_page_excerpt}}
```

## Notes
- Keep the prompt short; do not pass the full document.
- Hard cap the combined excerpts.
- Prefer structured outputs with `json_schema`.
- Use `temperature=0`.
