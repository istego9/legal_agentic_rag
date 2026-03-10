# Product Spec: Typed Solvers and No-Answer

## 0) Goal / Purpose
- Превращать retrieved evidence в корректные competition-style answers с контролируемым abstain path.
- Цель модуля: поднять structured accuracy и подавить hallucinations без избыточной зависимости от LLM.
- Агент может менять extraction rules, thresholds, prompts и route-specific solver internals, если answer contracts, abstain semantics и telemetry contracts сохраняются.

## 1) Problem / Job-to-be-done
- Structured questions составляют основную долю public set.
- Ошибочный confident answer на unanswerable question может стоить больше, чем аккуратный abstain.

## 2) Contracts / Boundaries
### Publishes
- answer
- answer_normalized
- confidence
- abstained flag
- route name
- used sources

### Consumes
- retrieval/evidence output
- runtime policy
- canonical corpus context

### Forbidden changes
- Менять `QueryResponse` shape.
- Возвращать не-empty sources для confident no-answer path.
- Подменять scorer logic внутри solver module.

## 3) Success criteria (acceptance)
- [ ] Отдельные solvers для `boolean`, `number`, `date`, `name`, `names`.
- [ ] Есть controlled free-text path.
- [ ] Есть explicit no-answer classifier и abstain thresholds.
- [ ] Structured accuracy и no-answer precision отслеживаются отдельно.
- [ ] `free_text` output contract совместим с contest note:
  - `1-3 paragraphs`
  - `<= 280 characters`
- [ ] Deterministic `null` semantics остаются first-class:
  - если ответ отсутствует и не может быть найден или выведен, solver возвращает `null`
  - canonical `no_answer` не экспортирует used pages

## 4) Non-goals
- Не реализовывать ingestion.
- Не хранить gold datasets.
- Не владеть experiment orchestration.

## 5) UX notes
- UI должен показывать route, confidence, abstain reason и normalized answer.

## 6) Data / Telemetry
- Сохранять:
  - solver version
  - abstain reason
  - answer type
  - confidence bucket
  - deterministic vs LLM path

## 7) Risk & Autonomy
- Риск: high
- Автономность: L3
- Human judgment:
  - canonical free-text no-answer phrasing
  - thresholds for abstain by answer type

## 8) Action items
- [ ] Реализовать typed extractors by answer type.
- [ ] Реализовать no-answer classifier.
- [ ] Реализовать route-aware answer templates.
- [ ] Нормализовать units, dates, names and lists.
- [ ] Зафиксировать free-text formatter под contest contract (`1-3 paragraphs`, `<= 280 chars`).
- [ ] Добавить regression fixtures на deterministic `null` behavior и empty-source no-answer semantics.
- [ ] Добавить solver regression fixtures и adversarial no-answer suite.

## 9) Validation plan
- Structured question regression set.
- No-answer precision/recall eval.
- Free-text quality spot checks on gold/public.
- Latency split by deterministic vs LLM path.
