import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { hq21Theme } from "./hq21Style";

function renderApp() {
  return render(
    <MantineProvider theme={hq21Theme} defaultColorScheme="light">
      <Notifications />
      <App />
    </MantineProvider>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("App e2e smoke", () => {
  it("follows the project session, corpus package, and compare flow", async () => {
    const cohortRows = {
      by_answer_type: [{ answer_type: "free_text", question_count: 3, coverage_share: 1, current_overall: 0.91, weighted_current_overall_value: 0.9, weighted_grounding_value: 0.89, overall_delta: 0.03, grounding_delta: 0.02, weighted_overall_delta: 0.04, weighted_grounding_delta: 0.01 }],
      by_route_family: [{ route_family: "article_lookup", question_count: 3, coverage_share: 1, current_overall: 0.88, weighted_current_overall_value: 0.86, weighted_grounding_value: 0.84, overall_delta: 0.02, grounding_delta: 0.01, weighted_overall_delta: 0.03, weighted_grounding_delta: 0.01 }],
      by_answerability: [{ answerability: "answerable", question_count: 3, coverage_share: 1, current_overall: 0.87, weighted_current_overall_value: 0.85, weighted_grounding_value: 0.83, overall_delta: 0.01, grounding_delta: 0.01, weighted_overall_delta: 0.02, weighted_grounding_delta: 0.01 }],
      by_document_scope: [{ document_scope: "single_doc", question_count: 3, coverage_share: 1, current_overall: 0.86, weighted_current_overall_value: 0.84, weighted_grounding_value: 0.82, overall_delta: 0.02, grounding_delta: 0.01, weighted_overall_delta: 0.02, weighted_grounding_delta: 0.01 }],
      by_corpus_domain: [{ corpus_domain: "law", question_count: 3, coverage_share: 1, current_overall: 0.85, weighted_current_overall_value: 0.83, weighted_grounding_value: 0.81, overall_delta: 0.01, grounding_delta: 0.01, weighted_overall_delta: 0.02, weighted_grounding_delta: 0.01 }],
      by_temporal_scope: [{ temporal_scope: "current", question_count: 3, coverage_share: 1, current_overall: 0.84, weighted_current_overall_value: 0.82, weighted_grounding_value: 0.8, overall_delta: 0.01, grounding_delta: 0.01, weighted_overall_delta: 0.01, weighted_grounding_delta: 0.01 }],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        let payload: Record<string, unknown> = {};
        if (url.includes("/v1/corpus/import-upload")) {
          payload = { job_id: "job-1" };
        } else if (url.includes("/v1/corpus/processing-results")) {
          payload = {
            latest_job: { blob_url: "/tmp/legal-corpus.zip" },
            jobs: [{ job_id: "job-1", blob_url: "/tmp/legal-corpus.zip", status: "completed" }],
            summary: {
              documents: 2,
              pages: 4,
              paragraphs: 8,
              processing_status_counts: { completed: 2 },
              by_doc_type: { law: 2 },
            },
            processing_documents: [],
          };
        } else if (url.includes("/v1/eval/runs/eval-1/report")) {
          payload = {
            items: [{ question_id: "q-1", overall_score: 0.72 }],
            value_report: cohortRows,
          };
        } else if (url.includes("/v1/eval/runs/eval-1")) {
          payload = {
            metrics: {
              overall_score: 0.91,
              answer_score_mean: 0.88,
              grounding_score_mean: 0.86,
              telemetry_factor: 1,
              ttft_factor: 0.93,
              slices: {
                by_answer_type: [{ answer_type: "free_text", question_count: 3, overall_score_mean: 0.91 }],
                by_route_family: [{ route_family: "article_lookup", question_count: 3, grounding_score_mean: 0.86 }],
              },
              value_report: cohortRows,
            },
          };
        } else if (url.includes("/v1/eval/compare")) {
          payload = {
            metric_deltas: { overall_score_delta: 0.04, grounding_score_delta: 0.02 },
            compare_slices: {
              by_answer_type: [{ answer_type: "free_text", left_question_count: 3, right_question_count: 3, overall_score_mean_delta: 0.04, grounding_score_mean_delta: 0.02, answer_score_mean_delta: 0.03, ttft_factor_mean_delta: 0.01 }],
              by_route_family: [{ route_family: "article_lookup", left_question_count: 3, right_question_count: 3, overall_score_mean_delta: 0.03, grounding_score_mean_delta: 0.02, answer_score_mean_delta: 0.02, telemetry_factor_mean_delta: 0.01 }],
            },
            value_report: cohortRows,
            question_deltas: [{ question_id: "q-1", delta: -0.08 }],
          };
        } else if (url.includes("/v1/experiments/compare")) {
          payload = {
            metric_deltas: { overall_score_delta: 0.05, grounding_score_delta: 0.03 },
            compare_slices: {
              by_answer_type: [{ answer_type: "free_text", left_question_count: 3, right_question_count: 3, overall_score_mean_delta: 0.05 }],
              by_route_family: [{ route_family: "article_lookup", left_question_count: 3, right_question_count: 3, grounding_score_mean_delta: 0.03 }],
            },
            value_report: cohortRows,
            question_deltas: [{ question_id: "q-2", delta: -0.06 }],
          };
        }

        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      })
    );

    renderApp();

    const timestampLabel = screen.getAllByText(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)[0];
    expect(timestampLabel).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Question Dataset Name"), {
      target: { value: "Alpha Questions" },
    });
    fireEvent.change(screen.getByLabelText("Question Dataset ID"), {
      target: { value: "dataset-alpha" },
    });
    expect(screen.getAllByText("Alpha Questions").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText("Corpus"));
    fireEvent.change(screen.getByLabelText("ZIP File"), {
      target: {
        files: [new File(["dummy"], "legal-corpus.zip", { type: "application/zip" })],
      },
    });
    expect(screen.queryByLabelText("Processing Limit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import ZIP" }));
    fireEvent.click(screen.getByRole("button", { name: "Load Processing Results" }));

    await waitFor(() => {
      expect(screen.getAllByText("legal-corpus.zip").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByText("Evaluation"));
    fireEvent.change(screen.getByLabelText("Eval Run ID"), { target: { value: "eval-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Load Eval Run" }));
    fireEvent.click(screen.getByRole("button", { name: "Load Eval Report" }));

    await waitFor(() => {
      expect(screen.getByText("By Temporal Scope")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Left Eval Run ID"), { target: { value: "eval-left" } });
    fireEvent.change(screen.getByLabelText("Right Eval Run ID"), { target: { value: "eval-right" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare Eval Runs" }));

    await waitFor(() => {
      expect(screen.getAllByText("By Corpus Domain").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByText("Experiments"));
    fireEvent.click(screen.getByRole("tab", { name: "Compare" }));
    fireEvent.change(screen.getByLabelText("Left Run ID"), { target: { value: "exp-left" } });
    fireEvent.change(screen.getByLabelText("Right Run ID"), { target: { value: "exp-right" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare Runs" }));

    await waitFor(() => {
      expect(screen.getAllByText("By Answerability").length).toBeGreaterThan(0);
    });
  }, 15000);

  it("opens a document without creating a tracked job entry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        let payload: Record<string, unknown> = {};

        if (url.includes("/v1/corpus/processing-results")) {
          payload = {
            latest_job: { blob_url: "/tmp/legal-corpus.zip" },
            jobs: [{ job_id: "job-1", blob_url: "/tmp/legal-corpus.zip", status: "completed" }],
            summary: {
              documents: 1,
              pages: 1,
              paragraphs: 1,
              processing_status_counts: { completed: 1 },
              by_doc_type: { law: 1 },
            },
            processing_documents: [
              {
                document_id: "doc-1",
                processing_status: "completed",
              },
            ],
          };
        } else if (url.includes("/v1/corpus/documents/doc-1/detail")) {
          payload = {
            document: {
              document_id: "doc-1",
              doc_type: "law",
              title: "Law No. 1",
              law_number: "No. 1",
              page_count: 1,
              status: "parsed",
            },
            document_processing: {
              text_quality_score: 0.92,
              llm_document_status: "completed",
              llm_document_model: "gpt-4o-mini",
            },
            document_ontology_view: {},
            summary: {
              page_count: 1,
              chunk_count: 1,
              llm_status_counts: { completed: 1 },
              ontology_assertion_count: 0,
            },
            pages: [
              {
                page_id: "page-1",
                source_page_id: "doc-1_0",
                page_num: 0,
                text: "Document page text",
                chunk_count: 1,
                chunks: [
                  {
                    paragraph_id: "chunk-1",
                    paragraph_index: 0,
                    paragraph_class: "body",
                    text: "Chunk source text",
                    llm_status: "completed",
                    llm_section_type: "other",
                    llm_summary: "Chunk summary",
                    llm_tags: ["tag_a"],
                    entities: ["Entity A"],
                    case_refs: [],
                    law_refs: ["Law No. 1"],
                    dates: [],
                  },
                ],
                ontology_assertions: [],
              },
            ],
            file_url: "/v1/corpus/documents/doc-1/file",
          };
        } else if (url.includes("/v1/corpus/documents")) {
          payload = {
            total: 1,
            items: [
              {
                document_id: "doc-1",
                doc_type: "law",
                title: "Law No. 1",
                law_number: "No. 1",
                page_count: 1,
                status: "parsed",
              },
            ],
          };
        } else if (url.includes("/v1/corpus/documents/doc-1/process-chunks-llm")) {
          payload = {
            document_id: "doc-1",
            total: 1,
            processed: 1,
            skipped: 0,
            failed: 0,
            model: "gpt-4o-mini",
          };
        }

        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      })
    );

    renderApp();

    fireEvent.click(screen.getByText("Corpus"));

    await waitFor(() => {
      expect(screen.getByText("Law No. 1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Open Document" }));

    await waitFor(() => {
      expect(screen.getByText("Chunk 1")).toBeInTheDocument();
      expect(screen.getByText("Chunk summary")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Job Center/ }));
    const jobCenterDrawer = await screen.findByRole("dialog", { name: "Job Center" });
    expect(within(jobCenterDrawer).getByText("No tracked jobs yet.")).toBeInTheDocument();
    expect(within(jobCenterDrawer).queryByText("Open Document")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run Document + Chunk LLM" }));
    await waitFor(() => {
      expect(within(jobCenterDrawer).getByText("Run Document + Chunk LLM")).toBeInTheDocument();
    });
  }, 15000);
});
