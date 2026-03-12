# Problem Report: Corpus Version and Lineage Metadata

## Executive Summary

The full-corpus `prepare` pipeline is reproducible and parser-stable, but the
current version/lineage metadata is not reliable enough for internal gold,
grounded runtime reasoning, or external validation. The failure mode is not a
single parser crash. It is a compound metadata problem:

1. weak regex extraction for `law_number` and `case_id`,
2. legislative temporal heuristics applied to case documents,
3. version grouping built directly from those noisy fields,
4. storage/reporting that hides part of the lineage signal needed for audit.

This is why the corpus can look healthy at the `prepare_report.json` level while
still producing false version families such as `law:difc` and `case:no`.

## What Was Verified

- Full bundle `prepare` completed twice with matching identity and artifact fingerprints.
- `source_page_id` mapping is stable and canonical.
- No parser crash loop was observed.
- No exact duplicate group was observed for this bundle.
- OCR was not used.

These facts are recorded in `evidence_summary.json`.

## Observed Failure Modes

### 1. `law_number` extraction is structurally unsafe

Current logic:

- file: `services/ingest/ingest.py`
- function: `_extract_law_number()`

The regex captures the first token after `law|act|code`, not the instrument
number. For strings such as:

- `FOUNDATIONS LAW DIFC LAW NO.3 OF 2018`
- `EMPLOYMENT LAW DIFC LAW NO. 2 of 2019`

the extractor returns `DIFC` instead of the real law number. That creates a
single fake family anchor `law:difc` across unrelated laws.

Evidence:

- `regex_reproduction.json`
- `problematic_version_groups.json`
- `document_samples.json`

### 2. `case_id` extraction fails on `Case No:`

Current logic:

- file: `services/ingest/ingest.py`
- function: `_extract_case_id()`

The regex does not handle `Case No:` and instead captures `No`. This creates
fake case families such as `case:no`.

Evidence:

- `regex_reproduction.json`
- `document_samples.json`

### 3. Legislative temporal heuristics are being applied to case documents

Current logic:

- file: `services/ingest/ingest.py`
- functions: `_extract_effective_start_date()`, `_extract_effective_end_date()`,
  `_is_current_from_end_date()`

The code interprets strings like `until 2022`, `superseded`, `expired`, and
other legislative cues as if they describe the lifecycle of the whole document.
That is acceptable for laws and notices only when tightly scoped. It is wrong
for cases.

Observed false positives:

- a case document got `effective_end_date=2022-01-01` from narrative text about
  a shareholder relationship that lasted until 2022;
- another case document got `effective_end_date=2025-01-01` because the text
  discussed a law that had been superseded in 2025.

Evidence:

- `temporal_false_positive_samples.json`
- `document_samples.json`

### 4. Version grouping is built too early and too directly

Current logic:

- file: `services/ingest/ingest.py`
- functions: `_resolve_version_group_id()`, `_apply_family_versioning()`

The pipeline assigns `version_group_id` directly from `law_number` or `case_id`
before those fields are normalized or validated. It then sorts families into a
linear sequence. That is too optimistic for this corpus.

Observed multi-document groups:

- `law:difc`
- `case:cfi-`
- `case:management`
- `case:no`

Only some of these may correspond to real related documents. The current system
cannot distinguish:

- separate laws from the same jurisdiction,
- judgment vs order vs reasons in the same case,
- real supersession vs incidental references inside text.

Evidence:

- `problematic_version_groups.json`

### 5. Canonical PG and compact diagnostics do not expose enough lineage fields

The contract expects fields such as:

- `effective_start_date`
- `effective_end_date`
- `is_current_version`
- `version_group_id`
- `version_sequence`
- `ocr_used`
- `extraction_confidence`

Today:

- `corpus_documents` stores only a smaller subset at top level;
- some metadata exists only transiently during deterministic ingest;
- `compact_ingest_diagnostics()` removes the fields needed for external audit.

Result:

- PG-backed inspection cannot truthfully answer lineage questions without
  rerunning deterministic ingest;
- `prepare_report.json` is too compact for external investigation.

Evidence:

- `storage_contract_gap.json`
- `evidence_summary.json`

## Why Regex-Only Is Not Enough

Regex is still the right first pass for:

- canonical page ids,
- parser quality heuristics,
- candidate doc-type routing,
- candidate references,
- cheap gating before any model call.

Regex is not reliable enough for:

- law family identification,
- current-version selection,
- case family identification,
- document role within a case family,
- distinction between document metadata and in-body legal references.

In this bundle, the key evidence is already decisive:

- `law_number="DIFC"` is not a recoverable version anchor;
- `case_id="No"` is not a recoverable case anchor;
- `effective_end_date` on case documents is semantically invalid.

## Research Conclusion

The right architecture is a two-stage metadata path:

1. deterministic parser extracts candidates and stable source/page identities;
2. title-page LM normalization resolves normalized metadata and family anchors;
3. family-level resolver decides legislative version lineage or case relation
   edges from candidate groups.

This stays compatible with the current ingest architecture, keeps runtime
deterministic, and moves expensive reasoning into offline `prepare`.
