# Execution Plan: Case Judgment Two-Pipeline Direct Ingest (Detailed)

## 0. Summary
Цель: запустить два production-grade pipeline для судебных решений без WorkCore:
- `pipeline_1_case_judgment_router`
- `pipeline_2_case_judgment_extractor`

Ключевой принцип:
- bundle schemas являются primary source-of-truth для extraction artifacts;
- PostgreSQL используется как versioned storage + indexing + projection;
- routing делается rules-first и token-efficient;
- LLM применяется только на явно определенных шагах и только в strict structured mode.

### 0.1 Implementation Status (2026-03-09)
- [x] Phase 0 contract mirror + validator + contract tests.
- [x] Phase 1 DB migration files for versioned extraction artifacts.
- [x] Base implementation for Phase 2-5 in code:
  - router module (`services/ingest/case_judgment_router.py`)
  - document extractor (`services/ingest/case_judgment_document_extractor.py`)
  - chunk extractor (`services/ingest/case_judgment_chunk_extractor.py`)
  - QC engine (`services/ingest/case_judgment_qc.py`)
  - projection helper (`services/ingest/case_judgment_projection.py`)
  - orchestration module (`services/ingest/case_judgment_pipeline.py`)
- [x] API wiring for run/promote/revert endpoints in `routers/corpus.py`.
- [x] Seed script (`scripts/seed_case_judgment_bundle.py`) with `--validate-only/--seed-only/--reseed`.
- [x] Seed executed against local Docker Postgres (`127.0.0.1:15432`): 1 run, 1 document extraction, 37 chunk extractions, 1 QC row.

## 1. Scope
### 1.1 In Scope
- классификация типа судебного документа;
- document-level extraction;
- chunk-level extraction;
- versioned artifact storage;
- QC/gating/promotion;
- seed из bundle examples;
- тесты и метрики качества/стоимости.

### 1.2 Out Of Scope
- WorkCore orchestration;
- новый UI workflow;
- изменение конкурсного runtime QA flow;
- изменение текущих shared contracts (`QueryRequest`, `QueryResponse`, `PageRef`, `Telemetry`, `SubmissionAnswer`) в рамках этого контура.

## 2. Non-Negotiables
- [ ] Не ломать текущий canonical contour: `documents`, `pages`, `paragraphs`, `case_documents`, `case_chunk_facets`, `chunk_search_documents`.
- [ ] Не переименовывать поля bundle schemas в primary artifacts.
- [ ] Не хранить только SQL projection без полного bundle-compatible JSON payload.
- [ ] Не делать LLM-first классификацию.
- [ ] Не использовать полный raw PDF в router prompt.
- [ ] Каждый artifact и run должен быть versioned и replayable.
- [ ] Никаких destructive update для extraction artifacts.

## 3. Source Contracts
### 3.1 Bundle schemas (primary)
- `case_cluster.schema.json`
- `full_judgment_case_document.schema.json`
- `full_judgment_case_chunk.schema.json`
- `full_judgment_case_page.schema.json`
- `workflow_state_case_parse.schema.json`
- `workflow_state_eval.schema.json`

### 3.2 Bundle examples (seed fixtures)
- `arb_016_2023_case_cluster_example.json`
- `enf_269_2023_full_judgment_document_example.json`
- `enf_269_2023_selected_chunks_example.json`
- `enf_269_2023_section_map.json`

### 3.3 Validation policy
- [ ] Validation source = mirrored bundle schemas in repo.
- [ ] SQL schema validation не заменяет JSON schema validation.
- [ ] Любое поле, отсутствующее в SQL projection, но присутствующее в bundle schema, должно сохраняться в `payload JSONB`.

## 4. Target Architecture
### 4.1 High-level flow
1. Canonical ingest (уже существует) поднимает `documents/pages/paragraphs`.
2. Pipeline 1:
   - marker scan -> feature scan -> rule router -> optional LLM fallback -> route artifact.
3. Pipeline 2:
   - route validation -> page classes -> document extraction -> chunk extraction -> QC -> promotion.
4. Projection:
   - selected fields попадают в `case_chunk_facets`/`chunk_search_documents`.
5. Eval/trace:
   - run tokens, confidence, qc status, error taxonomy сохраняются отдельно.

### 4.2 Separation of concerns
- canonical layer: truth for document text and identities;
- extraction layer: truth for interpreted case-judgment artifacts;
- projection layer: truth for retrieval performance and filters.

## 5. Detailed WBS
### 5.1 Phase 0: Contract Freeze and Mirror
Outcome: репозиторий содержит immutable mirror bundle contracts.

Tasks:
- [ ] Создать директорию mirror, например `schemas/case_judgment_bundle/`.
- [ ] Скопировать 6 bundle schemas без изменения field names.
- [ ] Скопировать 4 example fixtures в `tests/fixtures/case_judgment_bundle/`.
- [ ] Добавить checksum file для схем и fixtures (sha256).
- [ ] Добавить validator utility для проверки JSON против mirrored schemas.
- [ ] Добавить docs note, что эти схемы primary для этого контура.

Acceptance criteria:
- [ ] Все 6 схем валидно читаются local validator-ом.
- [ ] Все 4 example JSON проходят validation.
- [ ] Любое изменение mirror-схемы требует явного docs change + test update.

Validation commands:
- [ ] `python scripts/agentfirst.py verify`
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/contracts -k case_judgment_bundle`

Rollback:
- [ ] Удалить mirror-файлы и связанные tests, если import выполнен с ошибочной версией bundle.

### 5.2 Phase 1: DB Migration for Versioned Artifacts
Outcome: есть отдельные таблицы run/artifact/qc, additive к текущей БД.

Tasks:
- [ ] Добавить migration `db/migrations/*_case_judgment_extraction_v1.up.sql`.
- [ ] Добавить down migration.
- [ ] Создать таблицу `case_extraction_runs`.
- [ ] Создать таблицу `case_document_extractions`.
- [ ] Создать таблицу `case_chunk_extractions`.
- [ ] Создать таблицу `case_extraction_qc_results`.
- [ ] Добавить FK/constraints для ссылочной целостности.
- [ ] Добавить unique rule для активной версии doc artifact.
- [ ] Добавить GIN index для `payload JSONB`.
- [ ] Добавить операционные индексы по `status`, `document_id`, `schema_version`.

Minimum columns (`case_extraction_runs`):
- `run_id`, `document_id`, `pipeline_name`, `pipeline_version`, `schema_version`, `prompt_version`, `model_name`, `model_reasoning_effort`, `parser_version`, `status`, `route_status`, `token_input`, `token_output`, `llm_calls`, `source_document_revision`, `started_at`, `completed_at`, `error_message`, `metadata`.

Minimum columns (`case_document_extractions`):
- `document_extraction_id`, `run_id`, `document_id`, `schema_version`, `artifact_version`, `is_active`, `supersedes_document_extraction_id`, `document_subtype`, `proceeding_no`, `case_cluster_id`, `court_name`, `court_level`, `decision_date`, `page_count`, `confidence_score`, `validation_status`, `payload`, `created_at`.

Minimum columns (`case_chunk_extractions`):
- `chunk_extraction_id`, `run_id`, `document_extraction_id`, `paragraph_id`, `page_id`, `document_id`, `schema_version`, `artifact_version`, `chunk_external_id`, `chunk_type`, `section_kind_case`, `paragraph_no`, `page_number_1`, `order_effect_label`, `ground_owner`, `ground_no`, `confidence_score`, `validation_status`, `payload`, `created_at`.

Minimum columns (`case_extraction_qc_results`):
- `qc_result_id`, `run_id`, `document_id`, `qc_stage`, `status`, `severity`, `message`, `details`, `created_at`.

Acceptance criteria:
- [ ] Migration up/down проходит на чистой БД.
- [ ] Нет конфликтов с existing tables/indices.
- [ ] Проверена уникальность активной версии документа по `schema_version`.
- [ ] Append-only semantics соблюдены.

Validation commands:
- [ ] `python scripts/agentfirst.py verify`
- [ ] миграционный smoke test (up/down/up).

Rollback:
- [ ] Применить down migration.
- [ ] Вернуть previous DB snapshot.

### 5.3 Phase 2: Pipeline 1 Router Implementation
Outcome: token-efficient router работает rules-first, LLM fallback only.

Tasks:
- [ ] Добавить module `services/ingest/case_judgment_router.py`.
- [ ] Реализовать `marker_scan(first_two_pages_text, filename, metadata)`.
- [ ] Реализовать `page_feature_scan(first_two_pages_text)`.
- [ ] Реализовать `rule_router(marker_state, feature_state)`.
- [ ] Реализовать `routing_confidence(rule_hits, conflicts, missing_markers)`.
- [ ] Реализовать ambiguity criteria для fallback.
- [ ] Реализовать LLM fallback caller с prompt `case_judgment_router_v1`.
- [ ] Реализовать structured parser для fallback JSON.
- [ ] Сохранить route artifact в `case_extraction_runs.metadata`.
- [ ] Сохранить token usage в `case_extraction_runs`.

Rules baseline (обязательно):
- [ ] `ORDER WITH REASONS` + orders before reasons + numbered reasons -> `full_reasons_parser`.
- [ ] `JUDGMENT` + sustained reasoning sections -> `full_judgment_parser`.
- [ ] orders без reasons marker -> `short_order_parser`.
- [ ] конфликт маркеров или недостаток сигнала -> `unknown` + optional LLM fallback.

Token/cost targets:
- [ ] Router LLM input <= 1800 tokens p50.
- [ ] Router completion <= 180 tokens p50.
- [ ] Fallback invocation rate <= 30% на representative batch.

Acceptance criteria:
- [ ] На bundle fixture-документе router возвращает ожидаемый subtype/profile.
- [ ] Ошибочные и пустые входы корректно получают `unknown`/retry bucket.
- [ ] Token usage фиксируется в runs table.

Validation commands:
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/integration -k case_judgment_router`
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/contracts -k router_prompt_schema`

Rollback:
- [ ] Feature flag off для нового router.
- [ ] Использовать существующий generic doc classifier path.

### 5.4 Phase 3: Pipeline 2 Document-Level Extraction
Outcome: document-level artifact в bundle-compatible форме.

Tasks:
- [ ] Добавить module `services/ingest/case_judgment_document_extractor.py`.
- [ ] Реализовать compact context builder:
  - front matter excerpt;
  - operative orders excerpt;
  - issuance excerpt;
  - reduced section summary.
- [ ] Вызов LLM с prompt `case_judgment_document_extractor_v1`.
- [ ] Structured output parsing и sanitization.
- [ ] JSON schema validation против mirrored `full_judgment_case_document.schema.json`.
- [ ] Persist full payload в `case_document_extractions.payload`.
- [ ] Persist promoted index fields (`document_subtype`, `proceeding_no`, `case_cluster_id`, etc.).
- [ ] Persist confidence and quality flags.

Critical checks:
- [ ] Не брать полный документ в prompt.
- [ ] Не генерировать значения, если нет evidence.
- [ ] Даты только `YYYY-MM-DD` или `null`.

Acceptance criteria:
- [ ] Bundle document fixture проходит schema validation.
- [ ] При low-confidence extraction artifact сохраняется, но `validation_status != passed`.
- [ ] Нет silent field drops.

Validation commands:
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/integration -k case_judgment_document_extractor`
- [ ] schema validator tests.

Rollback:
- [ ] Деактивировать document extractor stage флагом.
- [ ] Сохранять только route artifact до стабилизации.

### 5.5 Phase 4: Pipeline 2 Chunk-Level Extraction
Outcome: chunk artifacts валидны по bundle chunk schema и page-grounded.

Tasks:
- [ ] Добавить module `services/ingest/case_judgment_chunk_extractor.py`.
- [ ] Реализовать deterministic splitter для:
  - operative order items;
  - numbered reasoning paragraphs после reasons marker.
- [ ] Реализовать per-chunk context builder (document context + local chunk context).
- [ ] Вызов LLM с prompt `case_judgment_chunk_extractor_v1` по 1 чанку.
- [ ] Structured output parsing.
- [ ] JSON schema validation против mirrored `full_judgment_case_chunk.schema.json`.
- [ ] Persist full payload в `case_chunk_extractions.payload`.
- [ ] Link `paragraph_id`/`page_id` when available.
- [ ] Persist selected projection fields.

Critical checks:
- [ ] У каждого chunk artifact есть `case_number`, `chunk_type`, `section_kind_case`, `text_clean`, `chunk_summary`, `page_number_1`.
- [ ] `chunk_external_id` детерминированный и стабильный при replay.
- [ ] No guessed `order_effect_label`, `ground_owner`, `ground_no`.

Acceptance criteria:
- [ ] Chunk fixtures проходят schema validation.
- [ ] Все persisted chunks связаны с doc artifact.
- [ ] Нет chunk rows без `run_id`.

Validation commands:
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/integration -k case_judgment_chunk_extractor`
- [ ] targeted replay tests.

Rollback:
- [ ] Отключить chunk extraction stage.
- [ ] Хранить только document artifact до устранения дефектов.

### 5.6 Phase 5: QC, Promotion, and Rollback Controls
Outcome: artifacts проходят quality gates до `is_active=true`.

Tasks:
- [ ] Реализовать QC engine `services/ingest/case_judgment_qc.py`.
- [ ] Реализовать checks:
  - required sections present;
  - page ids consistent;
  - chunk minimum fields complete;
  - subtype-specific expectations met.
- [ ] Запись QC findings в `case_extraction_qc_results`.
- [ ] Реализовать promotion rule:
  - promote only if blocking QC checks pass.
- [ ] Реализовать deactivation/reactivation logic для rollback.

Blocking QC checks:
- [ ] Для `order_with_reasons` есть operative orders.
- [ ] Для `judgment`/`order_with_reasons` есть reasoning chunks.
- [ ] Для каждого chunk есть page reference.
- [ ] Для document artifact заполнен subtype и proceeding/case anchors (или flagged missing with severity).

Acceptance criteria:
- [ ] Promotion не проходит при blocking failure.
- [ ] Предыдущая активная версия сохраняется и доступна.
- [ ] Rollback переключает активную версию без потери history.

Validation commands:
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest tests/integration -k case_judgment_qc`

Rollback:
- [ ] Автоматический switch на previous active artifact при critical regression.

### 5.7 Phase 6: Seed and Backfill
Outcome: bundle examples загружены как reference baseline.

Tasks:
- [ ] Добавить seed script `scripts/seed_case_judgment_bundle.py`.
- [ ] Поддержать режимы:
  - `--seed-only`
  - `--validate-only`
  - `--reseed`.
- [ ] Загружать fixtures в versioned extraction tables.
- [ ] Метить seeded runs как `source=reference_bundle`.
- [ ] Добавить dry-run output.

Acceptance criteria:
- [ ] Seed script детерминированно повторяем.
- [ ] Duplicate seed не ломает constraints.
- [ ] Seed artifacts проходят schema validation.

Validation commands:
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/python scripts/seed_case_judgment_bundle.py --validate-only`
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/python scripts/seed_case_judgment_bundle.py --seed-only`

Rollback:
- [ ] Delete seeded rows by `source=reference_bundle` and run window.

### 5.8 Phase 7: Projection to Retrieval Layer
Outcome: validated extraction fields доступны retrieval/search без смены source contract.

Tasks:
- [ ] Реализовать projector `services/ingest/case_judgment_projection.py`.
- [ ] Маппинг полей только из validated artifacts.
- [ ] Обновлять `case_chunk_facets` и `chunk_search_documents` idempotent-режимом.
- [ ] Добавить projection version tag в metadata.

Acceptance criteria:
- [ ] Projection не запускается на failed QC artifacts.
- [ ] Projection idempotent по `(run_id, artifact_version)`.
- [ ] Retrieval индексы получают новые case facets без поломки existing queries.

Validation commands:
- [ ] retrieval contract tests.
- [ ] integration smoke на existing search endpoints.

Rollback:
- [ ] Disable projector stage.
- [ ] Rebuild search docs from previous active artifacts.

### 5.9 Phase 8: Observability and Runbook
Outcome: pipeline операбелен и отлаживаем.

Tasks:
- [ ] Добавить structured logs:
  - `trace_id`
  - `run_id`
  - `document_id`
  - `pipeline_stage`
  - `status`
  - `token_input`
  - `token_output`.
- [ ] Добавить stage latency metrics.
- [ ] Добавить fallback rate metric (router).
- [ ] Добавить QC failure rate metric.
- [ ] Добавить alert thresholds:
  - high failure rate;
  - token spike;
  - fallback surge.
- [ ] Добавить runbook doc for incident handling.

Acceptance criteria:
- [ ] Любой failed run можно трассировать по `run_id`.
- [ ] Token/cost и quality metrics доступны по фазам.
- [ ] Есть documented procedure для replay и rollback.

## 6. Prompt Program (Detailed)
### 6.1 Prompt versions
- current baseline assets:
  - `case_judgment_router_v1.md`
  - `case_judgment_document_extractor_v1.md`
  - `case_judgment_chunk_extractor_v1.md`
- planned stabilization:
  - [ ] `v2`: stricter ambiguity behavior
  - [ ] `v3`: precision-first tuning for legal entities/effects (requested by user)

### 6.2 Prompt governance
- [ ] Любая новая версия prompt получает `prompt_version` label и changelog.
- [ ] A/B сравнение только через controlled fixtures.
- [ ] Promotion prompt version только при:
  - schema validity no worse than baseline;
  - precision not degraded on critical fields;
  - token budget in bounds.

### 6.3 Prompt constraints
- [ ] Structured outputs only (`json_schema`).
- [ ] `temperature=0`.
- [ ] `n=1`.
- [ ] Без chain-of-thought в output.
- [ ] Явный `unknown` вместо галлюцинации.

## 7. Model and Cost Plan (Detailed)
### 7.1 Router
- baseline model: `gpt-5-mini`, `reasoning_effort=minimal`.
- candidate model: `gpt-5-nano` for cost cut.
- promotion rule:
  - [ ] F1 on router labels not worse by >1.0 pp.
  - [ ] fallback rate not worse by >5.0 pp.
  - [ ] median cost decreases.

### 7.2 Document extraction
- baseline model: `gpt-5-mini`.
- reasoning:
  - default `minimal`;
  - escalate to `low` only for ambiguous slices.
- escalation model: `gpt-5` for QC-failed re-runs.

### 7.3 Chunk extraction
- baseline: `gpt-5-mini`, `minimal`.
- only one chunk per request to control drift and retry scope.

### 7.4 Cost guardrails
- [ ] Router p50 input tokens <= 1800.
- [ ] Router p95 input tokens <= 2500.
- [ ] Document extraction p50 input tokens <= 5000.
- [ ] Chunk extraction p50 input tokens <= 1300.
- [ ] Reject/retry policy when token budget exceeded.

## 8. Test Matrix
### 8.1 Contract tests
- [ ] Mirror bundle schema validation tests.
- [ ] Negative tests with missing required fields.
- [ ] AdditionalProperties handling tests.

### 8.2 Migration tests
- [ ] up/down/up migration deterministic.
- [ ] constraints and unique rules enforced.
- [ ] index presence checks.

### 8.3 Router tests
- [ ] positive fixtures:
  - order_with_reasons
  - judgment
  - short_order.
- [ ] ambiguous fixture -> fallback path.
- [ ] OCR-noisy fixture -> unknown/retry path.

### 8.4 Extraction tests
- [ ] document extraction schema pass.
- [ ] chunk extraction schema pass.
- [ ] date normalization checks.
- [ ] no hallucinated values when missing.

### 8.5 QC tests
- [ ] blocking failures prevent promotion.
- [ ] warning-only findings allow promotion.
- [ ] rollback restores previous active version.

### 8.6 Replay tests
- [ ] same input -> new artifact_version.
- [ ] previous versions remain queryable.
- [ ] projections idempotent.

### 8.7 Integration tests
- [ ] end-to-end run from canonical document to active extraction artifact.
- [ ] run failure propagation and error logging.
- [ ] token metrics persisted.

### 8.8 Regression tests
- [ ] known bundle examples always pass.
- [ ] regression baseline snapshots stored.

## 9. API and Service Change Plan
### 9.1 Expected touched files/modules
- `services/ingest/case_judgment_router.py` (new)
- `services/ingest/case_judgment_document_extractor.py` (new)
- `services/ingest/case_judgment_chunk_extractor.py` (new)
- `services/ingest/case_judgment_qc.py` (new)
- `services/ingest/case_judgment_projection.py` (new)
- `apps/api/src/legal_rag_api/routers/corpus.py` (wire pipeline endpoints)
- `db/migrations/*_case_judgment_extraction_v1.*.sql` (new)
- `scripts/seed_case_judgment_bundle.py` (new)
- `tests/contracts/*` (new)
- `tests/integration/*` (new)

### 9.2 Endpoint plan
- [ ] Add run endpoint for pipeline 1 (router).
- [ ] Add run endpoint for pipeline 2 (extractor).
- [ ] Add run status endpoint by `run_id`.
- [ ] Add endpoint to promote/revert active artifact.

## 10. Rollout Gates
### Gate A: Contracts/Migration Ready
- [ ] mirror schemas + fixtures ready;
- [ ] migration tests pass.

### Gate B: Router Ready
- [ ] router accuracy target met;
- [ ] token budget target met.

### Gate C: Extraction Ready
- [ ] doc/chunk schema pass rates acceptable;
- [ ] QC pipeline blocks bad artifacts.

### Gate D: Projection Ready
- [ ] projected fields visible in retrieval;
- [ ] no regression in existing search API.

### Gate E: Operability Ready
- [ ] logs/metrics/runbook complete;
- [ ] replay and rollback tested.

## 11. Risk Register
### R1: Schema drift from bundle
Mitigation:
- [ ] immutable mirror;
- [ ] strict validator in CI.

### R2: Router false classification
Mitigation:
- [ ] rules-first plus fallback;
- [ ] ambiguity bucket and confidence thresholds.

### R3: Extraction hallucinations
Mitigation:
- [ ] strict schema + null-on-missing policy;
- [ ] QC blocks and re-run escalation.

### R4: Token/cost spike
Mitigation:
- [ ] compact context builders;
- [ ] hard caps;
- [ ] per-run token telemetry and alerts.

### R5: Broken active artifact promotion
Mitigation:
- [ ] promotion only after blocking QC pass;
- [ ] one active artifact constraint;
- [ ] tested rollback.

## 12. Definition of Done (This Initiative)
- [ ] Bundle schemas mirrored and validated.
- [ ] New DB tables deployed with tests.
- [ ] Pipeline 1 router live with metrics.
- [ ] Pipeline 2 document/chunk extraction live with QC.
- [ ] Seed fixtures loaded and reproducible.
- [ ] Projection to retrieval layer integrated.
- [ ] End-to-end tests green.
- [ ] `python scripts/agentfirst.py verify` green.
- [ ] For runtime behavior changes:
  - [ ] `cd infra/docker && docker compose up --build -d`
  - [ ] verify `http://127.0.0.1:18000/docs`
  - [ ] verify `http://127.0.0.1:15188/`
  - [ ] verify `http://127.0.0.1:18080/`
  - [ ] verify `http://127.0.0.1:18080/docs`

## 13. Execution Order (Strict)
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7
9. Phase 8

Параллелить разрешено только после Gate B:
- extraction modules
- tests
- observability wiring

## 14. Immediate Next Implementation Tasks
- [ ] Mirror bundle schemas/examples into repo.
- [ ] Add migration for versioned extraction tables.
- [ ] Add schema validator utility + tests.
- [ ] Implement router module (rules + fallback).
- [ ] Implement run persistence in `case_extraction_runs`.

## 15. Decision Log
- 2026-03-09: WorkCore excluded for this contour.
- 2026-03-09: bundle schemas fixed as primary contracts.
- 2026-03-09: routing policy fixed as rules-first + LLM-fallback.
- 2026-03-09: extraction artifacts fixed as append-only versioned records.
- 2026-03-09: detailed execution runbook approved for implementation.
