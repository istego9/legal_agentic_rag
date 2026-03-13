# Public100 Baseline Truth Index

This memo is the tracked pointer for the canonical `Public100` baseline run.

Generated heavy artifacts are not committed. The source of truth is the artifact root:

- `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline`

## Canonical Artifacts

- prepare report: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/prepare_report.json`
- run manifest: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/run_manifest.json`
- run summary: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/run_summary.md`
- submission: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/submission.json`
- validation report: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/submission.validation_report.json`
- preflight report: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/preflight_report.json`
- question status: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/public100_baseline/question_status.jsonl`

## Prepare Summary

- documents: `30`
- pages: `590`
- paragraphs: `2433`
- relation_edges: `1493`
- parse_errors: `0`
- parse_warnings: `0`
- metadata_normalization_status: `completed`

## Run Summary

- question_count: `100`
- success_count: `100`
- failure_count: `0`
- resumed_from_cache_count: `0`
- abstain_count: `100`
- abstain_rate: `1.0`
- preflight_blocking_failed: `False`
- official_submission_valid: `True`
- invalid_prediction_count: `0`

## Route Distribution

- `article_lookup`: `45`
- `cross_case_compare`: `31`
- `single_case_extraction`: `16`
- `history_lineage`: `4`
- `no_answer`: `4`

## Top Failure Buckets

- `abstain / cross_case_compare / boolean / abstained`: `19`
- `abstain / article_lookup / number / abstained`: `16`
- `abstain / article_lookup / free_text / abstained`: `15`
- `abstain / article_lookup / boolean / abstained`: `12`
- `abstain / cross_case_compare / name / abstained`: `12`
- `abstain / single_case_extraction / free_text / abstained`: `7`
- `abstain / history_lineage / free_text / abstained`: `4`
- `abstain / no_answer / free_text / abstained`: `4`
- `abstain / single_case_extraction / names / abstained`: `4`
- `abstain / single_case_extraction / name / abstained`: `2`

## Notes

- This is a baseline operational run only. It does not imply retrieval or answer quality readiness.
- The run is reproducible and submission-valid, but the current runtime answered every public question with abstention.
- Any next-step triage or pilot-gold work should reference the artifact root above, not older tracked reports.
