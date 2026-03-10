# Web Console E2E Runbook

## Goal
Validate the project-centric web console end to end with the current Jobs To Be Done layout:
- `Project Session`
- `Corpus Package`
- `Question Dataset`
- `Review / Evaluation / Experiments / Gold / Synthetic`

## E2E Policy
- Every critical operator flow must remain covered by an automated smoke.
- Current smoke command:
  - `cd apps/web && npm run test:e2e`
- When a flow changes materially, update both:
  - the smoke spec in `apps/web/src/App.e2e.test.tsx`
  - this runbook if the browser/manual path also changed

## Prerequisites
1. Start API:
   - `PYTHONPATH=apps/api/src:. .venv/bin/uvicorn legal_rag_api.main:app --host 127.0.0.1 --port 8000`
2. Start frontend:
   - `cd apps/web`
   - `npm run dev -- --host 127.0.0.1 --port 4173`
3. Open:
   - `http://127.0.0.1:4173/`

## E2E Steps
1. Open `Projects`.
   - Expect the first `Project Session` name to be a timestamp-like label, not `Project 01`.
   - Expect `Project ID` and `Question Dataset ID` to be empty by default.

2. In `Project Settings` set:
   - `Project ID`
   - `Question Dataset Name`
   - `Question Dataset ID`
   - optional `Question ID`
   - Expect the header and left context card to show the friendly dataset label instead of a fake UUID placeholder.

3. Open `Corpus`.
   - Upload a ZIP file.
   - Expect `Corpus Package` to immediately show the uploaded ZIP filename.
   - Click `Load Processing Results`.
   - Expect corpus jobs to render using the ZIP filename or blob basename, not an opaque job id.

4. In `Corpus -> Documents`, click `Load Documents`.
   - If documents exist, open one document and verify the detail viewer renders.
   - If documents do not exist yet, the UI must show `empty` state without breaking layout.

5. Open `Datasets`.
   - Import or list questions.
   - Expect question objects to appear in the questions table.
   - Run `Ask` or `Run Batch`.

6. Open `Review & Runs`.
   - Load a run by `Run ID`.
   - Load `Run Question Review`.
   - Expect split view: question/evidence on the left, answer in center area, PDF on the right if available.
   - If PDF is absent, expect `empty` state, not broken layout.

7. Open `Evaluation`.
   - Create or load an eval run.
   - Verify single-run screen renders:
     - KPI cards
     - slices by `answer_type`
     - slices by `route_family`
     - `Value Report` with 6 cohorts:
       - `answer_type`
       - `route_family`
       - `answerability`
       - `document_scope`
       - `corpus_domain`
       - `temporal_scope`
   - If any cohort arrays are missing, expect `partial` state.

8. In `Evaluation -> Eval Compare`:
   - Enter two eval run ids.
   - Click `Compare Eval Runs`.
   - Expect:
     - metric deltas
     - compare slices for `answer_type`
     - compare slices for `route_family`
     - `Value Report` with the same 6 cohorts
     - top regressions from `question_deltas`
   - If compare data is not available, expect `empty` or `partial`, not a broken block.

9. Open `Experiments -> Compare`.
   - Enter two experiment run ids.
   - Expect:
     - metric deltas
     - compare slices
     - `Value Report` with the same 6 cohorts
     - top regressions
   - If compare artifacts are unavailable, expect `empty` or `partial`.

10. Open `Gold`, `Synthetic`, `Config`.
   - Verify each screen keeps the current project context.
   - Verify `Job Center` and `Debug Drawer` open without affecting the main layout.

## Pass Criteria
- No fake default IDs in the initial project/session view.
- `Corpus Package` is named from the uploaded ZIP.
- `Question Dataset` is shown with a friendly label.
- All major screens render `loading / empty / error / partial` states correctly.
- `Evaluation` and `Experiments Compare` render the full Phase 2 cohort set when payloads exist.
