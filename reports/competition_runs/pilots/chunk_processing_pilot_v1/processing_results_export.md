# Chunk Processing Results Export

> Superseded historical snapshot. Current canonical rules-first chunk/proposition pilot truth lives in `.artifacts/...` and is indexed by `reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_pilot_truth_index.md`.

- export_version: `chunk_processing_results_export_v1`
## prepare_report

```json
{
  "status": "completed",
  "project_id": "competition_chunk_processing_pilot_v1",
  "documents_path": "/Users/artemgendler/dev/legal_agentic_rag/reports/competition_runs/pilots/chunk_processing_pilot_v1/chunk_processing_pilot_documents.zip"
}
```

## structural

```json
{
  "chunk_count": 625,
  "missing_offsets_count": 0,
  "missing_parent_count": 196,
  "missing_prev_next_count": 0,
  "cross_article_chunk_ids": [
    "para_127a9cd0f3e733cc19e55584",
    "para_13431706d72927352822b8ee",
    "para_1a095b1bc9b2afd1619fe93d",
    "para_1e81bdd9c21b739b5324ddbf",
    "para_1f7de694b2965b4d15a8a163",
    "para_227987167c2d76e9174a9363",
    "para_29a92b0409cbb5ee59b8c3e4",
    "para_29abf3b6462a43fc612a9168",
    "para_2f69b100be4b48415d00ad32",
    "para_3f250872080798602df5ff65",
    "para_42b440f8a96ab1415e264834",
    "para_4d0c2f92e568356ae51c3c0f",
    "para_58018e553bf0021cdca0cd72",
    "para_630b72754728840253343afc",
    "para_6684e77ebc643cde2f9557db",
    "para_68a726e0484b5f64bc475685",
    "para_6c9f36d88bb6c5f6065c8c77",
    "para_6d76f28bbd063b1b05b06622",
    "para_828b70be070e5d45a2065a5b",
    "para_84c74909f990b9c66b1aee95",
    "para_856f48b2e9411ef0da0b66fa",
    "para_8c01bb969b7c257716c9fb52",
    "para_905d2decc4e02332d9e14b45",
    "para_9a8b191153d84751b2a27453",
    "para_a509592f4ae4b4e006a51cb3",
    "para_aebb818ae946c2a747e6a81e",
    "para_b637ae7f0583ffde2185b435",
    "para_c5af038f92561d0e7ede65a8",
    "para_da0fb55487d794831acee017",
    "para_dfb973a2d2bc6185991b7460",
    "para_e1f960495d48e15640d1afb2",
    "para_e540dbc341c677d6a66ec605",
    "para_f59b1088a87aac16935aab45"
  ],
  "case_merge_issue_chunk_ids": []
}
```

## semantic

```json
{
  "report_version": "chunk_processing_semantic_report_v1",
  "assertion_count": 632,
  "chunk_with_assertions_count": 623,
  "employment_article_11": {
    "chunk_id": "para_d5434318071aab73242a6bf4",
    "assertion_count": 3,
    "has_void_assertion": true,
    "has_more_favourable_permission": true,
    "has_employee_waive_permission": true,
    "has_condition_preserved": false
  },
  "coinmena_order": {
    "chunk_id": "para_fe7a3c1a9355672bd16c7dd0",
    "assertion_count": 1,
    "has_amount": false,
    "has_deadline": true,
    "has_interest": true
  },
  "ca004_order": {
    "chunk_id": null,
    "assertion_count": 0,
    "has_amount": false,
    "has_interest": false
  },
  "semantic_dense_summary_count": 625
}
```

## retrieval

```json
{
  "query_count": 6,
  "top3_expected_hit_ratio": 1.0
}
```

## direct_answer

```json
{
  "direct_answer_used_count": 2,
  "direct_answer_correct_count": 2,
  "direct_answer_correct_ratio": 1.0
}
```

## provenance

```json
{
  "document_field_missing_count": 0,
  "assertion_missing_count": 0,
  "projection_missing_count": 0,
  "direct_answer_missing_count": 0
}
```
