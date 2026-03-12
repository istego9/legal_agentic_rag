# Deterministic Fixes Evaluation

## Scope

This note compares the original full-corpus investigation baseline against the
deterministic ingest fixes that were implemented before reprocessing the full
`documents.zip`.

## Implemented Fixes

- tightened `law_number` extraction so generic jurisdiction tokens and generic
  `No.` markers do not become legislative ids
- tightened `case_id` extraction so `Case No:` and `Claim No.` produce strong
  case identifiers instead of `No`
- restricted legislative temporal heuristics to legislative document types
- disabled legislative-style family sequencing for case documents
- added a legislative title anchor to `version_group_id` so different laws with
  the same number no longer collapse into one family

## Before

- multi-document version groups: 4
- groups:
  - `case:cfi-`
  - `case:management`
  - `case:no`
  - `law:difc`
- case temporal false positives: 3

## After

- multi-document version groups: 2
- groups:
  - `case:ca_005_2025`
  - `case:dec_001_2025`
- case temporal false positives: 0

## Interpretation

The deterministic patch materially improved quality.

- clearly false anchors were removed:
  - `law:difc`
  - `case:no`
  - `case:cfi-`
- false case lifecycle inference was eliminated
- remaining multi-document groups now look like legitimate same-case document
  families rather than regex accidents

## Remaining Gaps

- some case documents still lack strong extracted identifiers and fall back to
  `pdf_id`
- case relations are still only family buckets; they are not yet explicit
  `order_for` / `reasons_for` / `appeal_in` edges
- title-page LM normalization is still needed to replace the remaining
  deterministic ambiguity with explicit structured metadata
