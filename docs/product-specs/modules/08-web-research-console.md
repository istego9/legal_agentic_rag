# Product Spec: Web Research Console

## 0) Goal / Purpose
- Дать оператору, исследователю и агенту визуальный доступ к corpus state, runtime outputs, eval deltas и experiment decisions.
- Цель модуля: ускорять diagnosis and iteration, а не владеть доменной логикой.
- Агент может менять layout, information density and workflow composition, если existing UI patterns, translation rules и backend contracts сохраняются.
- Phase 1 v3 уточнение:
  - основной review workflow = `question -> answer -> evidence -> PDF document`;
  - оператор видит used chunks/pages и может промоутить run result в draft gold.

## 1) Problem / Job-to-be-done
- Нужен единый internal console для corpus diagnostics, run inspection, compare reports, gold review и synth QA.
- Без этого исследовательский цикл остается терминальным и медленным.
- Проект должен быть верхним рабочим контейнером UI:
  - `project -> datasets -> runs -> eval -> experiments -> gold -> synth`
  - оператор работает и с комбинацией артефактов на уровне проекта, и с concrete objects внутри проекта.
- Naming semantics inside UI:
  - `Project` = session/work container
  - `Corpus` / `Ingest` = shared uploaded ZIP corpus package, reusable across project sessions
  - `Dataset` = question dataset, not ingest artifact
  - `Gold dataset` remains separate review/eval asset

## 2) Contracts / Boundaries
### Publishes
- none as business source-of-truth
- only UI flows, state wiring and diagnostics views

### Consumes
- stable API endpoints from corpus/runtime/eval/gold/synth/experiments/config
- translation keys
- HQ21 style constraints already adopted in the repo

### Forbidden changes
- Добавлять скрытую client-side business logic.
- Изобретать новые backend fields.
- Хардкодить UI strings вне translation tables.

## 3) Success criteria (acceptance)
- [ ] Есть workflows для corpus, QA, runs/eval, experiments, gold, synth and config.
- [ ] UI показывает statuses, metrics and artifacts without exposing raw complexity by default.
- [ ] Layout remains consistent with current Mantine/HQ21 direction.
- [ ] All labels are translatable.

## 4) Non-goals
- Не быть owner-ом contracts.
- Не быть owner-ом scoring logic.
- Не хранить state, который должен жить в API/storage.

## 5) UX notes
- Основная IA phase 1:
  - projects
  - project overview
  - corpus
  - datasets
  - review and runs
  - evaluation
  - experiments
  - gold
  - synthetic
  - config
- Object-first surfaces inside project:
  - shared corpus jobs
  - shared documents/pages/chunks
  - dataset questions
  - runs and run question review
  - eval runs and regressions
  - experiment profiles/runs/compare
  - gold datasets/questions
  - synth jobs
- Для run inspection обязателен split view:
  - question/evidence left pane
  - answer center pane
  - real PDF preview right pane
  - one-click promote-to-gold action
- Raw payloads and debug traces не должны доминировать в основном layout:
  - default UI = summaries, statuses, lists, validations
  - raw JSON = secondary debug drawer/panel
- Corpus document surfaces должны быть человеко-ориентированными:
  - default list labels prefer legal reference, doc type, year, and page count over internal ids or hashes
  - selected-page view should show extracted PDF page text plus chunk metadata needed for inspection
  - raw ids stay in debug payloads, not as primary labels
- Для long-running действий нужен явный job center / status surface:
  - processing
  - completed
  - failed
  - related artifact id
- Corpus import controls не должны требовать active project id для загрузки ZIP.
- Нужны состояния:
  - empty
  - loading
  - partial data
  - validation error
  - unhealthy backend

## 6) Data / Telemetry
- UI telemetry:
  - last loaded artifact ids
  - compare actions
  - filter usage
  - long-running requests visibility

## 7) Risk & Autonomy
- Риск: medium
- Автономность: L3
- Human judgment:
  - final UX composition
  - operator workflow prioritization

## 8) Action items
- [ ] Freeze project-centric navigation and active configuration rules.
- [ ] Freeze object surfaces inside project sections.
- [ ] Add views for scorer slices and top regressions.
- [ ] Add experiment compare and baseline views.
- [ ] Add gold/synth review surfaces.
- [ ] Keep raw payloads in secondary debug surfaces only.
- [ ] Prefer human-readable corpus document labels and chunk metadata in corpus inspection flows.
- [ ] Provide visible long-running job status and retry affordances.
- [ ] Ensure translations cover all new labels.

## 9) Validation plan
- Web unit tests.
- API contract smoke tests for consumed endpoints.
- Manual UI validation for critical research journeys.
- Build verification in `agentfirst verify`.
