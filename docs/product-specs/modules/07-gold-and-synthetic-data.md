# Product Spec: Gold and Synthetic Data

## 0) Goal / Purpose
- Создавать и поддерживать high-signal datasets, которые реально улучшают runtime, retrieval и scorer calibration.
- Цель модуля: поставлять trustworthy training/eval material для research loop, а не просто производить много данных.
- Агент может менять review workflow internals, candidate generation rules и QA gates, если published dataset/export contracts и review semantics сохраняются.

## 1) Problem / Job-to-be-done
- Нужен internal gold для анализа ошибок и проверки гипотез.
- Нужен synthetic pipeline только на реальные failure modes, иначе он создаст шум вместо сигнала.

## 2) Contracts / Boundaries
### Publishes
- gold datasets
- gold questions with source sets
- review status and lock state
- synthetic jobs, candidates and published datasets

### Consumes
- canonical corpus
- source identities
- eval/scoring policies

### Forbidden changes
- Публиковать synthetic datasets без QA gate.
- Ломать immutable behavior locked gold datasets.
- Генерировать page ids не из canonical corpus.

## 3) Success criteria (acceptance)
- [ ] Gold workflow supports create, review, lock, export.
- [ ] Synthetic jobs support preview, approve/reject, publish.
- [ ] Synthetic generation targets real failure clusters.
- [ ] Gold/synth datasets are consumable by eval and experiments.

## 4) Non-goals
- Не быть primary runtime path.
- Не подменять official public/private competition data.

## 5) UX notes
- UI должен давать reviewer-у быстрый доступ к answer, sources, notes и lock status.

## 6) Data / Telemetry
- Нужны поля:
  - review decision
  - reviewer notes
  - lock snapshot version
  - candidate provenance
  - QA gate result

## 7) Risk & Autonomy
- Риск: medium
- Автономность: L3
- Human judgment:
  - gold review decisions
  - synthetic publish approval

## 8) Action items
- [ ] Harden gold CRUD + review + lock.
- [ ] Add audit trail for mutations.
- [ ] Target synth generation at failure taxonomy clusters.
- [ ] Add QA gates before publish.
- [ ] Ensure exports are machine-readable and eval-compatible.

## 9) Validation plan
- Integration tests for gold workflow.
- Integration tests for synth publish gate.
- Export compatibility tests with eval pipeline.
- Audit log assertions for mutating operations.
