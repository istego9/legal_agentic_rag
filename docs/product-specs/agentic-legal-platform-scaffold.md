# Product Spec: Agentic Legal Platform Scaffold

## 0) Goal / Purpose
- Собрать и быстро улучшать competition-grade Legal Agentic RAG platform для `agentic-challenge.ai`.
- Создать замороженный каркас платформы, к которому можно безопасно цеплять модули и вести разработку параллельно.
- Главная цель каркаса: ускорить поставку без конфликтов по архитектуре, контрактам и competition-critical правилам.
- Агент может менять внутреннюю реализацию любого модуля, если:
  - сохраняются published contracts и versioned policies;
  - не ломаются source/page identity, telemetry и submission export;
  - сохраняется прохождение `agentfirst verify` и целевых evals.

## 1) Problem / Job-to-be-done
- Пользователь: инженерная команда и агентные исполнители, которые должны параллельно собирать competition-grade платформу.
- Боль: без зафиксированного каркаса параллельная работа быстро превращается в конфликты по ID, схемам, scorer rules и runtime contracts.
- Почему сейчас: окно конкурса короткое, а нам нужно одновременно развивать ingestion, runtime, eval, experiments и supporting infrastructure.

## 2) Contracts / Boundaries
### Frozen source-of-truth
- `apps/api/src/legal_rag_api/contracts.py`
- `docs/exec-plans/active/legal-rag-extraction-from-legalr.md`
- `docs/design-docs/adr-2026-03-06-winning-runtime-north-star-v1.md`
- `public_dataset.json`

### Frozen global invariants
- Канонический source на конкурсе = page.
- Канонический `source_page_id` формат = `pdf_id_page`.
- Paragraph используется для retrieval, page используется для grounding/export.
- `QueryRequest`, `QueryResponse`, `Telemetry`, `PageRef`, `RuntimePolicy`, `SubmissionAnswer` не меняются без отдельного version bump.
- Scoring policy, prompt policy, retrieval profile и processing profile должны быть versioned.
- `reports/` хранит только artifacts, но не является source-of-truth для бизнес-логики.

### Shared module map
- `control-plane`: contracts, policies, exporter, feature flags, config registry.
- `ingest`: import ZIP/PDF, parse, dedupe, canonical corpus, lineage.
- `retrieval`: candidate generation, route profiles, evidence selection.
- `solvers`: typed answers, no-answer, free-text fallback.
- `eval`: contest scoring emulator, compare reports, metrics slices.
- `experiments`: orchestration, gating, baseline comparison, leaderboard.
- `gold-synth`: internal gold datasets, source sets, synthetic generation and QA.
- `web-console`: operator UI over stable APIs.

### Forbidden global changes without central approval
- Изменение `page_index_base` semantics.
- Изменение `Telemetry` shape без policy/version migration.
- Изменение submission export schema.
- Размытие границы между runtime scoring и eval scoring.
- Переизобретение shared entity names вне `contracts.py`.

## 3) Success criteria (acceptance)
- [ ] Все параллельные модули имеют явные published/consumed contracts.
- [ ] У каждого модуля есть цель, action items, acceptance criteria и validation plan.
- [ ] Есть понятная карта зависимостей: что делается централизованно, а что можно вести независимо.
- [ ] Любой агент может вносить локальные улучшения в модуль, не ломая общий каркас.

## 4) Non-goals
- Не перепроектировать архитектуру репозитория.
- Не вводить новые frameworks или infra layers.
- Не смешивать продуктовые идеи с implementation contracts.

## 5) UX notes
- UI не является владельцем бизнес-логики.
- Все UI labels должны проходить через translation keys.
- UI может развиваться поверх зафиксированных endpoint contracts.

## 6) Data / Telemetry
- Global telemetry contract:
  - request start
  - first token
  - completion time
  - input/output tokens
  - model name
  - route name
  - search profile
  - trace id
- Global experiment metadata:
  - corpus processing version
  - retrieval profile version
  - solver version
  - scorer version
  - prompt version
  - page index base

## 7) Risk & Autonomy
- Риск: high
- Автономность: L3 внутри модулей, L1 для глобальных контрактов
- Human judgment обязателен для:
  - изменения canonical identity;
  - изменения submission/export semantics;
  - изменения public scoring interpretation;
  - freeze/rollback решения.

## 8) Action items
- [ ] Заморозить global contracts и policy registry как центральную дорожку.
- [ ] Зафиксировать module ownership и dependency rules.
- [ ] Создать модульные ТЗ в `docs/product-specs/modules/`.
- [ ] Привязать каждую ветку разработки к одному модулю или одной central concern.
- [ ] Сливать изменения только через compare/eval against baseline.

## 9) Validation plan
- Запустить `./.venv/bin/python scripts/agentfirst.py verify`.
- Проверить, что модульные ТЗ не противоречат `contracts.py`, ADR и extracted repo scope.
- Для каждого change set требовать:
  - module-local tests;
  - affected contract tests;
  - proxy/full experiment report, если изменяется runtime path.
