# Court Registry Enrichment

## Goal

Build a repo-controlled DIFC court registry from:

- observed headings in the current corpus
- official DIFC Courts web sources

and then apply that registry to case metadata normalization.

## Saved Registry

- registry file: `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/court_registry_v1.json`
- normalizer: `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/court_registry.py`

## Observed Corpus Labels

- `COURT OF APPEAL`
- `COURT OF FIRST INSTANCE`
- `SMALL CLAIMS TRIBUNAL`
- `DIGITAL ECONOMY COURT`
- `TECHNOLOGY AND CONSTRUCTION DIVISION`
- `SCT - JUDGMENTS AND ORDERS`
- `ENFORCEMENT ORDERS`

## Derived Structure

- court system:
  - `Dubai International Financial Centre Courts`
- core courts:
  - `Court of Appeal`
  - `Court of First Instance`
  - `Small Claims Tribunal`
- specialised divisions:
  - `Digital Economy Court Division`
  - `Technology & Construction Division`
- document streams:
  - `Orders`
  - `Judgments`
  - `Judgments and Orders`
  - `Order with Reasons`
  - `Enforcement Orders`

## External Sources Used

- DIFC court structure:
  - <https://www.difccourts.ae/about/court-structure>
- DIFC jurisdiction:
  - <https://www.difccourts.ae/about/jurisdiction>
- Technology & Construction Division:
  - <https://www.difccourts.ae/difc-courts/services/specialised-divisions/technology-and-construction-division>
- Digital Economy Court coverage:
  - <https://www.difccourts.ae/media-centre/newsroom/difc-courts-manages-increased-caseload-alongside-newly-engineered-services-future-digital-economy>
  - <https://www.difccourts.ae/media-centre/newsroom/dubais-difc-courts-shares-insights-case-activity>

## Normalization Policy

- The registry is authoritative for canonical aliases and hierarchy.
- The LLM still extracts title-page metadata.
- The court registry then normalizes:
  - `court_name`
  - `court_level`
  - division metadata
  - document stream metadata
- Registry normalization is post-extraction normalization, not hidden title fallback.

## Current Output Convention

- `court_name` becomes the specific normalized body where available
  - example: `Court of Appeal`
  - example: `Digital Economy Court Division`
- `court_level` becomes the broader adjudicative level
  - example: `Court of Appeal`
  - example: `Court of First Instance`
- processing stores richer structure in:
  - `processing.metadata_normalization.court_normalization`

## Current Result

After applying the registry on the cached full GPT-5-mini corpus pass:

- `case_null_court_count = 0`
- `rules_only_count = 0`
- `placeholder_title_count = 0`
- `law_amendment_gap_count = 0`
- `verbose_title_count = 1`

See:

- `/Users/artemgendler/dev/legal_agentic_rag/reports/corpus_investigation/2026-03-12-version-lineage-rca/full_gpt5mini_quality_report_v2_courts.md`
