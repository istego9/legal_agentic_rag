import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { describe, expect, it, vi } from "vitest";
import { hq21Theme } from "../hq21Style";
import { ReviewConsolePanel } from "./ReviewConsolePanel";
import type { ReviewPdfPreview, ReviewRecord } from "./types";

function renderPanel(overrides?: Partial<Record<string, unknown>>) {
  const record: ReviewRecord = {
    question_id: "q-review",
    question: "Which case was decided earlier?",
    answer_type: "name",
    primary_route: "single_case_extraction",
    risk_tier: "high",
    status: "needs_review",
    disagreement_flags: ["answer_conflict"],
    current_run_id: "run-1",
    trace_id: "trace-1",
    candidate_bundle: [
      {
        candidate_id: "system:1",
        candidate_kind: "system",
        answer: "ENF 269/2023",
        answerability: "answerable",
        confidence: 1,
        reasoning_summary: "system summary",
        sources: [
          {
            doc_id: "doc-1",
            doc_title: "Case Digest",
            page_number: 0,
            snippet: "Case ENF 269/2023 was decided on 2 November 2023.",
            is_used: true,
            source_origin: "system",
            source_page_id: "doc-1_0",
          },
        ],
      },
    ],
    accepted_decision: null,
    evidence: { solver_trace: { path: "name_case_timeline" } },
    document_viewer: {},
    promotion_preview: {},
    comparison_context: {},
  };
  const preview: ReviewPdfPreview = {
    run_id: "run-1",
    question_id: "q-review",
    document_id: "doc-1",
    title: "Case Digest",
    pdf_id: "doc-1",
    file_url: "",
    page: {
      page_id: "page-1",
      page_num: 0,
      source_page_id: "doc-1_0",
      used: true,
      chunk_text: "Case ENF 269/2023 was decided on 2 November 2023.",
      page_text: "Structured fallback page text",
      parse_warnings: [],
    },
    fallback: {
      doc_id: "doc-1",
      page_number: 0,
      text: "Structured fallback page text",
      parse_warnings: [],
    },
  };

  const api = {
    listReviewQuestions: vi.fn().mockResolvedValue({ items: [record], total: 1, summary: { run_id: "run-1", total_questions: 1, auto_lock_candidates: 0, locked_gold_count: 0, needs_review_count: 1, disagreement_histogram: { answer_conflict: 1 }, answerability_conflict_count: 0, source_conflict_count: 0, mini_check_failure_count: 0, route_breakdown: { single_case_extraction: 1 }, answer_type_breakdown: { name: 1 } } }),
    getReviewQuestion: vi.fn().mockResolvedValue(record),
    getReviewPdfPreview: vi.fn().mockResolvedValue(preview),
    generateReviewCandidates: vi.fn().mockResolvedValue({ record }),
    runReviewMiniCheck: vi.fn().mockResolvedValue({ record }),
    acceptReviewCandidate: vi.fn().mockResolvedValue({ ...record, accepted_decision: { final_answer: "ENF 269/2023", final_sources: [], decision_source: "system" } }),
    saveReviewCustomDecision: vi.fn().mockResolvedValue(record),
    lockReviewGold: vi.fn().mockResolvedValue({ ...record, status: "gold_locked", accepted_decision: { final_answer: "ENF 269/2023", final_sources: [], decision_source: "system", locked_at: "2026-03-11T00:00:00Z" } }),
    unlockReviewGold: vi.fn().mockResolvedValue({ ...record, status: "review_in_progress" }),
    exportReviewReport: vi.fn().mockResolvedValue({ summary: { total_questions: 1 } }),
    ...(overrides?.api as object),
  };

  const props = {
    api: api as never,
    apiBase: "",
    runId: "run-1",
    questionId: "q-review",
    goldDatasetId: "gold-1",
    onRunIdChange: vi.fn(),
    onQuestionIdChange: vi.fn(),
    onGoldDatasetIdChange: vi.fn(),
    onRecordLoaded: vi.fn(),
    onOpenDebug: vi.fn(),
    onSyncPath: vi.fn(),
    ...(overrides || {}),
  };

  return {
    api,
    ...render(
      <MantineProvider theme={hq21Theme} defaultColorScheme="light">
        <Notifications />
        <ReviewConsolePanel {...props} />
      </MantineProvider>
    ),
  };
}

describe("ReviewConsolePanel", () => {
  it("renders review list and fallback pdf, then locks gold", async () => {
    const { api } = renderPanel();

    await waitFor(() => {
      expect(screen.getAllByText("Which case was decided earlier?").length).toBeGreaterThan(0);
      expect(screen.getAllByText("answer_conflict").length).toBeGreaterThan(0);
      expect(screen.getByText("Structured fallback page text")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Lock Gold" }));

    await waitFor(() => {
      expect(api.lockReviewGold).toHaveBeenCalledTimes(1);
    });
  });
});
