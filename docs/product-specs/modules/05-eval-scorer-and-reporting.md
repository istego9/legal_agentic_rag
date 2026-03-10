# Product Spec: Eval, Scorer, and Reporting

## 0) Goal / Purpose
- Дать команде contest-accurate систему измерения, чтобы решения о разработке принимались по метрикам, а не по ощущениям.
- Цель модуля: максимально точно mirror-ить competition scoring и объяснять, почему run стал лучше или хуже.
- Агент может менять scorer internals и reporting slices, если policy versioning и published report contracts сохраняются.

## 1) Problem / Job-to-be-done
- Без правильного scorer-а вся optimization loop слепая.
- Нужно отдельно видеть answer quality, grounding, telemetry completeness, TTFT и no-answer failures.

## 2) Contracts / Boundaries
### Publishes
- eval run result
- compare report
- metric slices by family/type
- question-level error taxonomy

### Consumes
- predictions from runtime
- gold datasets
- scoring policies
- telemetry payloads

### Forbidden changes
- Вмешиваться в runtime answer generation.
- Хардкодить organizer interpretation без versioned policy.
- Скрывать differences between policy versions.

## 3) Success criteria (acceptance)
- [ ] Overall score mirrors contest aggregation:
  - `Total = (0.7 * S_det_avg + 0.3 * S_asst_avg) * G * T * F`
- [ ] `S_det_avg` и `S_asst_avg` считаются отдельно и публикуются явно.
- [ ] Есть per-question and per-family diagnostics.
- [ ] Есть compare between runs and baseline.
- [ ] Policy versions can coexist.

## 4) Non-goals
- Не ingest corpus.
- Не решать retrieval.
- Не строить UI beyond report payload contracts.

## 5) UX notes
- UI должен показывать metric deltas, top regressions и error clusters.

## 6) Data / Telemetry
- Считать:
  - answer score
  - `S_det_avg`
  - `S_asst_avg`
  - grounding score
  - telemetry factor
  - TTFT factor
  - source recall/precision/f-beta
  - no-answer precision/recall
  - free-text judge dimensions:
    - correctness
    - completeness
    - grounding
    - appropriate confidence
    - clarity and relevance

## 7) Risk & Autonomy
- Риск: high
- Автономность: L2
- Human judgment:
  - when organizer rules are ambiguous
  - freeze choice of active scorer policy

## 8) Action items
- [ ] Version scoring policies.
- [ ] Привести scorer math к explicit contest formula с раздельными `S_det_avg` и `S_asst_avg`.
- [ ] Добавить regression tests на weighted `70/30` aggregation.
- [ ] Зафиксировать deterministic scoring rules:
  - `number` tolerance
  - `boolean` exact match
  - `name` exact match
  - `names` Jaccard
  - `date` ISO exact match
  - `null` exact-match semantics
- [ ] Зафиксировать TTFT modifier curve как versioned policy data, а не как неявный default.
- [ ] Отдельно проверить и version-ить organizer interpretation для telemetry factor, потому что из notes виден только final range `[0.90, 1.00]`.
- [ ] Add compare reports and leaderboard slices.
- [ ] Add question-level failure taxonomy.
- [ ] Add regression suites for scorer math.
- [ ] Prepare fallback policy if organizer clarifies rules differently.

## 9) Validation plan
- Scorer regression tests.
- Property tests for source overlap math.
- Golden comparison fixtures.
- Manual cross-check against organizer examples when available.
