# services/runtime

Typed route/resolver/sources pipeline domain logic for single-question and batch QA.

## Retrieval profile notes

- `article_lookup` uses dedicated profile `article_lookup_recall_v2`.
- `single_case_extraction` uses dedicated profile `single_case_extraction_compact_v2`.
- `history_lineage` uses dedicated profile `history_lineage_graph_v1`.
- Other routes keep `default_compare_v1`.
- Runtime debug trace exposes:
  - `route_decision` (router signal + taxonomy decision payload)
  - `law_article_lookup_resolution` (`law_article_lookup_resolution_v1`)
  - `retrieved_pages` (all retrieved candidates)
  - `used_pages` (subset selected for evidence usage)
  - `evidence_selection_trace` (`evidence_selection_trace_v1`)
  - `answer_normalization_trace` (`answer_normalization_trace_v1`)
  - `route_recall_diagnostics` (`route_recall_diagnostics_v1`)
  - `latency_budget_assertion` (`latency_budget_assertion_v1`)
