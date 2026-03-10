# Codex Prompt 02 — Scorer Truth Pack

You are working inside the `legal_agentic_rag` repository.

## Objective
Make scorer regression the authoritative way to evaluate changes.

## Scope
Implement or harden scoring checks for:
- answer schema validity
- page source id validity
- telemetry completeness
- allowed no-answer form
- readable scorer summary output

## Files to inspect first
- `AGENTS.md`
- `packages/scorers/`
- `apps/api/src/legal_rag_api/telemetry.py`
- `apps/api/src/legal_rag_api/routers/eval.py`
- `apps/api/src/legal_rag_api/routers/runs.py`
- `tests/scorer_regression/`
- `public_dataset.json`

## Constraints
- Do not weaken current tests.
- No scoring change without at least one new regression test.
- Keep changes route-agnostic where possible.

## Deliverables
- scorer regression tests
- small run summary artifact or markdown output
- docs note under `docs/exec-plans/active/`

## Acceptance criteria
- Local scorer regression command exists and passes.
- Score summary includes no-answer and telemetry checks.
- Verify command passes.

## Commands
```bash
python scripts/agentfirst.py verify --strict
```