# Chunk Processing Rules Export

- export_version: `chunk_processing_rules_export_v1`
## pilot_scope

```json
{
  "document_count": 5,
  "documents": [
    {
      "pdf_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16",
      "label": "Employment Law DIFC Law No. 2 of 2019",
      "doc_type": "law"
    },
    {
      "pdf_id": "4e387152960c1029b3711cacb05b287b13c977bc61f2558059a62b7b427a62eb",
      "label": "Trust Law DIFC Law No. 4 of 2018",
      "doc_type": "law"
    },
    {
      "pdf_id": "fbdd7f9dd299d83b1f398778da2e6765dfaaed62005667264734a1f76ec09071",
      "label": "Common Reporting Standard Law DIFC Law No. 2 of 2018",
      "doc_type": "law"
    },
    {
      "pdf_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13",
      "label": "Coinmena B.S.C. (C) v Foloosi Technologies Ltd",
      "doc_type": "case"
    },
    {
      "pdf_id": "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26",
      "label": "CA 004/2025 Mr Oran and Oaken v Oved",
      "doc_type": "case"
    }
  ]
}
```

## structural_chunking

```json
{
  "laws": [
    "part",
    "chapter",
    "section",
    "article",
    "schedule item"
  ],
  "cases": [
    "caption",
    "heading",
    "reasoning paragraphs",
    "order",
    "disposition/costs/timing"
  ],
  "page_grounding_invariant": "page remains canonical source unit"
}
```

## ownership

```json
{
  "deterministic": [
    "ids",
    "page references",
    "structural anchors",
    "offsets",
    "lexical refs",
    "document field provenance",
    "assertion provenance"
  ],
  "llm": [
    "semantic provision kind",
    "atomic propositions",
    "negation/conditions/exceptions",
    "dense semantic summary"
  ]
}
```

## retrieval

```json
{
  "stages": [
    "deterministic query parse",
    "structural filter narrowing",
    "hybrid chunk ranking",
    "proposition reranking",
    "local context expansion",
    "direct answer only when grounded proposition dominates"
  ],
  "direct_answer_requires": [
    "single dominant proposition",
    "explicit citation support",
    "no competing conflict",
    "page-grounded provenance"
  ]
}
```

## auditability

```json
{
  "document_fields_require_field_evidence": true,
  "assertions_require_page_provenance": true,
  "proposition_projection_requires_traceback": true
}
```
