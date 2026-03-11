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

describe("App project workspace", () => {
  it("opens the review console from a /review deep link", async () => {
    window.history.pushState({}, "", "/review/q-review");
    renderApp();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Load Review List" })).toBeInTheDocument();
      expect(screen.getByLabelText("Question ID")).toHaveValue("q-review");
    });

    window.history.pushState({}, "", "/");
  }, 15000);

  it("keeps dataset context when switching between projects", () => {
    renderApp();
    const projectFocusPanel = screen.getByText("Project Settings").closest(".mantine-Paper-root");
    expect(projectFocusPanel).not.toBeNull();
    const focusPanelQueries = within(projectFocusPanel as HTMLElement);

    fireEvent.change(focusPanelQueries.getByLabelText("Project Session"), {
      target: { value: "Alpha Project" }
    });
    fireEvent.change(focusPanelQueries.getByLabelText("Question Dataset ID"), {
      target: { value: "dataset-alpha" }
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Project" }));
    fireEvent.change(focusPanelQueries.getByLabelText("Project Session"), {
      target: { value: "Beta Project" }
    });
    fireEvent.change(focusPanelQueries.getByLabelText("Question Dataset ID"), {
      target: { value: "dataset-beta" }
    });

    fireEvent.click(screen.getByText("Alpha Project"));

    expect(focusPanelQueries.getByLabelText("Project Session")).toHaveValue("Alpha Project");
    expect(focusPanelQueries.getByLabelText("Question Dataset ID")).toHaveValue("dataset-alpha");
  }, 15000);

  it("auto-loads shared corpus jobs and documents on the corpus screen", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: Record<string, unknown> = {};

      if (url.includes("/v1/corpus/processing-results")) {
        payload = {
          latest_job: { blob_url: "/workspace/reports/uploads/shared-corpus.zip" },
          jobs: [{ job_id: "job-1", blob_url: "/workspace/reports/uploads/shared-corpus.zip", status: "completed" }],
          summary: {
            documents: 2,
            pages: 4,
            paragraphs: 8,
            processing_status_counts: { completed: 1 },
            by_doc_type: { law: 1, case: 1 },
          },
          processing_documents: [],
        };
      } else if (url.includes("/v1/corpus/documents")) {
        payload = {
          total: 2,
          items: [
            { document_id: "doc-1", title: "Sample law", doc_type: "law" },
            { document_id: "doc-2", title: "Sample case", doc_type: "case" },
          ],
        };
      }

      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    fireEvent.click(screen.getByText("Corpus"));

    await waitFor(() => {
      expect(screen.getAllByText("shared-corpus.zip").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));

    await waitFor(() => {
      expect(screen.getByText("Sample law")).toBeInTheDocument();
      expect(screen.getByText("Sample case")).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/corpus/processing-results?limit=200"),
      expect.any(Object)
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/corpus/documents?limit=30"),
      expect.any(Object)
    );
  }, 15000);

  it("re-ingests a document from the documents list", async () => {
    let processingCalls = 0;
    let documentsCalls = 0;
    let reingestCalls = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes("/v1/corpus/documents/doc-1/reingest")) {
        reingestCalls += 1;
        return new Response(JSON.stringify({ status: "accepted", job_id: "job-reingest-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      if (url.includes("/v1/corpus/processing-results")) {
        processingCalls += 1;
        return new Response(
          JSON.stringify({
            latest_job: { blob_url: "/workspace/reports/uploads/shared-corpus.zip" },
            jobs: [{ job_id: "job-1", blob_url: "/workspace/reports/uploads/shared-corpus.zip", status: "completed" }],
            summary: {
              documents: 1,
              pages: 2,
              paragraphs: 2,
              processing_status_counts: { completed: 1 },
              by_doc_type: { case: 1 },
            },
            processing_documents: [{ document_id: "doc-1", processing_status: "completed" }],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      if (url.includes("/v1/corpus/documents?")) {
        documentsCalls += 1;
        return new Response(
          JSON.stringify({
            total: 1,
            items: [{ document_id: "doc-1", title: "Sample case", doc_type: "case", status: "parsed" }],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    fireEvent.click(screen.getByText("Corpus"));
    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));

    await waitFor(() => {
      expect(screen.getByText("Sample case")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Re-ingest Document" }));

    await waitFor(() => {
      expect(reingestCalls).toBe(1);
      expect(processingCalls).toBeGreaterThan(1);
      expect(documentsCalls).toBeGreaterThan(1);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/corpus/documents/doc-1/reingest"),
      expect.objectContaining({ method: "POST" })
    );
  }, 15000);

  it("shows human-readable corpus labels and chunk metadata in the document viewer", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: Record<string, unknown> = {};

      if (url.includes("/v1/corpus/documents/doc-1/detail")) {
        payload = {
          document: {
            document_id: "doc-1",
            pdf_id: "5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2",
            canonical_doc_id: "5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2-v1",
            content_hash: "e1262810ea8a916a3c2d215b8577f5ef95103316796925a33c9cf354d1920b76",
            project_id: "00000000-0000-0000-0000-000000000000",
            doc_type: "case",
            title: "Document 5d3df6d69fac",
            citation_title: "Document 5d3df6d69fac",
            law_number: "ARB-016-2023",
            case_id: "No",
            year: 2023,
            page_count: 19,
            status: "parsed",
            topic_tags: [],
            legal_domains: [],
            entity_names: [],
            citation_keys: [],
          },
          document_processing: {
            text_quality_score: 0.8554891820071491,
            llm_document_status: "completed",
            llm_document_model: "gpt-4o-mini",
            llm_document: {
              summary: "The tribunal order addresses enforcement and cites the underlying arbitration matter.",
              key_topics: ["enforcement", "arbitration"],
              key_entities: ["Ozias", "Tribunal"],
              case_refs: ["Case No. ARB-016-2023"],
            },
            agentic_enrichment: {
              status: "completed",
              assertion_count: 2,
              candidate_entry_count: 1,
              active_entry_count: 3,
              chunk_coverage_ratio: 1,
            },
          },
          document_ontology_view: {
            actor_summary: ["Tribunal"],
            beneficiary_summary: ["Claimant"],
          },
          summary: {
            page_count: 19,
            chunk_count: 2,
            llm_status_counts: {
              completed: 2,
            },
            ontology_assertion_count: 2,
          },
          pages: [
            {
              page_id: "page-1",
              source_page_id: "5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2_0",
              page_num: 0,
              text: "ENF 269/2023 page text",
              chunk_count: 2,
              chunks: [
                {
                  paragraph_id: "chunk-1",
                  paragraph_index: 0,
                  document_id: "doc-1",
                  page_id: "page-1",
                  paragraph_class: "case_excerpt",
                  text: "Long chunk text for the first chunk",
                  entities: ["Ozias", "Ori", "Octavio", "Obadiah"],
                  case_refs: ["Case No. ARB-016-2023"],
                  law_refs: [],
                  dates: ["2023", "2025"],
                  llm_status: "completed",
                  llm_section_type: "other",
                  llm_summary: "Enforcement order heading",
                  llm_tags: ["other", "case_reference"],
                },
              ],
              ontology_assertions: [
                {
                  assertion_id: "assertion-1",
                  subject_text: "Tribunal",
                  relation_type: "orders",
                  object_text: "enforcement",
                  modality: "directive",
                },
              ],
            },
          ],
          file_url: "/v1/corpus/documents/doc-1/file",
        };
      } else if (url.includes("/v1/corpus/processing-results")) {
        payload = {
          latest_job: { blob_url: "/workspace/reports/uploads/shared-corpus.zip" },
          jobs: [{ job_id: "job-1", blob_url: "/workspace/reports/uploads/shared-corpus.zip", status: "completed" }],
          summary: {
            documents: 1,
            pages: 19,
            paragraphs: 2,
            processing_status_counts: { completed: 1 },
            by_doc_type: { case: 1 },
          },
          processing_documents: [
            {
              document_id: "doc-1",
              processing_status: "completed",
              llm_document_status: "completed",
              enrichment_status: "completed",
              agent_assertion_count: 2,
              agent_chunk_coverage_ratio: 1,
            },
          ],
          enrichment_jobs: [
            {
              job_id: "enrich-1",
              processing_profile_version: "agentic_corpus_enrichment_v1",
              status: "completed",
              document_count: 1,
              processed_document_count: 1,
              chunk_count: 2,
              processed_chunk_count: 2,
              candidate_entry_count: 1,
              active_entry_count: 3,
              llm_model_version: "gpt-4o-mini",
            },
          ],
        };
      } else if (url.includes("/v1/corpus/documents")) {
        payload = {
          total: 1,
          items: [
            {
              document_id: "doc-1",
              pdf_id: "5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2",
              canonical_doc_id: "5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2-v1",
              content_hash: "e1262810ea8a916a3c2d215b8577f5ef95103316796925a33c9cf354d1920b76",
              project_id: "00000000-0000-0000-0000-000000000000",
              doc_type: "case",
              title: "Document 5d3df6d69fac",
              citation_title: "Document 5d3df6d69fac",
              law_number: "ARB-016-2023",
              case_id: "No",
              year: 2023,
              page_count: 19,
              status: "parsed",
              topic_tags: [],
              legal_domains: [],
              entity_names: [],
              citation_keys: [],
            },
          ],
        };
      }

      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    fireEvent.click(screen.getByText("Corpus"));
    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));

    await waitFor(() => {
      expect(screen.getByText("Case ARB-016-2023")).toBeInTheDocument();
    });

    expect(screen.queryByText("Document 5d3df6d69fac")).not.toBeInTheDocument();
    expect(screen.queryByText("doc-1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Document" }));

    await waitFor(() => {
      expect(screen.getByText("Extracted PDF Page Text")).toBeInTheDocument();
      expect(screen.getByText("Chunk 1")).toBeInTheDocument();
      expect(screen.getByText("Paragraph Class")).toBeInTheDocument();
      expect(screen.getByText("Entities")).toBeInTheDocument();
      expect(screen.getByText("Case Refs")).toBeInTheDocument();
      expect(screen.getByText("Tags")).toBeInTheDocument();
      expect(screen.getByText("Enforcement order heading")).toBeInTheDocument();
      expect(screen.getAllByText("Chunk LLM Coverage").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Agentic Enrichment Status").length).toBeGreaterThan(0);
      expect(screen.getByText("LLM Document Summary")).toBeInTheDocument();
      expect(screen.getByText(/Section Type: other/)).toBeInTheDocument();
      expect(screen.getByText("Assertions on Selected Page")).toBeInTheDocument();
      expect(screen.getByText(/Tribunal orders enforcement/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Job Center/ }));

    const jobCenterDrawer = await screen.findByRole("dialog", { name: "Job Center" });
    expect(within(jobCenterDrawer).getByText("No tracked jobs yet.")).toBeInTheDocument();
    expect(within(jobCenterDrawer).queryByText("Open Document")).not.toBeInTheDocument();
  }, 15000);
});
