## Corpus Version/Lineage Investigation

This directory contains the March 12, 2026 investigation package for the
version-grouping and current-version problems discovered during full-corpus
`prepare`.

### Scope

- Dataset: `datasets/official_fetch_2026-03-11/documents.zip`
- Runner: `scripts/competition_batch.py prepare`
- Canonical storage: PostgreSQL corpus store on `127.0.0.1:15432`

### Verified Facts

- `prepare` is deterministic for this bundle.
- Parser crashes were not observed.
- `doc/page` mapping is stable.
- Exact duplicate groups are empty for this bundle.
- Version and lineage signals are not trustworthy yet.

### Included Evidence

- `evidence_summary.json`
  - corpus counts, determinism fingerprints, parser status, version-group counts
- `problematic_version_groups.json`
  - full payload for every multi-document version group found by deterministic ingest
- `high_risk_docs.json`
  - documents that require manual review because of low text quality or opaque metadata
- `regex_reproduction.json`
  - minimal reproductions showing why the current regex extraction is unsafe
- `temporal_false_positive_samples.json`
  - case documents where legislative temporal heuristics created false lineage/current-version signals
- `document_samples.json`
  - concrete problematic documents with extracted fields and source excerpts
- `storage_contract_gap.json`
  - mismatch between the expected contract fields and what canonical PG exposes today
- `deterministic_fixes_eval.json`
  - before/after comparison for the deterministic ingest fixes that were implemented and reprocessed on the full corpus
- `deterministic_fixes_eval.md`
  - human-readable summary of the before/after change impact
- `metadata_normalizer_eval.json`
  - evaluation of the new title-page metadata normalizer and case relation resolver on the full corpus
- `metadata_normalizer_eval.md`
  - human-readable summary of the metadata normalizer outcome
- `azure_fast_classifier_eval.json`
  - evaluation of the Azure-backed fast-classifier run with chunk-level LLM disabled
- `azure_fast_classifier_eval.md`
  - human-readable summary of the Azure-backed run, including failure modes
- `azure_fast_classifier_hardened_eval.json`
  - before/after evaluation after `corpus_metadata_normalizer_v2` hardening and PG-backed reprocess
- `azure_fast_classifier_hardened_eval.md`
  - human-readable summary of the hardening impact on manual review and case-family quality
- `azure_typed_prompts_eval.json`
  - evaluation of the typed title-page prompt set and title-page amendment reference extraction
- `azure_typed_prompts_eval.md`
  - human-readable summary of the typed-prompt run
- `manual_review_rca.json`
  - structured breakdown of why the successful Azure run still left 15 documents in manual review
- `manual_review_rca.md`
  - detailed RCA for the remaining manual-review queue, with example documents and corrective actions
- `typed_prompt_redesign.md`
  - typed prompt redesign, official-docs-derived best practices, and the grounded consolidated-law plan
- `problem_report.md`
  - human-readable RCA
- `prompt_specs.md`
  - proposed prompt strategy by document type

### Reproduction

1. Run:
   - `.venv/bin/python scripts/competition_batch.py prepare --documents datasets/official_fetch_2026-03-11/documents.zip --project-id competition_local --output reports/competition_runs/prepare_report.json`
2. Rerun the same command to confirm matching fingerprints.
3. Regenerate the evidence JSONs from deterministic ingest and PG snapshot.

### Notes

- `prepare_report.json` and `prepare_report.rerun.json` remain the source run artifacts.
- `prepare_report.after_deterministic_fixes.json` is the reprocessed full-corpus artifact after the deterministic patch set.
- `prepare_report.with_metadata_normalizer.json` is the reprocessed full-corpus artifact after wiring the title-page normalizer and case relation resolver into import.
- `prepare_report.azure_fast_classifier_pg.json` is the PostgreSQL-backed Azure run using the fast classifier model and rules-only chunk enrichment.
- `prepare_report.azure_fast_classifier_hardened_pg_final.json` is the PostgreSQL-backed Azure run after hardening the title-page normalizer review invariants and case-anchor fallback.
- `prepare_report.azure_typed_prompts_pg_final_rerun.json` is the PostgreSQL-backed Azure run after splitting title-page extraction by document family.
- This directory is the research overlay that explains why the artifacts are not yet sufficient for trustworthy lineage/version use.
