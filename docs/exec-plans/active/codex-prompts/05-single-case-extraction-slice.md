# Codex Prompt 05 — Single-Case Extraction Vertical Slice

You are working inside the `legal_agentic_rag` repository.

## Objective
Harden one complete route: single-case extraction.

## Target outputs
- judges
- parties
- dates
- outcomes
- claim amounts when available

## Files to inspect first
- `apps/api/src/legal_rag_api/case_extraction_pg.py`
- `services/runtime/`
- `packages/retrieval/`
- `tests/fixtures/case_judgment_bundle/`
- `tests/integration/`
- `tests/scorer_regression/`

## Constraints
- Prefer deterministic extraction over generative synthesis.
- Preserve page-level source selection.
- Add tests for at least one longer case fixture.

## Acceptance criteria
- Stable case extraction on fixture corpus.
- Returned sources are page-level.
- Verify command passes.