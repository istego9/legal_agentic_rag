# Execution Plan: Phase 2 Score-Balanced Retrieval, Evidence, and Value Reporting

## Контекст
Phase 2 фиксирует score-balanced runtime improvement loop для текущего репозитория:

- retrieval и evidence selection улучшаются без version bump frozen shared contracts;
- score меряется не только по `overall_score`, а по `S/G/T/F`;
- в центре фазы стоит page-level grounding, но promotion требует отсутствия материального регресса на любой из осей;
- `research-driven-score-sprint.md` является подчинённым near-term slice этого документа, а не отдельным source-of-truth.

Текущий baseline на 2026-03-09:

- parser-only ingest, offline enrichment, review flow и `corpus_pg` parity уже есть;
- `./.venv/bin/python scripts/agentfirst.py verify` проходит;
- в репозитории уже есть retrieval traces, compare slices и experiments platform, но им не хватает unified value reporting, evidence compaction discipline и score-first route upgrades.

## Scope
- in-scope:
  - merged Phase 2 source-of-truth
  - value report by cohort inside existing eval/report surfaces
  - empty-source semantics for canonical `no_answer`
  - page-level evidence compaction and selector reasons
  - deterministic article/section/part/schedule lookup
  - retrieval core v2 with route-specific profiles
  - retrieval-aware abstain features
  - dynamic evidence budgets by `answer_type + route_family`
  - telemetry completeness gate and promotion reasons
- out-of-scope:
  - shared contract version bumps
  - full temporal legal graph redesign
  - dense retrieval as a core dependency
  - runtime NLI verifier in the online path
  - broad UI redesign or new product surfaces

## Success Criteria
- [ ] Phase 2 exists as one merged active execution plan.
- [ ] `value_report` shows which cohorts create or lose score/value.
- [ ] Canonical `no_answer` never exports used pages.
- [ ] Used page sets become more compact and reproducible on target fixtures.
- [ ] Deterministic structural lookup beats baseline on targeted structured fixtures.
- [ ] Retrieval-aware abstain improves no-answer behavior without hidden structured regressions.
- [ ] Promotion discipline requires no material regression on `S/G/T/F`.

## Plan (итерации)
### Iteration 0. Restore source-of-truth, baseline, and value cohorts
- [ ] Restore this Phase 2 doc as the canonical active plan.
- [ ] Update `research-driven-score-sprint.md` so it explicitly states it is a near-term slice under this plan.
- [ ] Freeze baseline bundle:
  - retrieval profile version
  - evidence selector version
  - no-answer policy version
  - telemetry gate version
- [ ] Freeze Phase 2 cohorts:
  - `route_family`
  - `answer_type`
  - `no_answer vs answerable`
  - `law vs case vs regulation`
  - `single-doc vs multi-doc`
  - `current-law vs history-lineage`
- [ ] Extend existing eval/report artifacts with `value_report` and weighted value signals.

Gate:

- one active Phase 2 source-of-truth exists;
- every candidate change can be judged by cohorts, not only by aggregate score.

### Iteration 1. Contract-safe wins on source semantics and evidence compaction
- [ ] Enforce empty-source semantics for canonical `no_answer`.
- [ ] Add page collapse and dedupe before final used-page export.
- [ ] Implement a set-cover style evidence selector over paragraph candidates.
- [ ] Persist selector reason codes:
  - `selected`
  - `collapsed`
  - `dropped`
  - `duplicate_suppressed`
  - `lineage_retained`

Gate:

- no-answer exports no used pages;
- compacted evidence packs stay grounded.

### Iteration 2. Deterministic structured path
- [ ] Parse `article`, `section`, `part`, and `schedule` references deterministically.
- [ ] Route structural references through dedicated lookup before generic lexical retrieval.
- [ ] Expand deterministic extraction for `number`, `date`, `money`, and `percentage`.
- [ ] Preserve generic retrieval fallback for malformed references.

Gate:

- targeted structured fixtures improve on answer + grounding without TTFT regression.

### Iteration 3. Retrieval core v2 and route-specific profiles
- [ ] Build multi-stage retrieval:
  - lexical projected search
  - exact/facet boosts
  - controlled lineage expansion for targeted routes only
- [ ] Introduce first route profiles:
  - `article_lookup_recall_v2`
  - `single_case_extraction_compact_v2`
  - `history_lineage_graph_v1`
- [ ] Keep current-version preference as a soft boost.
- [ ] Preserve parity between in-memory and `corpus_pg`.

Gate:

- target route families improve recall/grounding without storage-mode divergence.

### Iteration 4. Retrieval-aware abstain and dynamic evidence budget
- [ ] Log retrieval-quality features:
  - top candidate score gap
  - exact identifier hit
  - unique page count
  - candidate consensus
  - page-collapse ratio
- [ ] Introduce retrieval-aware abstain thresholds behind a versioned policy.
- [ ] Add dynamic evidence budgets by `answer_type + route_family`.
- [ ] Emit abstain reason labels.

Gate:

- no-answer precision improves and answerable structured paths do not regress silently.

### Iteration 5. Retrieval forensics, telemetry discipline, and experiment promotion
- [ ] Extend run-review artifacts with normalized query, route family, profile id, candidate count, used page count, filter hits, stage movement, selector reasons.
- [ ] Add shadow OTel-style telemetry mapping additively.
- [ ] Add telemetry completeness as a hard promotion gate.
- [ ] Record accepted/rejected promotion reasons inside experiment artifacts.
- [ ] Keep promotion score-balanced across `S/G/T/F`.

Gate:

- operator can explain retrieval/evidence decisions from artifacts;
- no profile is promoted without compare and telemetry gate pass.

## Validation
- `./.venv/bin/python scripts/agentfirst.py verify`
- contract tests for additive payload changes and no-answer source semantics
- retrieval fixtures for article, case, history, and duplicate-edition cases
- selector tests for set-cover/page collapse and required-page retention
- structured extraction tests for number/date/money
- no-answer tests for answerable vs unanswerable separation
- value report tests for cohort attribution and weighted value stability
- experiments tests for telemetry gate and promotion reasons

## Rollback
- rollback unit = previous stable bundle:
  - retrieval profile
  - evidence selector version
  - no-answer policy version
  - telemetry gate version
- failed Phase 2 changes roll back by switching active profile/policy versions, not by mutating shared contracts.
- hard rollback triggers:
  - material regression on `S`
  - material regression on `G`
  - telemetry completeness failure
  - TTFT regression beyond budget

## Deferred Tracks
- dense retrieval
- minimal temporal version model
- broad citation-graph expansion
- post-hoc verifier in eval
- synthetic unanswerable leaderboard slice

These remain explicit next-wave bets and do not enter active implementation until Iterations 0-5 are measured.
