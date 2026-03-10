# Legal RAG Extraction From LegalR

## Goal
- Extract the Legal RAG platform code from `/Users/artemgendler/dev/legal-arag` into this repository.
- Preserve runtime, ingest, retrieval, eval, experiments, gold/synth, product web UI, schemas, migrations, and contract surfaces.
- Exclude only the separate control-panel/workflow orchestration surface.

## Source / Target
- Source repo: `/Users/artemgendler/dev/legal-arag`
- Target repo: `/Users/artemgendler/dev/legal_agentic_rag`

## In Scope
- `apps/api`
- `apps/web`
- `services/ingest`
- `services/runtime`
- `services/eval`
- `services/experiments`
- `services/gold`
- `services/synth`
- `packages/contracts`
- `packages/prompts`
- `packages/retrieval`
- `packages/router`
- `packages/scorers`
- `db`
- `schemas`
- RAG-relevant docs/specs/ADRs/diagrams
- RAG tests
- `public_dataset.json`
- Minimal CI and local validation helpers

## Out Of Scope
- `apps/ops`
- `docs/workboard`
- workboard / wave-runner API and bridge
- `services/fly`
- control-panel/workflow-only specs
- generated logs, reports, test-results, caches, local virtualenv

## Action Items
- [ ] Copy the whitelisted source tree.
- [ ] Remove copied control-panel leftovers from API entrypoints, frontend entry points, and tests.
- [ ] Rewrite repo-level docs/config to describe the extracted product scope.
- [ ] Keep validation commands for backend plus product web, but exclude control-panel/workflow checks.
- [ ] Run compile/tests against the extracted repo.
- [ ] Record residual gaps, if any.

## Validation
- `python3 -m compileall apps/api/src services packages scripts tests`
- `PYTHONPATH=apps/api/src:. python3 -m pytest tests/contracts tests/integration tests/scorer_regression`

## Rollback
- Target repo is currently a fresh extraction workspace.
- If extraction scope proves wrong, delete the copied tree and repeat with a narrower whitelist.
