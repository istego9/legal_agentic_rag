# Law Relation / History Vertical Slice Report (Step 5)

## Scope Delivered
- Route family hardened: `law_relation_or_history` (raw runtime route remains `history_lineage`).
- End-to-end deterministic path implemented for history/lineage QA.
- No contract/schema breaking changes in `QueryRequest`, `QueryResponse`, `PageRef`, telemetry schema, or submission export.

## Representative Question Types Covered
- Amendment lineage: `amended_by`, `amends`
- Repeal/supersession lineage: `repealed_by`, `repeals`, `superseded_by`, `supersedes`
- Temporal events: `enacted_on`, `commenced_on`, `effective_from`
- Version semantics: `current_version`, `previous_version`
- Notice-mediated commencement: `notice_mediated_commencement` (including partial commencement phrasing)
- DIFC legal context distinction:
  - default application / governing law: `default_difc_application`
  - DIFC Courts opt-in jurisdiction: `jurisdiction_opt_in`

## Runtime/Route Changes
- Added `services/runtime/law_history_lookup.py`:
  - deterministic history intent resolution
  - legal-context flags
  - retrieval hint generation
  - deterministic typed-first history solver + corpus-only source-of-law guardrail
- Integrated history slice in `apps/api/src/legal_rag_api/routers/qa.py`:
  - `law_history_slice_active` for taxonomy route `law_relation_or_history`
  - history resolution guard with explicit abstain + no-silent-fallback (`law_history_resolution_missing`)
  - explicit history retrieval profile selection (`history_lineage_graph_v1`)
  - route-aware history retrieval passes by doc type and relation-aware expansion
  - deterministic history solver invocation
  - LLM free-text fallback blocked for history slice
  - page-grounded sources only in final output
- Minimal router disambiguation fix in `packages/router/heuristics.py`:
  - enactment cues improved
  - narrow strong-history override to prevent edge history questions from being swallowed by article lookup

## Traces / Telemetry Added
- `law_history_lookup_resolution`
- `legal_context_flags`:
  - `is_difc_context`
  - `is_jurisdiction_question`
  - `is_governing_law_question`
  - `is_notice_mediated`
  - `is_current_vs_historical_question`
- History retrieval trace fields:
  - retrieval strategy/profile selection
  - pass-level candidate traces
  - fallback tracing
- Existing scorer-facing telemetry shadow preserved and populated.

## DIFC/UAE Assumptions Encoded
- Corpus-first grounding only (DIFC laws/regulations/amendment laws/notices and surfaced linked instruments).
- No external English-law doctrine synthesis.
- Jurisdiction vs governing-law/application treated as separate intents.
- Enactment/commencement notices treated as first-class evidence sources.
- Deterministic abstain behavior for structurally unresolved history questions.

## Tests Added/Updated
### Contracts
- `tests/contracts/test_law_history_vertical_slice_contracts.py`
  - intent parsing/normalization
  - jurisdiction vs governing-law distinction
  - notice-mediated commencement classification
  - typed normalization behavior
  - page-level source formatting
  - no-silent-fallback behavior
- `tests/contracts/test_runtime_route_law_family_disambiguation.py`
  - added narrow history disambiguation regressions for enactment/supersession cues

### Integration
- `tests/integration/test_law_history_lookup_slice.py`
  - amendment/amended-by
  - enactment date
  - commencement/came into force
  - current vs previous version
  - notice-mediated partial commencement signal
  - DIFC default-application vs jurisdiction distinction
- Updated `tests/integration/test_api_e2e.py` typed solver expectations for history slice.

### Scorer Regression
- `tests/scorer_regression/test_law_history_lookup_strict_slice.py`
  - strict contract pass
  - canonical page source IDs
  - telemetry completeness
  - valid abstain/no-answer behavior with empty used sources

## Validation Status
- `pytest tests/contracts tests/integration tests/scorer_regression -q`: **passed** (`152 passed`)
- `python scripts/agentfirst.py verify --strict`: **passed**
- Docker rebuild + endpoint checks:
  - `infra/docker`: `docker compose up --build -d` completed
  - `http://127.0.0.1:18000/docs`: `200`
  - `http://127.0.0.1:15188/`: `200`
  - `http://127.0.0.1:18080/`: `200`
  - `http://127.0.0.1:18080/docs`: `200`

## Remaining Gaps Before Contest-Ready History Route
- Law/notice mention extraction heuristics still rely on regex and can over-capture noisy title spans; targeted normalization is improved but not fully ontology-backed.
- Relation-edge exploitation is currently projection/filter driven; deeper graph traversal via persisted relation edges can be expanded for harder lineage chains.
- Additional corpus fixtures for staged/partial commencement edge cases would further harden deterministic tie-breaking under dense evidence.
