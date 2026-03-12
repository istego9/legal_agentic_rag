## Azure Fast Classifier Hardening Eval

- report: `reports/competition_runs/prepare_report.azure_fast_classifier_hardened_pg_final.json`
- metadata profile: `corpus_metadata_normalizer_v2`
- Azure model: `wf-fast10`
- chunk-level LLM: disabled

### Before -> After

- manual review docs: `15 -> 4`
- empty-reason manual reviews: `8 -> 0`
- case docs without anchor: `4 -> 0`
- regulation docs with case signals: `2 -> 0`
- case relation edges: `2 -> 5`

### Residual Risk

- Remaining manual review queue is now only legislative: `4` law documents.
- The remaining reasons are current-version / title ambiguity problems, not case-anchor or doc-type confusion problems.
- Azure path completed via cache hits on the final PG-backed rerun: `llm_calls=0`, `cache_hit_count=33`.
