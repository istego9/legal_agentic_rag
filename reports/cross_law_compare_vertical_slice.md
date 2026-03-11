# Cross-Law Compare Vertical Slice Report

## Scope Implemented
Implemented an end-to-end `cross_law_compare` vertical slice in the `/v1/qa/ask` runtime pipeline with deterministic-first behavior, page-grounded evidence, no-silent-fallback guards, and strict-contract-compatible outputs.

## Representative Questions Covered
- Was `DIFC Law No. 1 of 2018` enacted earlier than `DIFC Law No. 2 of 2020`?
- Did two laws come into force on the same date (including notice-mediated commencement evidence)?
- Do two laws have the same administering authority?
- Do both laws contain a schedule?
- Compare full titles across two laws.
- Compare definition/scope wording across two laws.
- Unresolved compare structure (`"Compare these laws."`) clean abstain.
- Resolved compare with missing evidence clean abstain.

## Compare Dimensions Covered
Deterministic compare-intent detection and solver support for:
- enactment date
- commencement / came-into-force date
- administering authority
- title / full title
- definition / scope wording
- penalties / sanctions
- schedule presence
- feature / term / rule presence across instruments
- condition satisfaction (`which law(s) satisfy ...`)

## Runtime Changes
- Added `services/runtime/cross_law_compare_lookup.py`:
  - compare-intent resolution (`resolver_version`, instrument IDs/types, dimensions, operator, temporal focus, confidence, structural requirements)
  - retrieval hints builder (doc-type priority, expansions, notice/lineage flags, anchors)
  - candidate-to-instrument annotation
  - deterministic cross-law solver with typed-first outputs and abstain paths
  - reuse of history/article resolvers (`resolve_law_history_lookup_intent`, `solve_law_history_deterministic`, `resolve_law_article_lookup_intent`)
- Updated `apps/api/src/legal_rag_api/routers/qa.py`:
  - cross-law resolution guard and explicit skip reason `cross_law_compare_resolution_missing`
  - route-aware multi-pass compare retrieval (`cross_law_compare_matrix_v1`) with per-instrument passes, notice expansion, lineage expansion, and instrument-coverage trace
  - deterministic-only cross-law solver path (`solve_cross_law_compare_deterministic`)
  - LLM fallback blocked for cross-law slice
  - additive debug/evidence/telemetry trace fields for cross-law
  - no-silent-fallback map extended with cross-law flags/reasons
- Updated `services/runtime/solvers.py`:
  - compare-aware used-source selection for `cross_law_compare` to preserve instrument coverage
  - evidence selection trace extended with compare coverage fields

## Traces Added
- `cross_law_compare_resolution`
- `cross_law_compare_retrieval_hints`
- `cross_law_compare_dimension_trace`
- compare retrieval strategy/profile/pass trace
- compare instrument coverage trace (candidate and used)
- candidate/used page traces remain page-level source IDs only
- no-silent-fallback cross-law flags/reasons

## Tests Added
- Contracts: `tests/contracts/test_cross_law_compare_vertical_slice_contracts.py`
- Integration: `tests/integration/test_cross_law_compare_slice.py`
- Scorer regression: `tests/scorer_regression/test_cross_law_compare_strict_slice.py`

## Validation Status
- `.venv/bin/python -m pytest tests/contracts tests/integration tests/scorer_regression -q` -> **pass**
- `.venv/bin/python scripts/agentfirst.py verify --strict` -> **pass**
- Docker rebuild and endpoint checks:
  - `cd infra/docker && docker compose up --build -d` -> **pass**
  - `http://127.0.0.1:18000/docs` -> **200**
  - `http://127.0.0.1:15188/` -> **200**
  - `http://127.0.0.1:18080/` -> **200**
  - `http://127.0.0.1:18080/docs` -> **200**

## Scorer / Contract Notes
- Query response contract remains unchanged.
- Source semantics remain strict page-level (`source_page_id=pdf_id_page`).
- Abstain behavior and telemetry completeness validated via scorer regression and strict preflight checks.

## Remaining Gaps Before Contest-Ready Compare Route
- Improve anchor resolution for title-only references and highly abbreviated instrument mentions.
- Tighten disambiguation where multiple similarly named instruments exist without numbers/years.
- Add more adversarial fixtures for mixed amendment/commencement compare phrasing in larger corpora.
- Expand deterministic extraction robustness for long-form penalties/definition wording conflicts across dense multi-page evidence.
