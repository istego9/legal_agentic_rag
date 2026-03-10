---
name: public_dataset_taxonomy
description: Use when labeling public questions, benchmarking router performance, or changing route families.
---

# Public Dataset Taxonomy

## Goal
Provide a single labeled taxonomy for public questions so routing can be benchmarked and improved.

## Labels required per question
- `primary_route`
- `answer_type_expected`
- `document_scope`
- `target_doc_types`
- `temporal_sensitivity`
- `answerability_risk`

## Rules
1. Every public question must be labeled.
2. Benchmark reports must show confusion and misses.
3. Router may not return silent unknowns.
4. Keep labels under version control.

## Suggested paths
- `tests/fixtures/public_dataset_taxonomy/`
- `scripts/benchmark_router.py`
- `docs/exec-plans/active/benchmarks/`
