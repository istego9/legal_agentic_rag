# Codex Prompt 08 — Gold and Synth Hardening

You are working inside the `legal_agentic_rag` repository.

## Objective
Separate official/public, internal gold, and synthetic datasets operationally and in storage contracts.

## Scope
- add provenance fields where missing
- add review/lock semantics for gold
- prevent synthetic examples from entering official scorer runs
- add tests for dataset separation

## Files to inspect first
- `services/gold/`
- `services/synth/`
- `apps/api/src/legal_rag_api/routers/gold.py`
- `apps/api/src/legal_rag_api/routers/synth.py`
- `tests/integration/`

## Constraints
- Keep current API shape where possible.
- Prefer additive fields over breaking contract changes.
- Update docs if API contract changes.

## Acceptance criteria
- gold review/lock flow is test-covered
- synthetic provenance is enforced
- verify passes