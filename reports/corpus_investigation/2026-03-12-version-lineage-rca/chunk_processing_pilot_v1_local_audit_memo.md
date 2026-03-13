# Chunk Processing Pilot Local Audit Memo

Current framing: `rules-first chunk/proposition pilot`.

## Current Truth

- canonical confirmation roots: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/pilots/chunk_processing_pilot_v1` and `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/pilots/chunk_processing_pilot_v1_run2`
- latest confirmation root: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/pilots/chunk_processing_pilot_v1_run2`
- shadow subset root: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/pilots/chunk_processing_shadow_subset_v1`

## Metrics

- structural gate passed: `True`
- semantic gate passed: `True`
- retrieval gate passed: `True`
- direct-answer gate passed: `True`
- expanded frozen query pass ratio: `0.625`
- real-corpus fixture pass ratio: `1.0`
- provenance missing (document/assertion/projection/direct-answer): `0/0/0/0`

## Repo Hygiene

Tracked generated pilot markdown/json under `reports/competition_runs/pilots/chunk_processing_pilot_v1/` are historical and superseded.
Current truth lives in `.artifacts` and is indexed by `chunk_processing_pilot_truth_index.md`.
