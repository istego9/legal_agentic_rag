# Pilot Gold V1 Report

- run_id: `03e22b5d-89f2-4a69-82ee-eb4500d29447`
- gold_dataset_id: `51ed079a-a2a3-462e-b5ae-2acbc87b33c3`
- artifact_dir: `/Users/artemgendler/dev/legal_agentic_rag/.artifacts/gold/pilot_gold_v1`

## Outcome

- locked_count: `13`
- unresolved_count: `12`

## Disagreement Buckets

- `missing_sources`: `12`
- `history_version_ambiguity`: `3`
- `answer_conflict`: `1`

## Top 5 Adjudication Reasons

- `locked_from_grounded_candidate`: `13`
- `no_grounded_candidate_consensus`: `8`
- `expected_no_answer_requires_manual_confirmation`: `4`

## Blockers Before Full Gold

- Strong/challenger candidates still depend on lightweight experimental profile variations; they are not independent model families.
- Unresolved rows remain where all grounded candidates abstain or where no source pages support a lockable decision.
- Adversarial/no-answer questions cannot be locked until the review flow supports no-answer gold with explicit source policy or a separate locked-no-answer contract.
