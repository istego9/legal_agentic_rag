# Execution Plan: Strict Two-Stage Ingest, Re-Ingest, and IJob Sync

## 0. Context
Требования на этот цикл:
- без fallback-механизмов: если обязательного source artifact нет, операция должна завершаться `failed`;
- corpus документы должны хранить источник так, чтобы `re-ingest` был воспроизводим;
- ingest должен быть разделен на 2 pipeline:
  - stage A: parser/text processing;
  - stage B: AI-run (LLM extraction/enrichment) как отдельный запуск;
- статус обоих pipeline должен быть синхронизируемым с Job Center (`IJob`-совместимое представление).

## 1. Scope
### 1.1 In Scope
- strict source requirements для re-ingest;
- corpus reset flow (операционный);
- разделение ingest stage A и stage B;
- единый job projection layer для UI Job Center;
- API contract + web wiring + tests.

### 1.2 Out Of Scope
- изменение shared contest contracts (`QueryResponse`, `SubmissionAnswer`, `PageRef`);
- новые фреймворки/очереди/оркестраторы;
- workboard/wave-runner;
- redesign UI beyond existing Job Center surface.

## 2. Non-Negotiables
- [ ] Никаких silent fallback путей для source file resolution.
- [ ] Re-ingest разрешен только при наличии валидного `source_pdf_path` на диске.
- [ ] Stage A и Stage B должны иметь отдельные job statuses.
- [ ] Все job статусы должны отображаться в Job Center через единый projection.
- [ ] Никаких новых сущностей без явной необходимости; использовать существующие contracts/tables.

## 3. Current State Snapshot (2026-03-09)
- [x] Fallback для `source_pdf_path` удален из API.
- [x] Corpus и case extraction таблицы очищены (documents/pages/paragraphs/chunks/jobs = 0).
- [x] Текущий `re-ingest` strict: при отсутствии `source_pdf_path` -> `422 source_pdf_path is missing`.
- [x] Полный test suite green.

## 4. Target State
### 4.1 Stage A (Parser Ingest)
- API импортирует ZIP.
- Parser pipeline пишет canonical artifacts (`documents/pages/paragraphs/chunks`).
- Для каждого документа фиксируется source pointer (`processing.source_pdf_path`).
- Stage A job завершается независимо от Stage B.

### 4.2 Stage B (AI Run)
- Запускается отдельным endpoint-ом (batch by import job / by project / by document ids).
- Использует уже готовые artifacts Stage A.
- Записывает `corpus_enrichment_jobs` и enrichment outputs.
- Не выполняется автоматически внутри Stage A.

### 4.3 IJob Sync
- Job Center получает единый список job items:
  - stage A import jobs;
  - stage B enrichment jobs;
  - case extraction runs (если включены).
- Единые поля projection:
  - `job_id`, `job_type`, `status`, `started_at`, `updated_at`, `artifact_id`, `message`.

## 5. Work Breakdown Structure
### 5.1 Phase 0: Strict Mode Baseline
Tasks:
- [x] Удалить source fallback в `re-ingest` и document-file path resolution.
- [x] Удалить fallback-oriented tests.
- [x] Очистить corpus runtime state в Postgres.
- [ ] Добавить operator runbook команды для reset перед новым batch ingest.

Acceptance:
- [ ] Любой missing source -> deterministic fail.
- [ ] Ошибки не маскируются.

### 5.2 Phase 1: Stage Split (A/B)
Tasks:
- [ ] Разделить текущий `_run_import` на:
  - [ ] `_run_import_stage_a` (parser-only)
  - [ ] `_run_enrichment_stage_b` (AI-run)
- [ ] Сохранить backward-safe response shape для Stage A (`job_id`, `status`, diagnostics).
- [ ] Добавить endpoint запуска Stage B:
  - [ ] `POST /v1/corpus/enrichment-jobs/run`
  - [ ] input: `project_id | import_job_id | document_ids`
- [ ] Запретить implicit auto-start Stage B из Stage A.

Acceptance:
- [ ] Import endpoint завершает только Stage A.
- [ ] Stage B запускается явно и повторяемо.

### 5.3 Phase 2: Source Storage Hardening
Tasks:
- [ ] Зафиксировать contract правила:
  - [ ] `processing.source_pdf_path` обязателен для re-ingest;
  - [ ] path должен указывать на существующий PDF файл.
- [ ] Добавить ingest-time assert:
  - [ ] если source PDF не materialized -> ingest fail (не partial success).
- [ ] Добавить test fixture на missing source path -> expected failure.

Acceptance:
- [ ] Re-ingest работает только на валидных source artifacts.
- [ ] Нет неоднозначных состояний `completed` без source file.

### 5.4 Phase 3: IJob Projection and Job Center Sync
Tasks:
- [ ] Добавить API projection endpoint:
  - [ ] `GET /v1/jobs`
  - [ ] query: `project_id`, `limit`, `types`
- [ ] Projection sources:
  - [ ] `corpus_import_jobs`
  - [ ] `corpus_enrichment_jobs`
  - [ ] `case_extraction_runs`
- [ ] Нормализовать status mapping:
  - [ ] queued/running -> `processing`
  - [ ] completed -> `completed`
  - [ ] failed -> `failed`
- [ ] Подключить web Job Center к `/v1/jobs` (вместо локального activity-only view).

Acceptance:
- [ ] Job Center показывает реальные backend jobs, а не только client-side actions.
- [ ] Stage A/B читаются как разные job entries.

### 5.5 Phase 4: UI and Operator Controls
Tasks:
- [ ] Добавить явные кнопки/действия:
  - [ ] `Import (Stage A)`
  - [ ] `Run AI (Stage B)`
  - [ ] `Re-ingest document`
- [ ] В карточке документа показывать source readiness:
  - [ ] `source_pdf_path exists` -> ready
  - [ ] missing -> failed/blocked
- [ ] Добавить action `Reset Corpus` (operator-only path) с confirmation.

Acceptance:
- [ ] Оператор видит, на каком шаге процесс остановился.
- [ ] Нельзя случайно считать `ingest completed`, если Stage B еще не запускался.

### 5.6 Phase 5: Validation, Rollout, and Rollback
Tasks:
- [ ] Contract tests на stage split + strict source semantics.
- [ ] Integration tests:
  - [ ] import stage A only;
  - [ ] explicit stage B run;
  - [ ] re-ingest success/failure paths;
  - [ ] `/v1/jobs` aggregation correctness.
- [ ] Rebuild local docker stack и endpoint checks.
- [ ] Public `https://legal.build` verification.

Rollback:
- [ ] Feature-flag Stage Split off (temporary compatibility mode) при критическом блокере.
- [ ] Возврат к предыдущему routing в UI Job Center.

## 6. API Delta (Planned)
- Existing:
  - `POST /v1/corpus/import-zip` -> stage A only.
  - `POST /v1/corpus/import-upload` -> stage A only.
  - `POST /v1/corpus/documents/{id}/reingest` -> strict source required.
- New:
  - `POST /v1/corpus/enrichment-jobs/run`.
  - `GET /v1/jobs`.
  - optional: `POST /v1/corpus/admin/reset` (if operator reset via API is approved).

## 7. Data and Contract Notes
- Используются существующие сущности:
  - `corpus_import_jobs`
  - `corpus_enrichment_jobs`
  - `case_extraction_runs`
  - `documents.processing.source_pdf_path`
- Новые поля добавлять только если без них невозможно агрегировать jobs.
- Любое расширение response должно быть additive.

## 8. Validation Plan
- [ ] `PYTHONPATH=apps/api/src:. .venv/bin/pytest`
- [ ] `python3 scripts/agentfirst.py verify` (если будут configured steps)
- [ ] `cd infra/docker && docker compose up --build -d`
- [ ] `curl http://127.0.0.1:18000/docs`
- [ ] `curl http://127.0.0.1:15188/`
- [ ] `curl http://127.0.0.1:18080/`
- [ ] `curl http://127.0.0.1:18080/docs`
- [ ] `curl https://legal.build/`
- [ ] `curl https://legal.build/docs`

## 9. Open Decisions (Need Confirmation)
- [ ] Нужен ли отдельный endpoint reset (`/v1/corpus/admin/reset`) или reset остается только операционной SQL-командой.
- [ ] Точный внешний контракт `IJob` (если отличается от current Job Center projection) для финальной схемы `/v1/jobs`.
- [ ] Запуск Stage B: по `import_job_id` default или по `project_id` default.
