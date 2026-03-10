# Codex Prompt 03 — Public Taxonomy and Router Benchmark

You are working inside the `legal_agentic_rag` repository.

## Objective
Create a fully labeled taxonomy for `public_dataset.json` and benchmark the router against it.

## Scope
1. Create a versioned taxonomy artifact under tests fixtures or docs active plan.
2. Add validation that every public question is labeled.
3. Add a benchmark script that:
   - runs the router over all public questions
   - compares route predictions to labeled routes
   - writes a confusion report and error list

## Required labels
- `primary_route`
- `answer_type_expected`
- `document_scope`
- `target_doc_types`
- `temporal_sensitivity`
- `answerability_risk`

## Files to inspect first
- `public_dataset.json`
- `packages/router/`
- `services/runtime/`
- `apps/api/src/legal_rag_api/routers/qa.py`
- `tests/contracts/`
- `tests/integration/`

## Constraints
- Prefer deterministic labeling + validation over auto-generated labels.
- Do not mix benchmark code into request path.
- Keep reports checked into a docs/exec-plans path only if small and useful.

## Acceptance criteria
- 100% taxonomy coverage.
- Benchmark script runs locally.
- Router misses are reported with reasons, not just counts.
- Verify command passes.