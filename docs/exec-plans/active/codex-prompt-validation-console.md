# Task: Build Validation / Gold Review Console in existing repo

## Goal
Implement a review console inside the existing repository that helps validate question results, compare candidate answers, inspect page-grounded evidence, run a mini-check model on selected snippets, and lock internal gold decisions.

## Why this task exists
The system already has:
- routing benchmark
- law article vertical slice
- law history vertical slice
- cross-law compare vertical slice
- strict scorer / export compliance

What is missing is an operator-facing review console for:
- disagreement triage
- evidence verification on PDF pages
- mini-check contradiction detection
- adjudication and gold locking
- full run report export

## Scope
Build the console inside the existing product surfaces (`apps/web`, `apps/api`).
Do not create a second product or standalone prototype app.

## Design summary
Use a three-pane review screen:
- left: question list with signal badges and filters
- center: question + candidate answers + evidence + decision controls
- right: PDF preview
- bottom: expandable trace/report tabs

This task must use the existing runtime/reporting infrastructure where possible.

## Required deliverables

### 1. Frontend review routes
Add pages/routes such as:
- `/review`
- `/review/:questionId`

### 2. Backend review APIs
Add read/action APIs for:
- list questions for review
- fetch one question review record
- fetch PDF preview metadata
- run mini-check
- accept candidate
- custom decision
- lock gold / unlock gold
- export full review report

### 3. Candidate bundle support
Support at least these candidate answer kinds:
- `system`
- `strong_model`
- `challenger`
- `mini_check`

If strong/challenger data is absent, do not fake it.
Show missing-state explicitly.

### 4. Signals and disagreement logic
Required UI signals:
- answer conflict
- sources conflict
- answerability conflict
- mini-check fail
- missing sources
- telemetry / contract issues
- needs review
- auto-lock candidate
- gold locked

### 5. PDF preview integration
Right-side pane must show document/page preview for selected evidence.
If true PDF preview is unavailable, show a structured text fallback with doc/page/snippet and parse warnings.

### 6. Mini-check workflow
Add a mini-check action that sends:
- question
- answer_type
- selected evidence snippets
- selected candidate answer

and returns:
- support verdict (`supported`, `not_supported`, `insufficient_evidence`)
- optional extracted answer
- confidence
- short rationale

Mini-check must not silently overwrite accepted decision.
It only adds signal.

### 7. Full report export
Add full report export for a run, including:
- per-question candidate bundle
- disagreement flags
- accepted decision
- lock status
- adjudication note
- mini-check result
- trace references
- aggregate summary

### 8. Auditability
All state-changing actions must be auditable.
Keep reviewer, timestamp, and action type.

## Constraints
- no fake data in production path
- no silent fallbacks
- if candidate data is missing, UI must show `not available`
- preserve existing API/runtime behavior unless explicitly extended
- do not weaken scorer / submission contracts

## Files to inspect first
- `apps/web/`
- `apps/api/src/legal_rag_api/`
- `reports/`
- existing run/export/report endpoints
- tests under `tests/contracts` and `tests/integration`

## Suggested data structures
Implement or adapt models for:
- `QuestionReviewRecord`
- `CandidateAnswer`
- `EvidenceRef`
- `AcceptedDecision`
- `MiniCheckResult`
- `ReviewRunSummary`

## Tests required

### Contract / backend
- review list endpoint shape
- question detail endpoint shape
- lock/unlock behavior
- full report export shape
- mini-check action shape

### Integration / frontend
- review page renders list and details
- disagreement badge appears when candidate answers differ
- PDF pane updates when source selected
- lock/unlock flow works
- report export works

### Regression
- existing runtime and export paths still pass strict verify

## Suggested implementation phases

### Phase 1
- list + details + candidate cards + evidence table + PDF pane

### Phase 2
- lock/unlock + custom decision + report export

### Phase 3
- mini-check + disagreement automation + run summary analytics

## Acceptance criteria
- operator can review questions one by one efficiently
- disagreement rows are immediately visible
- evidence can be verified on page/doc level
- gold decision can be locked with an audit trail
- full report can be exported
- `python scripts/agentfirst.py verify --strict` passes

## Deliverable report
Return:
1. files changed
2. backend endpoints added
3. frontend routes/components added
4. disagreement logic implemented
5. mini-check workflow status
6. tests run
7. remaining gaps
