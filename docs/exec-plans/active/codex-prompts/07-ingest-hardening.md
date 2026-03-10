# Codex Prompt 07 — Ingest Hardening

You are working inside the `legal_agentic_rag` repository.

## Objective
Make contest ingest reproducible and non-stubbed.

## Scope
- isolate local synthetic/bootstrap ingest helpers
- harden competition ingest path
- ensure document/page/chunk mappings are deterministic
- assert document-type projections are created

## Files to inspect first
- `services/ingest/`
- `apps/api/src/legal_rag_api/corpus_pg.py`
- `tests/integration/`
- `tests/contracts/`

## Constraints
- Do not remove local developer bootstrap if tests depend on it; isolate it.
- Contest mode must not call stub parser paths.
- Add fixture-based tests.

## Acceptance criteria
- contest ingest never reports `stub-v1`
- page ids are deterministic
- verify passes