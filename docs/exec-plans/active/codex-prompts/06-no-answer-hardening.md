# Codex Prompt 06 — No-Answer Hardening

You are working inside the `legal_agentic_rag` repository.

## Objective
Add explicit, measurable no-answer handling.

## Scope
- Introduce or harden a no-answer route/detector.
- Ensure unsupported questions return the allowed no-answer form.
- Ensure no-answer responses return empty sources.
- Add adversarial fixtures.

## Files to inspect first
- `packages/router/`
- `services/runtime/`
- `packages/scorers/`
- `tests/scorer_regression/`
- `tests/integration/`

## Constraints
- No fabricated evidence.
- Telemetry must still be emitted.
- Do not collapse all low-confidence cases into no-answer.

## Acceptance criteria
- no-answer regression tests pass
- sources are empty on no-answer
- verify passes