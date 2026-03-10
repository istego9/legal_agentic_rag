# Execution Plan: Agentic Challenge Win Plan

## Контекст
Цель проекта: оперативно собрать и улучшать competition-grade Legal Agentic RAG для `agentic-challenge.ai`.

North Star уже зафиксирован:

- page-level grounding/export является конкурсным source of truth;
- runtime должен быть `offline-heavy, online-light`;
- structured questions идут в deterministic-first path;
- free-text path допускает максимум один основной online LLM call;
- все существенные изменения проходят через versioned profiles и compare against baseline.

Текущий baseline на 2026-03-08:

- `./.venv/bin/python scripts/agentfirst.py verify` проходит;
- backend contract/integration/scorer regression tests: `46 passed`;
- web tests: `6 passed`;
- web build: green.

## Scope
- in-scope:
  - control-plane and contracts
  - ingest and corpus canonicalization
  - retrieval and evidence selection
  - typed solvers and no-answer
  - eval, scorer, and reporting
  - experiments and leaderboard
  - gold and synthetic data workflows
  - web research console
- out-of-scope:
  - `apps/ops`
  - workboard / wave-runner orchestration
  - separate control-panel workflow surface
  - новые product surfaces вне extracted Legal RAG scope

## План (итерации)
### Phase 0. Freeze central lane and baseline
- [ ] Подтвердить central source-of-truth: `contracts.py`, scaffold spec, runtime ADR, dataset contract.
- [ ] Зафиксировать `SHARED_CONTRACT_REGISTRY` и owner/version discipline для `PageRef`, `Telemetry`, `RuntimePolicy`, `QueryRequest`, `QueryResponse`, `SubmissionAnswer`.
- [ ] Зафиксировать active/fallback versions для `scoring`, `retrieval`, `solver`, `prompt`, `processing`.
- [ ] Снять baseline artifacts: текущий runtime profile, scorer policy, verify result, initial eval/report ids.
- [ ] Зафиксировать feature flags для risky tracks и rollback.

Gate:

- нет неявных shared contracts;
- есть baseline profile для сравнения;
- rollback можно сделать без ручного редактирования кода во всех модулях.

### Phase 1. Harden ingest, scorer, and operator visibility
- [ ] Довести ingest до deterministic baseline на повторных прогонах одного и того же входа.
- [ ] Реализовать controlled OCR fallback и явные parse diagnostics.
- [ ] Реализовать duplicate/version grouping и current-version policy.
- [ ] Довести scorer/reporting до contest-accurate decomposition по `S`, `G`, `T`, `F`.
- [ ] Добавить compare reports, top regressions и error taxonomy.
- [ ] Дать в web console минимально полезные панели: corpus diagnostics, run inspection, compare reports, unhealthy backend state.

Gate:

- repeated ingest -> те же canonical identities;
- scorer math закрыт regression tests;
- команда видит top failures без терминального форензика.

### Phase 2. Raise grounding through retrieval and evidence selection
- Detailed plan: `docs/exec-plans/active/phase-2-retrieval-grounding-and-evidence.md`
- [ ] Реализовать multi-stage retrieval поверх canonical corpus.
- [ ] Добавить metadata filters по article/law/case/lineage signals.
- [ ] Ввести route-specific retrieval profiles.
- [ ] Реализовать explicit `retrieved` vs `used` semantics.
- [ ] Реализовать evidence selector с recall bias и контролем over-citation.
- [ ] Добавить retrieval debug trace в API/UI artifacts.

Gate:

- source recall на gold/public растет относительно baseline;
- TTFT/p95 не деградируют beyond agreed budget;
- used pages воспроизводимы и объяснимы.

### Phase 3. Win structured path with typed solvers and no-answer
- [ ] Реализовать typed solvers для `boolean`, `number`, `date`, `name`, `names`.
- [ ] Реализовать explicit no-answer classifier и abstain thresholds.
- [ ] Нормализовать units, dates, names and lists.
- [ ] Держать controlled free-text path как fallback с одним главным LLM synthesis call.
- [ ] Добавить route-aware answer templates и abstain reasons в telemetry.
- [ ] Закрыть structured regression fixtures и adversarial no-answer suite.

Gate:

- structured accuracy растет против baseline;
- no-answer precision/recall считается отдельно и не деградирует silently;
- `QueryResponse` и submission semantics остаются совместимыми.

### Phase 4. Build the experiment operating system
- [ ] Freeze experiment profile schema.
- [ ] Реализовать proxy/full execution flow.
- [ ] Добавить baseline compare и gating rules на merge/promotion.
- [ ] Добавить cache key logic для repeatable stages.
- [ ] Реализовать leaderboard slices по total, grounding, structured, free-text, TTFT.
- [ ] Сделать из compare report обязательный вход для risky runtime changes.

Gate:

- каждое заметное изменение runtime проходит через experiment profile и compare against baseline;
- шумовые улучшения не проходят в merge без сигналов на proxy/full.

### Phase 5. Expand gold and synth around real failures
- [ ] Harden gold CRUD, review, lock, export.
- [ ] Добавить audit trail для mutating flows.
- [ ] Построить failure taxonomy clusters из compare reports.
- [ ] Направить synth generation только в реальные failure clusters.
- [ ] Ввести QA gates перед publish synthetic datasets.
- [ ] Проверить совместимость gold/synth exports с eval и experiments.

Gate:

- gold snapshots lockable и воспроизводимы;
- synth не генерирует шум вне реальных failure modes;
- новые датасеты улучшают research loop, а не засоряют его.

### Phase 6. Freeze, rollback readiness, and submission
- [ ] Выбрать active versions для retrieval/solver/prompt/scoring/processing profiles.
- [ ] Снять full compare против baseline и последнего stable candidate.
- [ ] Проверить telemetry completeness и `page_index_base` / `source_page_id` semantics.
- [ ] Провести dry-run submission export validation.
- [ ] Подготовить rollback candidate: предыдущий stable profile bundle.
- [ ] Зафиксировать final go/no-go checklist и release notes по freeze.

Gate:

- есть один явный submission candidate и один явный rollback candidate;
- export schema и grounding semantics не расходятся с contest contract;
- release решение принимается по метрикам, а не по интуиции.

## Параллелизация
1. Сначала только central lane:
   - control-plane and contracts
2. После freeze central lane можно параллелить:
   - ingest
   - eval/scorer/reporting
   - web research console
3. После появления стабильного canonical corpus можно параллелить:
   - retrieval and evidence selection
   - gold and synthetic data
4. После стабилизации retrieval contracts можно параллелить:
   - typed solvers and no-answer
   - experiments and leaderboard

## Decision log
- 2026-03-08: цель проекта зафиксирована как сборка competition-grade Legal Agentic RAG для `agentic-challenge.ai`.
- 2026-03-08: execution plan строится от зелёного `agentfirst verify`, а не от extraction-rescue сценария.
- 2026-03-08: общий порядок работ следует module dependency order из `docs/product-specs/modules/README.md`.

## Validation
- global:
  - `./.venv/bin/python scripts/agentfirst.py verify`
- contracts:
  - contract tests for shared schemas and additive compatibility
- ingest:
  - determinism checks on repeated ingest
  - regression fixtures for duplicate/version/broken PDFs
- retrieval/runtime:
  - proxy/full compare reports against baseline
  - route-family regressions
  - TTFT/p95 checks
- scorer:
  - scorer regression tests
  - property checks for source overlap math
- datasets:
  - export compatibility tests with eval pipeline
- web:
  - unit tests
  - contract smoke tests
  - manual validation for critical research journeys

## Rollback
- baseline rollback unit = previous stable profile bundle:
  - retrieval profile version
  - solver profile version
  - prompt policy version
  - scoring policy version
  - corpus processing version
- risky tracks должны включаться только через feature flags или active/fallback version switch.
- если proxy/full compare показывает regression по total score, grounding, telemetry completeness или TTFT, change set не промотируется.
- если submission candidate не проходит export/grounding validation, активируется предыдущий stable bundle без изменения shared contracts.
