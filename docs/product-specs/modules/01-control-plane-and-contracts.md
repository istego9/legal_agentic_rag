# Product Spec: Control Plane and Contracts

## 0) Goal / Purpose
- Создать центральный слой предсказуемости: versioned contracts, policy registry, feature flags и artifact/export rules.
- Цель модуля: дать остальным модулям стабильные точки подключения, чтобы агенты могли улучшать локальную реализацию без сбоев в интеграции.
- Агент может менять внутреннюю реализацию registry/config/export helpers, если published contracts и version semantics сохраняются.

## 1) Problem / Job-to-be-done
- Нужен один модуль-владелец общих правил.
- Без него ingestion, runtime, eval и experiments начинают расходиться по формату ответов, telemetry и policy names.

## 2) Contracts / Boundaries
### Publishes
- Shared Pydantic/OpenAPI contracts.
- Shared contract registry with owner + version labels for frozen boundary surfaces.
- Scoring policy registry.
- Retrieval/solver/prompt/profile version labels.
- Feature flags and rollout knobs.
- Submission export conventions.

### Consumes
- Existing `contracts.py`.
- Existing runtime/gold/eval/synth entity names.

### Forbidden changes
- Ломать `QueryRequest`, `QueryResponse`, `Telemetry`, `SubmissionAnswer`, `PageRef` без version bump.
- Менять semantics `source_page_id`.
- Менять export schema без explicit migration path.

## 3) Success criteria (acceptance)
- [ ] Все shared contracts перечислены и versioned.
- [ ] Реестр frozen shared contracts живет в одном source-of-truth слое и содержит owner + schema version.
- [ ] Есть единый реестр policy versions.
- [ ] Exporter и runtime/eval используют одни и те же contract names.
- [ ] Feature flags позволяют rollback без ручного редактирования кода во всех модулях.

## 4) Non-goals
- Не писать retrieval logic.
- Не писать solver logic.
- Не реализовывать UI workflows.

## 5) UX notes
- UI читает policy versions и config через API, но не владеет ими.

## 6) Data / Telemetry
- Versioned entities:
  - scoring policy
  - retrieval profile
  - solver profile
  - prompt policy
  - corpus processing profile
- Telemetry completeness обязана считаться одинаково в runtime и eval.

## 7) Risk & Autonomy
- Риск: high
- Автономность: L1
- Human judgment:
  - contract breakages
  - export semantics
  - contest rule reinterpretation

## 8) Action items
- [ ] Выписать полный список shared contracts.
- [ ] Зафиксировать shared contract registry и owner mapping в control-plane source-of-truth.
- [ ] Зафиксировать policy naming/versioning convention.
- [ ] Зафиксировать feature flags для risky tracks.
- [ ] Зафиксировать artifact naming для reports/exports.
- [ ] Добавить contract regression tests для critical schemas.

## 9) Frozen shared contract registry
- Source of truth: `apps/api/src/legal_rag_api/contracts.py`
- Registry symbol: `SHARED_CONTRACT_REGISTRY`
- Frozen boundary surfaces:
  - `PageRef`
  - `Telemetry`
  - `RuntimePolicy`
  - `QueryRequest`
  - `QueryResponse`
  - `SubmissionAnswer`
- Для этих surface additive changes допускаются только под явной version discipline; breaking changes требуют отдельный version bump и docs/tests update в одном change set.

## 10) Validation plan
- Contract tests.
- Submission export schema validation.
- Backward-compatibility checks for additive changes.

## 11) Active/Fallback Policy Rules
- Policy registry хранит `active_version`, `fallback_version`, `available_versions` для семейств:
  - `scoring`
  - `retrieval`
  - `solver`
  - `prompt`
- Runtime и eval обязаны использовать один и тот же `scoring_policy_version` из resolved policy labels.
- Backward-compatible loader сначала читает явный requested label (если передан), затем:
  - использует `active_version`, если label пустой;
  - использует `fallback_version`, если requested label не зарегистрирован.
- Явный rollback path: переключение `active_version` на предыдущий `fallback_version` без изменения scoring formulas.
