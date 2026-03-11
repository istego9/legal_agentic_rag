# Validation / Gold Review Console — Technical Specification v1

## 1. Purpose
Build a review screen that helps the team validate answer quality, evidence quality, and disagreement patterns before locking internal gold rows or shipping competition submissions.

The screen is not only a QA viewer. It is a candidate-bundle adjudication console.

It must support three realities:
1. Before corpus prepare is finished — show run / ingest readiness and block gold-lock actions.
2. After corpus prepare but before internal gold exists — show candidate answers and disagreement analysis.
3. After internal gold exists — support adjudication, lock/unlock, and report exports.

## 2. Main user goals
1. Scan all questions quickly.
2. See which questions are safe vs risky.
3. Compare:
   - current system answer
   - strong model answer
   - challenger answer
   - mini-check answer (small model on selected evidence only)
4. Verify evidence on the PDF page immediately.
5. Read the trace only when needed.
6. Lock a gold decision only when disagreement is resolved.
7. Export a full machine-readable report for offline analysis.

## 3. Core UX principle
The console must optimize for triage speed.

The user should be able to answer, within a few seconds:
- do the candidate answers agree?
- do they cite the same evidence?
- does the evidence actually support the answer?
- is this row safe to auto-lock, or does it need review?

## 4. Screen layout

### 4.1 Left pane — Question list / triage rail
A scrollable list of questions with compact signal badges.

Each row must show:
- question id
- truncated question text
- answer type
- primary route
- status badge
- disagreement badge
- evidence badge
- telemetry/contract badge
- current decision badge

Recommended badges:
- `agree`
- `answer_conflict`
- `sources_conflict`
- `answerability_conflict`
- `mini_check_fail`
- `missing_sources`
- `telemetry_bad`
- `needs_review`
- `auto_lock_candidate`
- `gold_locked`

Mandatory filters:
- route
- answer type
- status
- disagreement only
- needs review only
- gold locked only
- no-answer only
- missing sources only
- contract failures only

Search must support:
- question id
- free text over question
- law title / case id / document id

### 4.2 Center pane — Review workspace
Top-to-bottom stack:

#### A. Question block
- full question
- answer type
- route
- document scope
- risk tier
- current run id / dataset id / model set id

#### B. Candidate answer comparison block
Four answer cards side-by-side or stacked responsively:
1. `System`
2. `Strong model`
3. `Challenger`
4. `Mini-check`

Each card must show:
- answer text/value
- answerability label (`answerable` / `abstain`)
- confidence
- source summary (`doc x / pages y,z`)
- short reasoning/evidence summary
- timestamp / run label
- button: `use as baseline`

Disagreement visualization:
- red border if answer differs from majority
- amber border if answer matches but sources differ materially
- purple border if answerability differs
- green border if card agrees with accepted gold

#### C. Evidence block
Below candidate cards, show selected evidence records:
- document id
- document title (if available)
- page number(s)
- extracted paragraph/snippet
- source origin (`system`, `strong`, `challenger`, `mini-check`)
- used/not-used marker
- button: `send to mini-check`
- button: `pin to PDF`

#### D. Decision block
Controls:
- accepted answer field
- accepted sources field
- risk tier
- adjudication note
- reviewer confidence
- buttons:
  - `accept system`
  - `accept strong`
  - `accept challenger`
  - `accept mini-check`
  - `custom answer`
  - `mark needs review`
  - `lock gold`
  - `unlock gold`

### 4.3 Right pane — PDF preview
Large PDF page preview with page navigation.

Must support:
- selected document/page
- highlight selected paragraphs/snippets
- switch between candidate evidence sets
- next/prev page
- zoom
- open document in separate tab/window if needed

If PDF preview is unavailable, show structured fallback:
- doc id
- page number
- extracted text block
- parse warnings

### 4.4 Bottom pane — Trace / full report
Tabbed area:
- `trace`
- `retrieval`
- `evidence`
- `normalization`
- `telemetry`
- `scorer`
- `adjudication`
- `raw json`

This pane is collapsed by default but can be expanded.

## 5. Review states

### 5.1 Question state machine
Each question row must have one of:
- `not_ready`
- `auto_lock_candidate`
- `needs_review`
- `review_in_progress`
- `gold_locked`
- `gold_rejected`
- `exported`

### 5.2 Disagreement classification
Required derived signals:
- `answer_conflict`
- `sources_conflict`
- `answerability_conflict`
- `mini_check_conflict`
- `contract_failure_present`
- `trace_incomplete`
- `pdf_support_not_verified`

### 5.3 Auto-lock rule
Row may be auto-lock candidate only if all are true:
- system / strong / challenger answers agree
- answerability agrees
- at least one overlapping evidence page exists
- no contract failure
- no telemetry failure
- no history/version ambiguity flag

## 6. Mini-check model workflow
Purpose: take selected evidence snippets + question + candidate answer and check whether the answer is supported.

The mini-check model is not a gold oracle.
It is a local contradiction detector.

### Inputs
- question
- expected answer type
- candidate answer
- selected snippets
- selected document ids / page numbers

### Outputs
- `supported` / `not_supported` / `insufficient_evidence`
- extracted answer candidate (optional)
- contradiction reason
- confidence
- short rationale

### UI behavior
- trigger via button on evidence block or answer card
- if mini-check contradicts chosen answer, row becomes red
- if mini-check agrees, row gets support badge
- mini-check never auto-locks by itself

## 7. Full report requirements
The console must be able to export a full report for all questions in one run.

### Formats
- machine-readable JSON
- human-readable Markdown summary

### Report must include
For every question:
- question metadata
- candidate answers
- candidate sources
- disagreement flags
- accepted decision
- gold lock status
- adjudication note
- trace ids / run ids
- mini-check result
- contract/scorer summary

Aggregate section must include:
- total questions
- auto-lock candidates
- locked gold count
- needs review count
- disagreement histogram
- answerability conflict count
- source conflict count
- mini-check failure count
- route breakdown
- answer type breakdown

## 8. Backend data model

### 8.1 `QuestionReviewRecord`
- `question_id`
- `question`
- `answer_type`
- `primary_route`
- `document_scope`
- `risk_tier`
- `status`
- `disagreement_flags[]`
- `current_run_id`
- `trace_id`
- `candidate_bundle`
- `accepted_decision`
- `report_summary`

### 8.2 `CandidateAnswer`
- `candidate_id`
- `candidate_kind` (`system`, `strong_model`, `challenger`, `mini_check`)
- `answer`
- `answerability`
- `confidence`
- `reasoning_summary`
- `sources[]`
- `support_status`
- `run_id`
- `created_at`

### 8.3 `EvidenceRef`
- `doc_id`
- `doc_title`
- `page_number`
- `snippet`
- `paragraph_id`
- `is_used`
- `source_origin`
- `highlight_offsets`

### 8.4 `AcceptedDecision`
- `final_answer`
- `final_sources[]`
- `answerability`
- `decision_source`
- `reviewer`
- `reviewer_confidence`
- `adjudication_note`
- `locked_at`

## 9. Required API surface

### Read APIs
- `GET /v1/review/questions`
- `GET /v1/review/questions/{questionId}`
- `GET /v1/review/questions/{questionId}/pdf-preview`
- `GET /v1/review/report/{runId}`

### Action APIs
- `POST /v1/review/questions/{questionId}/mini-check`
- `POST /v1/review/questions/{questionId}/accept-candidate`
- `POST /v1/review/questions/{questionId}/custom-decision`
- `POST /v1/review/questions/{questionId}/lock-gold`
- `POST /v1/review/questions/{questionId}/unlock-gold`
- `POST /v1/review/report/{runId}/export`

## 10. Frontend implementation guidance
Use the existing product web app rather than creating a second UI.

Recommended route:
- `/review`
- `/review/:questionId`

Suggested component split:
- `ReviewQuestionList`
- `QuestionSignalsBar`
- `CandidateAnswerCards`
- `EvidenceTable`
- `PdfPreviewPane`
- `DecisionPanel`
- `TraceTabs`
- `RunReportDrawer`

## 11. Storage / artifacts
Recommended artifact outputs:
- `reports/review_runs/{runId}/review_report.json`
- `reports/review_runs/{runId}/review_report.md`
- `reports/review_runs/{runId}/question_status.jsonl`
- `reports/review_runs/{runId}/candidate_bundle.jsonl`

## 12. Acceptance criteria

### Functional
- user can filter questions by disagreement and status
- user can inspect candidate answers side-by-side
- user can open page-grounded PDF preview
- user can run mini-check on selected evidence
- user can lock/unlock gold decision
- user can export full report

### Non-functional
- no fake placeholders in production path
- if data is unavailable, UI must say exactly what is missing
- trace/raw-json view must be available for every reviewed question
- all state-changing actions must be auditable

## 13. Suggested delivery phases

### Phase 1 — MVP review console
- question list
- candidate answer cards
- PDF preview
- lock/unlock gold
- full report export

### Phase 2 — mini-check + disagreement automation
- mini-check action
- derived disagreement signals
- auto-lock candidate flags

### Phase 3 — adjudication productivity
- keyboard shortcuts
- bulk filters
- reviewer analytics
- compare run-to-run
