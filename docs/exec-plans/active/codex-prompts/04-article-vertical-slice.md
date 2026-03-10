# Codex Prompt 04 — Article Lookup Vertical Slice

You are working inside the `legal_agentic_rag` repository.

## Objective
Harden one complete route: article lookup.

## Scope
Use 5–10 public questions that are clearly article-based and make this route work end to end:
- route
- retrieve
- source select
- answer normalize
- emit telemetry
- pass scorer checks

## Files to inspect first
- `services/runtime/`
- `packages/retrieval/`
- `packages/router/`
- `apps/api/src/legal_rag_api/runtime_pg.py`
- `tests/fixtures/`
- `tests/integration/`
- `tests/scorer_regression/`

## Constraints
- Keep the route deterministic where possible.
- Do not add a generative fallback just to make tests pass.
- Fail closed if evidence is insufficient.

## Deliverables
- route-specific integration tests
- scorer regression fixtures
- short debug runbook

## Acceptance criteria
- Article slice command runs locally.
- Every answerable test returns page sources.
- Verify command passes.