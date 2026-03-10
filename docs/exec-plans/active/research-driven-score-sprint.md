# Execution Plan: Research-Driven Score Sprint

## Контекст
Этот план переводит результаты deep research от 2026-03-09 в ближайший execution slice для текущего репозитория.

Он не заменяет и не конкурирует с:

- `docs/exec-plans/active/agentic-challenge-win-plan.md`
- `docs/exec-plans/active/phase-2-retrieval-grounding-and-evidence.md`

Этот документ считается near-term score sprint slice внутри merged Phase 2 plan.

Он сужает ближайшие 2 недели до набора гипотез, которые:

- совместимы с frozen contracts;
- усиливают page-level grounding и deterministic-first runtime;
- не требуют архитектурного разворота в LLM-first или full GraphRAG;
- дают compare-against-baseline signal, а не только "интересную идею".

Спринт опирается на top hypotheses из research synthesis:

- A: evidence pack set-cover / page collapse
- C: retrieval-quality features -> no-answer policy
- D: deterministic article/section lookup
- F: dynamic evidence budget
- H: telemetry completeness gate / shadow OTel mapping
- I: explicit empty-source semantics for no-answer

Текущее состояние на 2026-03-09:

- `./.venv/bin/python scripts/agentfirst.py verify` проходит;
- shared contracts уже зафиксированы в `contracts.py`;
- есть активный Phase 2 retrieval plan, но нужен более узкий score-first sprint для ближайшей поставки.

## Scope
- in-scope:
  - explicit no-answer source semantics
  - page-level evidence pack compaction and over-citation control
  - deterministic `article` / `section` / `part` / `schedule` lookup path
  - structured deterministic extraction improvements for date/number/money style questions
  - retrieval-quality features for abstain decisions
  - dynamic evidence budget by `answer_type + route_family`
  - telemetry completeness as experiment promotion gate
  - compare-ready slices and artifacts for sprint hypotheses
- out-of-scope:
  - version bump of `PageRef`, `Telemetry`, `RuntimePolicy`, `QueryRequest`, `QueryResponse`, `SubmissionAnswer`
  - full temporal legal graph redesign
  - runtime NLI verifier in the online request path
  - multi-agent orchestration or LLM-first routing
  - broad web-console redesign
  - introducing new frameworks, libraries, or product surfaces

## Success Criteria
- [ ] `no_answer` path never exports used pages unless an explicit route policy justifies it.
- [ ] Used page sets become more compact and more reproducible on target fixtures without dropping required pages.
- [ ] Deterministic article/section lookup outperforms the current baseline on targeted structured fixtures.
- [ ] Structured deterministic extraction improves exact-answer accuracy for date/number/money slices without TTFT regression.
- [ ] Retrieval-aware abstain logic improves no-answer precision without silent regressions on answerable structured questions.
- [ ] Telemetry completeness becomes a hard gate for experiment promotion.
- [ ] All sprint changes remain switchable through versioned profiles or explicit flags, not hard-coded forks.

## Plan (итерации)
### Iteration 0. Freeze baseline, slices, and acceptance rules
- [ ] Record one explicit baseline bundle for this sprint:
  - retrieval profile id
  - evidence selector version
  - solver profile version
  - telemetry policy version
- [ ] Freeze sprint evaluation slices:
  - `article_lookup`
  - `no_answer`
  - structured `number` / `date`
  - structured `name` / `names`
  - free-text control slice
- [ ] Define acceptance metrics for every experiment:
  - page recall
  - used page count
  - over-citation proxy
  - no-answer precision / recall
  - TTFT / total latency
  - telemetry completeness
- [ ] Add one compare report template for this sprint so hypotheses are judged on the same artifact shape.

Gate:

- one explicit baseline artifact exists;
- every sprint hypothesis has a measurable success and failure condition;
- no change proceeds without a baseline compare target.

### Iteration 1. Contract-safe wins on source semantics and evidence compaction
- [ ] Enforce explicit empty-source semantics for canonical `no_answer` responses.
- [ ] Add regression tests that prove:
  - `abstained=true` + canonical no-answer -> empty used page set
  - submission export does not include sources for canonical no-answer
- [ ] Implement page-collapse and dedupe rules over retrieved paragraph candidates before final used-page export.
- [ ] Add a lightweight set-cover style evidence selector over top-ranked candidate paragraphs so the output prefers the minimum sufficient page set.
- [ ] Persist selector reason codes that explain why a page was selected, collapsed, or dropped.

Gate:

- contract and regression tests are green;
- used page sets are smaller or equal on target fixtures;
- required grounding pages are not lost in the compacted pack.

### Iteration 2. Deterministic structured retrieval boost
- [ ] Implement deterministic parsing for `article`, `section`, `part`, and `schedule` references in question text.
- [ ] Route these patterns through a dedicated structural lookup path before generic lexical retrieval.
- [ ] Reuse existing corpus metadata and document structure only; do not invent new shared entities.
- [ ] Expand deterministic extraction for `number`, `date`, `money`, and percentage-like answers from top evidence pages before any LLM fallback.
- [ ] Add targeted fixtures for:
  - article lookup
  - commencement / effective date
  - monetary amount
  - structured comparison with explicit legal identifiers

Gate:

- targeted structured fixtures beat the baseline in answer + grounding;
- TTFT does not regress beyond agreed budget for these routes;
- fallback to generic retrieval remains available for malformed references.

### Iteration 3. Retrieval-aware abstain and dynamic evidence budget
- [ ] Log retrieval-quality features needed for abstain policy:
  - top candidate score gap
  - unique page count
  - exact identifier hit flags
  - candidate consensus on extracted answer
  - page-collapse ratio
- [ ] Introduce retrieval-aware abstain thresholds behind a versioned solver profile.
- [ ] Add dynamic evidence-budget rules by `answer_type + route_family`, with explicit hard maximums.
- [ ] Compare answerable and unanswerable slices separately; do not merge them into one coarse confidence score.
- [ ] Add reason labels for abstain outcomes:
  - no corpus support
  - conflicting evidence
  - insufficient uniqueness
  - low retrieval quality

Gate:

- no-answer precision improves on the sprint slice;
- answerable structured accuracy stays within agreed non-regression budget;
- evidence packs stay within route-level page budgets.

### Iteration 4. Telemetry and promotion discipline
- [ ] Add telemetry completeness as a hard experiment gate, not an informational metric.
- [ ] Map current runtime telemetry into a shadow OTel-style representation for:
  - TTFT
  - total response time
  - token counts
  - model / route / profile identity
  - trace id
- [ ] Keep the shadow mapping additive-only; do not break frozen telemetry contracts.
- [ ] Extend compare reports with sprint-specific slices:
  - article lookup
  - no-answer
  - structured numeric/date
  - over-citation proxy
  - telemetry completeness
- [ ] Record accepted and rejected experiment decisions with the regression reason.

Gate:

- no sprint profile is promoted without score + telemetry compare;
- latency regressions and missing telemetry are visible in the same decision artifact.

### Iteration 5. Prepare the next-wave bets without starting them early
- [ ] Define explicit entry criteria for:
  - minimal temporal version model
  - citation graph expansion
  - post-hoc `VeriCite-lite` eval verifier
  - UAEval4RAG-style synthetic unanswerable slice
- [ ] Keep these tracks deferred until Iterations 1-4 produce stable signals.
- [ ] Pre-register the expected metrics and failure modes for each deferred track so later work starts from compare discipline, not from intuition.

Gate:

- deferred bets have explicit prerequisites;
- the sprint closes with a ranked next-wave backlog instead of parallel uncontrolled tracks.

## Workstreams
### A. Source Semantics and Evidence Policy
- empty-source no-answer behavior
- page collapse
- set-cover style compact evidence packs
- selector reason codes

### B. Deterministic Structured Path
- article/section/part/schedule parsing
- structural lookup
- deterministic extraction for dates, numbers, money, percentages

### C. Abstain and Budgeting
- retrieval-quality features
- abstain thresholds
- dynamic evidence budgets
- route-aware page caps

### D. Telemetry and Promotion
- telemetry completeness gate
- shadow OTel mapping
- sprint compare slices
- promotion / rejection logging

## Deferred Tracks
- [ ] Minimal temporal model for `current` / `amended` / `consolidated` questions.
- [ ] One-hop citation graph expansion for cross-law retrieval.
- [ ] Post-hoc claim-to-page verifier for eval and failure clustering.
- [ ] Synthetic unanswerable generation with DIFC-flavored false presuppositions.

These remain deferred until the contract-safe and score-first sprint changes are measured.

## Decision Log
- 2026-03-09: this sprint operationalizes hypotheses A, C, D, F, H, and I from the deep-research synthesis.
- 2026-03-09: hypotheses E, G, J, and K are explicitly deferred until the cheaper score-first wins are measured.
- 2026-03-09: no shared contract version bump is allowed in this sprint.
- 2026-03-09: the online runtime remains `offline-heavy, online-light` with no new mandatory LLM routing step.

## Validation
- global:
  - `./.venv/bin/python scripts/agentfirst.py verify`
- contracts and regressions:
  - `PYTHONPATH=apps/api/src:. ./.venv/bin/python -m pytest tests/contracts tests/integration tests/scorer_regression`
  - targeted route fixtures for `article_lookup`, `no_answer`, `number`, `date`, `name`, `names`
- compare discipline:
  - proxy compare against frozen sprint baseline
  - full compare before promotion
  - review of `S`, `G`, `T`, `F` plus sprint-specific slices
- latency and telemetry:
  - TTFT / total response checks on sprint slices
  - telemetry completeness gate must pass
- console and diagnostics:
  - run-review smoke checks for used pages, abstain reasons, and compare artifact visibility

## Rollback
- rollback unit = previous stable sprint profile bundle:
  - retrieval profile
  - evidence selector version
  - solver profile
  - telemetry policy version
- rollback mechanism:
  - switch active profile labels back to previous stable bundle
  - disable sprint-only flags if a change is still behind a feature toggle
  - keep failed compare artifacts for postmortem instead of reverting blindly
- hard rollback triggers:
  - grounding regression on target slices
  - no-answer precision collapse
  - telemetry completeness failure
  - TTFT regression beyond budget
  - structured deterministic route regressions on article/date/number fixtures
