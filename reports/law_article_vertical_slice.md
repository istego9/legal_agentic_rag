# Law Article Lookup Vertical Slice (Step 4)

Date: 2026-03-11  
Scope: `law_article_lookup` only (route family `article_lookup` with normalized taxonomy `law_article_lookup`)

## Action Checklist
- [x] Deterministic route decision trace exposed.
- [x] Law/article lookup intent extraction + resolution stage added.
- [x] Route-aware retrieval profile enforced (`article_lookup_recall_v2`).
- [x] Candidate pages + used pages traced and page-grounded.
- [x] Deterministic answer extraction remains first path.
- [x] Answer normalization trace added.
- [x] No-silent-fallback guard for unresolved law/article lookup added.
- [x] Page-level source semantics preserved for response/export.
- [x] Telemetry shadow + route/evidence traces included in debug/review artifacts.
- [x] Contract/integration/scorer regression tests added for this slice.

## Implemented Vertical Slice
1. Route decision
- `qa._answer_query` now uses `resolve_route_decision(...)` and emits `route_decision` trace payload.

2. Law/article extraction + resolution
- Added `services/runtime/law_article_lookup.py`.
- New resolver output includes:
  - `law_identifier`
  - `article_identifier`
  - `subarticle_identifier` (optional)
  - `provision_lookup_confidence`
  - `resolved_doc_type_guess`
  - supporting structured fields (`law_number`, `law_year`, section/clause/paragraph refs, etc.).

3. Retrieval planning and explicit profile usage
- `article_lookup` continues to use `article_lookup_recall_v2`.
- Retrieval traces now include:
  - `retrieval_backend`
  - `lookup_intent`
  - structural hit counters
  - top candidates and reasons.

4. No-silent-fallback behavior
- For `law_article_lookup`, unresolved lookup intent blocks retrieval with explicit trace:
  - `retrieval_skipped_reason=law_article_resolution_missing`
  - `retrieval_fallback_traced=true`
  - `no_silent_fallback` debug/evidence flags.
- Generic lexical fallback is blocked when structural law/article lookup is required but unresolved.

5. Deterministic extraction and normalization
- Free-text deterministic behavior changed from question-fragment fallback to evidence extraction (`free_text_evidence_extract`).
- Numeric extraction hardened to avoid provision-number pollution (`Article 10(...)` no longer conflicts with actual numeric answers).
- Added `answer_normalization_trace_v1` with raw vs normalized output for scorer/debug forensics.

6. Page-grounded evidence and sources
- Candidate/used selection remains internal chunk-aware but final response/source contract remains page-level (`source_page_id=pdf_id_page`).

## Representative Questions Covered
- Boolean: Article yes/no lookup.
- Number: Article numeric lookup (months/days style).
- Date: Article date lookup.
- Name: Article entity lookup.
- Short free_text: Article provision text extraction.
- Tricky form: `Law No. X of YYYY` + `Article N(M)` parsing and resolution.

## Tests Added
- `tests/contracts/test_law_article_vertical_slice_contracts.py`
  - resolver parsing and normalization
  - answer normalization contract behavior
  - page-level source formatting
  - no-silent-fallback contract behavior
- `tests/integration/test_law_article_lookup_slice.py`
  - end-to-end route/retrieval/evidence/normalization for representative law article questions
  - tricky law number/year/article case
- `tests/scorer_regression/test_law_article_lookup_strict_slice.py`
  - strict scorer contract pass
  - canonical page source IDs
  - telemetry + schema validity

## Validation Runs
- `.venv/bin/python -m pytest tests/contracts tests/integration tests/scorer_regression -q`  
  Result: `138 passed`
- `.venv/bin/python scripts/agentfirst.py verify --strict`  
  Result: `verify passed`
- Runtime DoD rebuild and endpoint checks:
  - `cd infra/docker && docker compose up --build -d`
  - `http://127.0.0.1:18000/docs` -> `200`
  - `http://127.0.0.1:15188/` -> `200`
  - `http://127.0.0.1:18080/` -> `200`
  - `http://127.0.0.1:18080/docs` -> `200`

## Contract-Risk Summary (legal-rag-contract-guardian)
- Change type: additive (non-breaking contract surface).
- Shared API contracts (`QueryResponse`, `PageRef`, `Telemetry`) unchanged.
- Page-level source semantics preserved.
- Telemetry remains complete/serializable.
- Review artifacts expanded with additive evidence/debug fields.
- Blocking contract issues: none found.

## Remaining Gaps Before Contest-Ready Article Lookup
- Resolver currently focuses on English phrasing; multilingual/edge punctuation normalization can be extended.
- Law title resolution is deterministic but still heuristic; can be improved with canonical title aliases from corpus metadata.
- Additional adversarial fixtures (ambiguous multi-law same-article references) can further harden abstain correctness.
