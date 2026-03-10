# Product Spec: Experiments and Leaderboard

## 0) Goal / Purpose
- Сделать любую гипотезу воспроизводимой, сравнимой и безопасной для merge.
- Цель модуля: быть операционной системой для experimentation loop, а не еще одним местом с бизнес-логикой.
- Агент может менять orchestration, caching, gating and report assembly, если experiment identities и compare semantics сохраняются.

## 1) Problem / Job-to-be-done
- Нам нужны сотни экспериментов за короткое окно.
- Без профилей, baseline и proxy gates команда начнет merge-ить шум.

## 2) Contracts / Boundaries
### Publishes
- experiment profiles
- experiment runs
- proxy/full gate results
- leaderboard rows
- links to runtime/eval artifacts

### Consumes
- runtime policies
- eval outputs
- gold datasets
- corpus processing versions

### Forbidden changes
- Встраивать scorer math прямо сюда.
- Встраивать retrieval/solver business logic.
- Терять version capture по experiment run.

## 3) Success criteria (acceptance)
- [ ] Каждый experiment run фиксирует versions всех relevant profiles.
- [ ] Есть proxy gate перед full run.
- [ ] Есть stable baseline and compare path.
- [ ] Leaderboard поддерживает slices by total/grounding/structured/free-text/TTFT.

## 4) Non-goals
- Не быть owner-ом corpus data.
- Не быть owner-ом gold review workflow.
- Не быть owner-ом UI design.

## 5) UX notes
- UI должен позволять запускать, сравнивать и фильтровать эксперименты без ручного лог-форензика.

## 6) Data / Telemetry
- Experiment run metadata:
  - profile id
  - stage type
  - baseline run id
  - sample size
  - runtime/eval artifact ids
  - metrics summary

## 7) Risk & Autonomy
- Риск: medium-high
- Автономность: L3
- Human judgment:
  - merge/rollback решения по пограничным улучшениям

## 8) Action items
- [ ] Freeze experiment profile schema.
- [ ] Add proxy/full execution flow.
- [ ] Add baseline comparison and gated rejection rules.
- [ ] Add cache key logic for repeatable stages.
- [ ] Add leaderboard and top-regression reports.

## 9) Validation plan
- Integration tests for experiment flow.
- Idempotency tests.
- Cache consistency tests.
- Baseline compare regression tests.
