# 2026-03-10 File Touch Map

## Files to modify first

### 1. Contest path hardening
**Modify**
- `apps/api/src/legal_rag_api/state.py`
- `apps/api/src/legal_rag_api/state_pg.py`
- `apps/api/src/legal_rag_api/runtime_pg.py`
- `apps/api/src/legal_rag_api/storage.py`
- `apps/api/src/legal_rag_api/routers/config.py` or equivalent runtime-config entrypoint

**Purpose**
- isolate local/in-memory state from competition runtime
- fail closed in `COMPETITION_MODE`

**Create**
- `tests/contracts/test_contest_mode_guardrails.py`
- `tests/integration/test_contest_mode_persistence.py`

### 2. Scorer truth pack
**Modify**
- `packages/scorers/`
- `apps/api/src/legal_rag_api/routers/eval.py`
- `apps/api/src/legal_rag_api/routers/runs.py`
- `apps/api/src/legal_rag_api/telemetry.py`

**Create**
- `tests/scorer_regression/test_public_contract_basics.py`
- `tests/scorer_regression/test_no_answer_contract.py`
- `tests/scorer_regression/test_source_page_contract.py`
- `docs/exec-plans/active/score-deltas.md`

### 3. Taxonomy and router benchmark
**Modify**
- `packages/router/`
- `services/runtime/`
- `apps/api/src/legal_rag_api/routers/qa.py`

**Create**
- `tests/fixtures/public_dataset_taxonomy/public_taxonomy_v1.jsonl`
- `tests/contracts/test_public_taxonomy_coverage.py`
- `tests/integration/test_router_benchmark.py`
- `scripts/benchmark_router.py`

### 4. Article vertical slice
**Modify**
- `services/runtime/`
- `packages/retrieval/`
- `apps/api/src/legal_rag_api/runtime_pg.py`

**Create**
- `tests/fixtures/article_lookup_bundle/`
- `tests/integration/test_article_lookup_slice.py`
- `docs/exec-plans/active/article-lookup-debug-runbook.md`

### 5. Single-case extraction vertical slice
**Modify**
- `services/runtime/`
- `packages/retrieval/`
- `apps/api/src/legal_rag_api/case_extraction_pg.py`

**Create**
- `tests/integration/test_single_case_extraction_slice.py`
- `docs/exec-plans/active/single-case-extraction-debug-runbook.md`

### 6. No-answer hardening
**Modify**
- `packages/router/`
- `services/runtime/`
- `packages/scorers/`

**Create**
- `tests/fixtures/no_answer_cases/`
- `tests/integration/test_no_answer_slice.py`

### 7. Ingest hardening
**Modify**
- `services/ingest/`
- `apps/api/src/legal_rag_api/corpus_pg.py`

**Create**
- `tests/integration/test_ingest_competition_path.py`
- `tests/contracts/test_ingest_page_mapping.py`

### 8. Gold and synth hardening
**Modify**
- `services/gold/`
- `services/synth/`
- `apps/api/src/legal_rag_api/routers/gold.py`
- `apps/api/src/legal_rag_api/routers/synth.py`

**Create**
- `tests/integration/test_gold_review_locking.py`
- `tests/integration/test_synth_dataset_provenance.py`

## Files to avoid touching casually

- `docs/ARCHITECTURE.md`
- `docs/PLANS.md`
- `openapi/`
- `schemas/`

These should only change when runtime contracts actually change. Do not let Codex rewrite them “for consistency”.

## Directory ownership model

- `apps/api/src/legal_rag_api/`: API composition, wiring, runtime adapters
- `services/`: domain behavior, workflows, business logic
- `packages/`: reusable route/retrieval/scoring logic
- `tests/`: contract/integration/performance/scorer proof
- `docs/exec-plans/active/`: current execution truth, score deltas, runbooks