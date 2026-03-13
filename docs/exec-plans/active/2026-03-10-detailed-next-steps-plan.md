# 2026-03-10 Detailed Next Steps Plan

## Objective

Convert the existing repository from a strong contract-first skeleton into a competition-grade, measurable, fail-closed system for the Legal Agentic RAG Challenge.

This plan assumes the current repository already contains:
- API surface in `apps/api/src/legal_rag_api`
- domain services in `services/`
- shared packages in `packages/`
- tests in `tests/`
- contracts/schemas/docs in `schemas/`, `openapi/`, `docs/`
- `AGENTS.md` and `.agentfirst/stack.yaml`

## Non-negotiable operating rules

1. No silent fallback answers.
2. No in-memory state on the contest path.
3. No stub ingest on the contest path.
4. No route may emit an answerable response without page sources.
5. Any change to runtime behavior must land with:
   - tests
   - trace/telemetry assertions
   - scorer impact note
   - docs update if contract changes

## Recommended execution order

### Wave 0 — Freeze the competition path
**Goal:** separate local bootstrap conveniences from contest runtime.

**Tasks**
- Add a single source of truth config flag: `COMPETITION_MODE=1`.
- In `apps/api/src/legal_rag_api/state.py`, remove permissive default behavior for contest mode.
- Ensure `InMemoryStore` remains test/local-only.
- Ensure any stub ingest path is blocked in competition mode.
- Add contract tests proving the service fails closed when contest persistence is unavailable.

**Acceptance criteria**
- Starting API with `COMPETITION_MODE=1` and no persistent backing store fails fast.
- Contest endpoints cannot load stub corpora.
- Integration tests explicitly cover this behavior.

### Wave 1 — Scorer becomes the product truth
**Goal:** all iterations are measured through the competition contract.

**Tasks**
- Harden scorer package under `packages/scorers/`.
- Add strict validation for:
  - answer schema
  - page source id format
  - telemetry completeness
  - empty-source behavior for no-answer cases
- Add scorer regression fixtures for at least 15 public questions across route families.
- Add one markdown scoreboard artifact per run in a temp/output folder or run registry.

**Acceptance criteria**
- A single command runs scorer regression locally.
- Score breakdown includes:
  - exact-answer accuracy
  - source precision/recall/F-beta style summary
  - telemetry completeness
  - no-answer precision/recall
  - TTFT/latency percentiles where available

### Wave 2 — Public dataset taxonomy
**Goal:** stop treating all questions as the same problem.

**Tasks**
- Create a normalized taxonomy file from `datasets/official_fetch_2026-03-11/questions.json`.
- Add labels:
  - `primary_route`
  - `answer_type_expected`
  - `document_scope`
  - `target_doc_types`
  - `temporal_sensitivity`
  - `answerability_risk`
- Store the file in a durable repo path:
  - `docs/exec-plans/active/public-dataset-taxonomy-v1.jsonl`
  - or `tests/fixtures/public_dataset_taxonomy/public_taxonomy_v1.jsonl`
- Add validation script to ensure every public question is labeled.

**Acceptance criteria**
- 100% of public questions are labeled.
- Router benchmark can load labels and compute confusion report.

### Wave 3 — Router benchmark
**Goal:** prove routing quality before retrieval tuning.

**Tasks**
- Benchmark current router against taxonomy labels.
- Emit confusion matrix and per-route errors.
- Promote a deterministic rules-first baseline.
- Keep LLM arbitration optional and explicitly traceable.

**Acceptance criteria**
- A benchmark command writes a report to `docs/exec-plans/active/benchmarks/`.
- Router never returns naked `unknown`; every miss includes `unhandled_reason`.

### Wave 4 — Vertical slice 1: article lookup
**Goal:** first full route from request to scored answer.

**Tasks**
- Choose 5–10 article-based public questions.
- Verify:
  - routing
  - retrieval
  - source selection
  - answer normalization
  - telemetry output
- Add end-to-end fixtures.
- Add a runbook for debugging article lookup misses.

**Acceptance criteria**
- One command executes the article slice and scorer.
- Failures are categorized by route/retrieval/source/normalization.

### Wave 5 — Vertical slice 2: single-case extraction
**Goal:** cover the second most important deterministic route.

**Tasks**
- Use case questions for judges, parties, dates, outcomes, amounts.
- Ensure case chunk projections expose the required fields.
- Add explicit regression tests on `tests/fixtures/case_judgment_bundle`.

**Acceptance criteria**
- Single-case extraction answers are deterministic where possible.
- Returned sources are page-level and stable.

### Wave 6 — No-answer and abstention hardening
**Goal:** avoid losing points to unsupported answers.

**Tasks**
- Add explicit no-answer route and detector.
- Require:
  - null or allowed no-answer form
  - empty sources
  - telemetry preserved
- Add adversarial fixtures based on out-of-domain criminal terms and absent concepts.

**Acceptance criteria**
- Unsupported queries never leak fabricated sources.
- No-answer behavior is separately measured in scorer regression.

### Wave 7 — Ingest hardening for contest path
**Goal:** turn ingest into a reproducible, non-stubbed pipeline.

**Tasks**
- Replace or isolate `ingest_zip_stub` from contest path.
- Add fixture corpus ingest tests.
- Assert every ingested paragraph maps to a page id.
- Assert document-type-specific projections are created.

**Acceptance criteria**
- Contest ingest path is deterministic and reproducible.
- No stub parser version appears in contest artifacts.

### Wave 8 — Gold + synth services
**Goal:** build controlled data improvement loops without contaminating official evaluation.

**Tasks**
- Harden `services/gold` and `services/synth`.
- Add provenance and separation rules:
  - official/public
  - internal gold
  - synthetic
- Add review/lock semantics for gold answers and source pages.

**Acceptance criteria**
- Gold and synth datasets are physically and logically separated.
- Synthetic examples cannot be accidentally mixed into official scorer runs.

### Wave 9 — Persistence, observability, and restart safety
**Goal:** make the system durable enough for full corpus and private-set runs.

**Tasks**
- Move runtime state to the persistent path already implied by `state_pg.py` / `runtime_pg.py`.
- Ensure runs, traces, telemetry, and selected sources survive process restart.
- Add restart-safety integration test.

**Acceptance criteria**
- Batch run interrupted and resumed retains run state correctly.
- Telemetry completeness survives restart scenarios.

### Wave 10 — Full public-set optimization loop
**Goal:** optimize only after measurement and route proof.

**Tasks**
- Run full public set nightly.
- Triage every failure by category.
- Promote only changes that improve measured score or reliability.
- Keep a simple changelog of score deltas in `docs/exec-plans/active/score-deltas.md`.

**Acceptance criteria**
- Every merge affecting runtime has a measurable before/after note.
- Regression suite grows only from real observed misses.

## Commit / PR order

1. PR-01 contest mode hardening
2. PR-02 scorer truth pack
3. PR-03 public taxonomy and router benchmark
4. PR-04 article vertical slice
5. PR-05 single-case vertical slice
6. PR-06 no-answer hardening
7. PR-07 ingest hardening
8. PR-08 gold/synth hardening
9. PR-09 persistence + restart safety
10. PR-10 public-set optimization loop

## Stop-doing list

- Do not add more abstract architecture docs before the first two vertical slices are measurable.
- Do not introduce online multi-agent query planning on the hot path.
- Do not let Codex create wide, cross-cutting PRs without route-specific tests.
- Do not use synthetic data as evidence of contest readiness.

## Done means

A task is only complete when:
- code is merged
- tests exist
- `python scripts/agentfirst.py verify --strict` passes
- if runtime behavior changed, local docker stack rebuilt and checked
- docs updated
- scorer impact recorded
