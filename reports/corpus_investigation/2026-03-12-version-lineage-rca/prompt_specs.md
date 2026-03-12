# Prompt Specs for Corpus Metadata Hardening

## Goal

Replace fragile regex-only lineage/version inference with a cheap offline
metadata normalization pass that uses only title pages or, when needed, the
first two pages.

## Global Rules

- Run offline during `prepare`, never in runtime QA.
- Use deterministic settings:
  - `temperature=0`
  - schema-constrained JSON output
  - cache key = `content_hash + prompt_version + model_version + page_window`
- Default input is parser text from page 1.
- Escalate to page 2 only when page 1 is missing required anchors.
- Use image/OCR fallback only when title-page parser quality is below the gate.

## Stage Layout

### Stage A. Deterministic Candidate Extraction

Keep regex/rules for:

- `doc_type_candidate`
- `page ids`
- `article refs`
- `law refs`
- `case refs`
- candidate dates
- parser quality

Do not treat this stage as source of truth for:

- `law_number`
- `case_id`
- `version_group_id`
- `is_current_version`

### Stage B. Title-Page Metadata Normalization

LM extracts normalized metadata from title pages.

### Stage C. Family Resolver

LM resolves relationships only inside candidate groups.

- laws/regulations/notices:
  - family id
  - edition ordering
  - current version marker
  - supersedes edges only when explicit
- cases:
  - same-case family
  - document role
  - relation edges such as `order_for`, `reasons_for`, `appeal_in`
  - no legislative-style `current_version`

## Document-Type Matrix

### 1. Laws

Input:

- page 1 parser text
- page 2 parser text only if page 1 is ambiguous
- optional title-page image/OCR if title-page quality is below threshold

Extract with:

- prompt `legislative_title_metadata_v1`

Fields:

- `instrument_kind`
- `official_title`
- `short_title`
- `law_number`
- `law_year`
- `consolidated_version_number`
- `consolidated_version_date`
- `amendment_notice_refs`
- `issued_date`
- `effective_start_date`
- `effective_end_date`
- `jurisdiction`
- `family_anchor_candidate`
- `lineage_confidence`
- `manual_review_required`

Then resolve with:

- prompt `legislative_family_resolution_v1`

Family resolver output:

- `family_id`
- `documents`
- `document_order`
- `current_document_id`
- `relation_edges`
- `family_review_required`

### 2. Regulations

Input:

- same as laws

Extract with:

- prompt `legislative_title_metadata_v1`
- `doc_type_hint="regulation"`

Fields:

- all law fields plus:
- `enabled_by_title`
- `enabled_by_law_number`
- `enabled_by_law_year`
- `issuing_authority`

Then resolve with:

- prompt `legislative_family_resolution_v1`

### 3. Enactment Notices

Input:

- page 1 parser text
- page 2 only if target law is unclear

Extract with:

- prompt `enactment_notice_title_metadata_v1`

Fields:

- `notice_title`
- `notice_number`
- `notice_year`
- `target_law_title`
- `target_law_number`
- `target_law_year`
- `commencement_date`
- `commencement_scope`
- `family_anchor_candidate`
- `manual_review_required`

Then resolve with:

- prompt `notice_target_resolution_v1`

### 4. Cases

Input:

- page 1 parser text
- page 2 if role or citation is ambiguous

Extract with:

- prompt `case_title_metadata_v1`

Fields:

- `case_number`
- `claim_number`
- `neutral_citation`
- `court_name`
- `court_level`
- `decision_date`
- `document_role`
- `party_block`
- `same_case_anchor_candidate`
- `manual_review_required`

Important rule:

- cases do not emit `is_current_version`
- cases do not emit legislative supersession

Then resolve with:

- prompt `case_relation_resolution_v1`

Family resolver output:

- `case_family_id`
- `documents`
- `relation_edges`
- `primary_merits_document_id`
- `review_required`

### 5. Other / Unknown

Input:

- page 1 parser text

Extract with:

- prompt `document_router_title_metadata_v1`

Fields:

- `doc_type`
- `reason`
- `manual_review_required`

If still unknown:

- no version grouping
- no current-version assignment
- hard manual-review queue

## Contract Mapping and Exact Response Envelopes

This section defines what each prompt is allowed to write into existing
contracts and what must remain inside `processing` until the public contract is
explicitly extended.

### Storage Policy

Prompt outputs are split into:

- existing contract writes
  - fields that map directly into `DocumentBase`, type-specific documents, or
    `RelationEdge`
- processing-only candidate fields
  - fields used for review or resolver logic that do not exist as public
    top-level contract fields today

Processing-only candidate fields include:

- `claim_number`
- `appeal_number`
- `document_role`
- `consolidated_version_number`
- `consolidated_version_date`
- `family_anchor_candidate`
- `same_case_anchor_candidate`
- `manual_review_required`
- `manual_review_reasons`
- title-page extraction confidence notes

### Law Mapping

Existing contract writes:

- `DocumentBase`
  - `doc_type="law"`
  - `title_raw`
  - `title_normalized`
  - `short_title`
  - `citation_title`
  - `language`
  - `jurisdiction`
  - `issued_date`
  - `effective_start_date`
  - `effective_end_date`
  - `is_current_version`
  - `version_group_id`
  - `version_sequence`
  - `supersedes_doc_id`
  - `superseded_by_doc_id`
  - `ocr_used`
  - `extraction_confidence`
- `LawDocument`
  - `law_number`
  - `law_year`
  - `instrument_kind`
  - `administering_authority`
  - `promulgation_date`
  - `commencement_date`
  - `last_consolidated_date`
  - `status`
  - `edition_scope`

Processing-only candidate fields:

- `consolidated_version_number`
- `family_anchor_candidate`
- `manual_review_required`
- `manual_review_reasons`

### Regulation Mapping

Existing contract writes:

- `DocumentBase`
  - `doc_type="regulation"`
  - `title_raw`
  - `title_normalized`
  - `short_title`
  - `citation_title`
  - `language`
  - `jurisdiction`
  - `issued_date`
  - `effective_start_date`
  - `effective_end_date`
  - `is_current_version`
  - `version_group_id`
  - `version_sequence`
  - `supersedes_doc_id`
  - `superseded_by_doc_id`
  - `ocr_used`
  - `extraction_confidence`
- `RegulationDocument`
  - `regulation_number`
  - `regulation_year`
  - `regulation_type`
  - `issuing_authority`
  - `enabled_by_law_title`
  - `status`
  - `is_current_version`

Processing-only candidate fields:

- `enabled_by_law_number`
- `enabled_by_law_year`
- `family_anchor_candidate`
- `manual_review_required`
- `manual_review_reasons`

### Enactment Notice Mapping

Existing contract writes:

- `DocumentBase`
  - `doc_type="enactment_notice"`
  - `title_raw`
  - `title_normalized`
  - `short_title`
  - `citation_title`
  - `language`
  - `jurisdiction`
  - `issued_date`
  - `effective_start_date`
  - `effective_end_date`
  - `version_group_id`
  - `ocr_used`
  - `extraction_confidence`
- `EnactmentNoticeDocument`
  - `notice_number`
  - `notice_year`
  - `notice_type`
  - `issuing_authority`
  - `target_title`
  - `target_law_number`
  - `target_law_year`
  - `commencement_scope_type`
  - `commencement_date`
  - `linked_version_group_id`

Processing-only candidate fields:

- `family_anchor_candidate`
- `manual_review_required`
- `manual_review_reasons`

### Case Mapping

Existing contract writes:

- `DocumentBase`
  - `doc_type="case"`
  - `title_raw`
  - `title_normalized`
  - `short_title`
  - `citation_title`
  - `language`
  - `jurisdiction`
  - `issued_date`
  - `ocr_used`
  - `extraction_confidence`
- `CaseDocument`
  - `case_number`
  - `neutral_citation`
  - `court_name`
  - `court_level`
  - `decision_date`
  - `judgment_date` when explicit and role is judgment
  - `claimant_names`
  - `respondent_names`
  - `appellant_names`
  - `defendant_names`
  - `judge_names`
  - `presiding_judge`
  - `procedural_stage`

Processing-only candidate fields:

- `claim_number`
- `appeal_number`
- `document_role`
- `same_case_anchor_candidate`
- `manual_review_required`
- `manual_review_reasons`

Forbidden writes:

- no `is_current_version`
- no legislative `version_group_id`
- no legislative `supersedes_doc_id`
- no legislative `superseded_by_doc_id`

### Other / Unknown Mapping

Existing contract writes:

- `DocumentBase`
  - `doc_type="other"`
  - `title_raw`
  - `title_normalized`
  - `short_title`
  - `citation_title`
  - `language`
  - `jurisdiction`
  - `issued_date` only if explicit
  - `ocr_used`
  - `extraction_confidence`

Processing-only candidate fields:

- `manual_review_required`
- `manual_review_reasons`

### Exact Outer Envelope

Every title-page prompt should return the same outer envelope:

```json
{
  "canonical_document": {},
  "type_specific_document": {},
  "processing_candidates": {},
  "review": {
    "manual_review_required": true,
    "manual_review_reasons": []
  }
}
```

Validation invariants:

- If `manual_review_required=true`, `manual_review_reasons` must be non-empty.
- If `same_case_anchor_candidate` is present, `manual_review_reasons` must not
  include `missing_case_anchor`.
- `type_specific_document` must not mix case fields with legislative fields.

### Exact Envelope: `legislative_title_metadata_v1`

```json
{
  "canonical_document": {
    "doc_type": "law|regulation|enactment_notice|other",
    "title_raw": "string|null",
    "title_normalized": "string|null",
    "short_title": "string|null",
    "citation_title": "string|null",
    "language": "string|null",
    "jurisdiction": "string|null",
    "issued_date": "YYYY-MM-DD|null",
    "effective_start_date": "YYYY-MM-DD|null",
    "effective_end_date": "YYYY-MM-DD|null",
    "ocr_used": false,
    "extraction_confidence": 0.0
  },
  "type_specific_document": {
    "law_number": "string|null",
    "law_year": "integer|null",
    "instrument_kind": "string|null",
    "administering_authority": "string|null",
    "promulgation_date": "YYYY-MM-DD|null",
    "commencement_date": "YYYY-MM-DD|null",
    "last_consolidated_date": "YYYY-MM-DD|null",
    "regulation_number": "string|null",
    "regulation_year": "integer|null",
    "regulation_type": "string|null",
    "issuing_authority": "string|null"
  },
  "processing_candidates": {
    "consolidated_version_number": "string|null",
    "consolidated_version_date": "YYYY-MM-DD|null",
    "enabled_by_law_number": "string|null",
    "enabled_by_law_year": "integer|null",
    "family_anchor_candidate": "string|null"
  },
  "review": {
    "manual_review_required": true,
    "manual_review_reasons": []
  }
}
```

### Exact Envelope: `enactment_notice_title_metadata_v1`

```json
{
  "canonical_document": {
    "doc_type": "enactment_notice",
    "title_raw": "string|null",
    "title_normalized": "string|null",
    "short_title": "string|null",
    "citation_title": "string|null",
    "language": "string|null",
    "jurisdiction": "string|null",
    "issued_date": "YYYY-MM-DD|null",
    "effective_start_date": "YYYY-MM-DD|null",
    "effective_end_date": "YYYY-MM-DD|null",
    "ocr_used": false,
    "extraction_confidence": 0.0
  },
  "type_specific_document": {
    "notice_number": "string|null",
    "notice_year": "integer|null",
    "notice_type": "string|null",
    "issuing_authority": "string|null",
    "target_title": "string|null",
    "target_law_number": "string|null",
    "target_law_year": "integer|null",
    "commencement_scope_type": "full|partial|unknown|null",
    "commencement_date": "YYYY-MM-DD|null"
  },
  "processing_candidates": {
    "family_anchor_candidate": "string|null"
  },
  "review": {
    "manual_review_required": true,
    "manual_review_reasons": []
  }
}
```

### Exact Envelope: `case_title_metadata_v1`

```json
{
  "canonical_document": {
    "doc_type": "case",
    "title_raw": "string|null",
    "title_normalized": "string|null",
    "short_title": "string|null",
    "citation_title": "string|null",
    "language": "string|null",
    "jurisdiction": "string|null",
    "issued_date": "YYYY-MM-DD|null",
    "ocr_used": false,
    "extraction_confidence": 0.0
  },
  "type_specific_document": {
    "case_number": "string|null",
    "neutral_citation": "string|null",
    "court_name": "string|null",
    "court_level": "string|null",
    "decision_date": "YYYY-MM-DD|null",
    "judgment_date": "YYYY-MM-DD|null",
    "claimant_names": [],
    "respondent_names": [],
    "appellant_names": [],
    "defendant_names": [],
    "judge_names": [],
    "presiding_judge": "string|null",
    "procedural_stage": "string|null"
  },
  "processing_candidates": {
    "claim_number": "string|null",
    "appeal_number": "string|null",
    "document_role": "judgment|order|reasons|permission|appeal|other|null",
    "same_case_anchor_candidate": "string|null"
  },
  "review": {
    "manual_review_required": true,
    "manual_review_reasons": []
  }
}
```

### Exact Envelope: `document_router_title_metadata_v1`

```json
{
  "canonical_document": {
    "doc_type": "law|regulation|enactment_notice|case|other",
    "title_raw": "string|null",
    "title_normalized": "string|null",
    "short_title": "string|null",
    "citation_title": "string|null",
    "language": "string|null",
    "jurisdiction": "string|null",
    "issued_date": "YYYY-MM-DD|null",
    "ocr_used": false,
    "extraction_confidence": 0.0
  },
  "type_specific_document": {},
  "processing_candidates": {
    "router_reason": "string|null"
  },
  "review": {
    "manual_review_required": true,
    "manual_review_reasons": []
  }
}
```

### Family Resolver Write Policy

`legislative_family_resolution_v1` writes:

- `DocumentBase.version_group_id`
- `DocumentBase.version_sequence`
- `DocumentBase.is_current_version`
- `DocumentBase.supersedes_doc_id`
- `DocumentBase.superseded_by_doc_id`
- `RelationEdge[*]`

`case_relation_resolution_v1` writes:

- `RelationEdge[*]`
- `CaseDocument.procedural_stage` when resolver confirms it

Processing-only outputs from family resolvers:

- `family_resolution_confidence`
- `family_review_required`
- `family_review_reasons`
- `case_family_id`
- `primary_merits_document_id`
- `document_role_confirmed`

## Prompt Drafts

### Prompt: `legislative_title_metadata_v1`

System:

```text
You normalize legal document metadata from the title page of a statute,
regulation, or similar legislative instrument. Extract only what is explicitly
supported by the provided text. Do not infer missing numbers, dates, or family
relationships. Return valid JSON only.
```

User:

```text
Task:
Normalize metadata for one legislative document.

Input:
- doc_type_hint: {law|regulation|unknown}
- source_pdf_id: {pdf_id}
- page_1_text: {page_1_text}
- page_2_text: {page_2_text_or_empty}

Output JSON schema:
{
  "doc_type": "law|regulation|enactment_notice|other",
  "official_title": "string|null",
  "short_title": "string|null",
  "law_number": "string|null",
  "law_year": "integer|null",
  "consolidated_version_number": "string|null",
  "consolidated_version_date": "YYYY-MM-DD|null",
  "issued_date": "YYYY-MM-DD|null",
  "effective_start_date": "YYYY-MM-DD|null",
  "effective_end_date": "YYYY-MM-DD|null",
  "jurisdiction": "string|null",
  "issuing_authority": "string|null",
  "family_anchor_candidate": "string|null",
  "manual_review_required": true,
  "manual_review_reasons": ["string"]
}

Rules:
- Use only explicit title-page evidence.
- If you see multiple law references, distinguish the document's own identity from amendment references.
- If the title page does not provide enough evidence, set manual_review_required=true.
- Do not mark current version here.
```

### Prompt: `enactment_notice_title_metadata_v1`

System:

```text
You normalize commencement or enactment notice metadata from title-page text.
Extract only explicit information. Return valid JSON only.
```

User:

```text
Task:
Normalize metadata for one enactment notice.

Input:
- source_pdf_id: {pdf_id}
- page_1_text: {page_1_text}
- page_2_text: {page_2_text_or_empty}

Output JSON schema:
{
  "doc_type": "enactment_notice",
  "notice_title": "string|null",
  "notice_number": "string|null",
  "notice_year": "integer|null",
  "target_law_title": "string|null",
  "target_law_number": "string|null",
  "target_law_year": "integer|null",
  "commencement_date": "YYYY-MM-DD|null",
  "commencement_scope": "full|partial|unknown",
  "family_anchor_candidate": "string|null",
  "manual_review_required": true,
  "manual_review_reasons": ["string"]
}
```

### Prompt: `case_title_metadata_v1`

System:

```text
You normalize case-document metadata from the first page of a court document.
Extract only explicit information. Distinguish the case identity from the role
of this specific document, such as judgment, order, reasons, permission ruling,
or appeal decision. Return valid JSON only.
```

User:

```text
Task:
Normalize metadata for one case document.

Input:
- source_pdf_id: {pdf_id}
- page_1_text: {page_1_text}
- page_2_text: {page_2_text_or_empty}

Output JSON schema:
{
  "doc_type": "case",
  "case_number": "string|null",
  "claim_number": "string|null",
  "neutral_citation": "string|null",
  "court_name": "string|null",
  "court_level": "string|null",
  "decision_date": "YYYY-MM-DD|null",
  "document_role": "judgment|order|reasons|permission|appeal|other",
  "party_block": ["string"],
  "same_case_anchor_candidate": "string|null",
  "manual_review_required": true,
  "manual_review_reasons": ["string"]
}

Rules:
- Never output legislative current-version semantics.
- Never treat references to other laws or other cases as the identity of this document.
- If the page contains both claim number and appeal number, preserve both.
- If `case_number` or `claim_number` is present, populate
  `same_case_anchor_candidate`.
- Do not classify court orders, judgments, reasons decisions, or appeal rulings
  as regulations.
```

### Prompt: `legislative_family_resolution_v1`

System:

```text
You resolve version lineage inside a candidate family of legislative documents.
Use only explicit evidence from titles, version labels, issue dates, and
commencement statements. Return valid JSON only.
```

User:

```text
Task:
Resolve whether these documents belong to the same legislative family and, if
so, which document is the latest usable version.

Input:
- family_candidate_key: {candidate_key}
- documents: [{normalized_title_page_payloads}]

Output JSON schema:
{
  "family_id": "string|null",
  "documents_same_family": true,
  "current_document_id": "string|null",
  "ordered_document_ids": ["string"],
  "relation_edges": [
    {
      "from_document_id": "string",
      "to_document_id": "string",
      "edge_type": "supersedes|amends|consolidates|related"
    }
  ],
  "review_required": true,
  "review_reasons": ["string"]
}

Rules:
- If the family is ambiguous, set review_required=true and do not force a linear order.
- A shared jurisdiction token such as DIFC is not enough to place documents in one family.
```

### Prompt: `case_relation_resolution_v1`

System:

```text
You resolve relationships between court documents from the same or similar case
family. Return valid JSON only.
```

User:

```text
Task:
Determine whether the supplied case documents belong to the same dispute and how
they relate.

Input:
- candidate_case_anchor: {candidate_anchor}
- documents: [{normalized_case_title_payloads}]

Output JSON schema:
{
  "case_family_id": "string|null",
  "documents_same_case": true,
  "primary_merits_document_id": "string|null",
  "relation_edges": [
    {
      "from_document_id": "string",
      "to_document_id": "string",
      "edge_type": "order_for|reasons_for|appeal_in|permission_for|related"
    }
  ],
  "review_required": true,
  "review_reasons": ["string"]
}

Rules:
- Never output a legislative-style current version.
- If the documents may be different disputes, set review_required=true.
```
