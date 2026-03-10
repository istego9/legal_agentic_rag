# Product Spec: Retrieval and Evidence Selection

## 0) Goal / Purpose
- Поднимать grounding recall и answerability detection в пределах latency budget.
- Цель модуля: возвращать не просто "похожие тексты", а минимально достаточный и воспроизводимый evidence set для solver-а и export.
- Агент может менять retrieval heuristics, ranking, filters и evidence selection policy, если published candidate/evidence contracts и latency budgets сохраняются.

## 1) Problem / Job-to-be-done
- Конкурс штрафует за missing required pages сильнее, чем за умеренный over-citation.
- Текущий lexical bootstrap недостаточен для article lookup, lineage и cross-document cases.

## 2) Contracts / Boundaries
### Publishes
- ranked candidate paragraphs/pages
- explicit `retrieved` vs `used` semantics
- route-specific retrieval profile ids
- evidence selection output for solvers/export

### Consumes
- canonical corpus from ingest
- runtime policy and route name
- page/source identity invariants

### Forbidden changes
- Вмешиваться в answer normalization.
- Менять export schema.
- Подменять scorer logic.

## 3) Success criteria (acceptance)
- [ ] Source recall на gold/public растет без критического TTFT regression.
- [ ] Есть route-specific retrieval profiles.
- [ ] Used sources объяснимы и воспроизводимы.
- [ ] Over-citation контролируется per route.

## 4) Non-goals
- Не решать typed answer extraction.
- Не считать overall score.
- Не заниматься review workflow datasets.

## 5) UX notes
- UI должен показывать candidate list, used pages, scores и route profile.

## 6) Data / Telemetry
- Сохранять:
  - retrieval profile version
  - candidate count
  - selected used page count
  - query normalization trace
  - filter hits

## 7) Risk & Autonomy
- Риск: high
- Автономность: L3
- Human judgment:
  - допустимый over-citation budget
  - route-specific recall/latency trade-off

## 8) Action items
- [ ] Реализовать multi-stage retrieval.
- [ ] Добавить metadata filters by doc/article/law/case signals.
- [ ] Добавить route-specific profiles.
- [ ] Реализовать evidence selector with recall bias.
- [ ] Добавить debug trace for retrieval decisions.

## 9) Validation plan
- Public/internal gold grounding eval.
- Route-family regression fixtures.
- TTFT/p95 latency checks.
- Adversarial retrieval tests for near-miss pages and duplicate editions.
