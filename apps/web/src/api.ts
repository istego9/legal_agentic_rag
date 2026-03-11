type HttpMethod = "GET" | "POST" | "PATCH";

export interface RuntimePolicy {
  use_llm: boolean;
  max_candidate_pages: number;
  max_context_paragraphs: number;
  page_index_base_export: 0 | 1;
  scoring_policy_version: string;
  allow_dense_fallback: boolean;
  return_debug_trace: boolean;
}

function joinUrl(baseUrl: string, path: string): string {
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function buildChunksPath(projectId?: string, documentId?: string, limit?: number): string {
  const params = new URLSearchParams();
  if ((projectId ?? "").trim()) {
    params.set("project_id", (projectId ?? "").trim());
  }
  if ((documentId ?? "").trim()) {
    params.set("document_id", (documentId ?? "").trim());
  }
  if (typeof limit === "number" && Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(Math.trunc(limit)));
  }
  const qs = params.toString();
  return qs ? `/v1/corpus/chunks?${qs}` : "/v1/corpus/chunks";
}

function buildDocumentsPath(projectId?: string, limit?: number): string {
  const params = new URLSearchParams();
  if ((projectId ?? "").trim()) {
    params.set("project_id", (projectId ?? "").trim());
  }
  if (typeof limit === "number" && Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(Math.trunc(limit)));
  }
  const qs = params.toString();
  return qs ? `/v1/corpus/documents?${qs}` : "/v1/corpus/documents";
}

function buildExperimentProfilesPath(limit?: number): string {
  const params = new URLSearchParams();
  if (typeof limit === "number" && Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(Math.trunc(limit)));
  }
  const qs = params.toString();
  return qs ? `/v1/experiments/profiles?${qs}` : "/v1/experiments/profiles";
}

function buildExperimentLeaderboardPath(limit?: number, stageType?: string, experimentId?: string): string {
  const params = new URLSearchParams();
  if (typeof limit === "number" && Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(Math.trunc(limit)));
  }
  if ((stageType ?? "").trim()) {
    params.set("stage_type", (stageType ?? "").trim());
  }
  if ((experimentId ?? "").trim()) {
    params.set("experiment_id", (experimentId ?? "").trim());
  }
  const qs = params.toString();
  return qs ? `/v1/experiments/leaderboard?${qs}` : "/v1/experiments/leaderboard";
}

function buildReviewQuestionsPath(runId: string, filters?: Record<string, unknown>): string {
  const params = new URLSearchParams();
  params.set("run_id", runId);
  for (const [key, value] of Object.entries(filters ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (typeof value === "boolean") {
      if (value) {
        params.set(key, "true");
      }
      continue;
    }
    const token = String(value).trim();
    if (!token) {
      continue;
    }
    params.set(key, token);
  }
  return `/v1/review/questions?${params.toString()}`;
}

async function parseResponseBody(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return { raw: text };
  }
}

async function request<T>(baseUrl: string, method: HttpMethod, path: string, body?: unknown): Promise<T> {
  const res = await fetch(joinUrl(baseUrl, path), {
    method,
    headers: {
      "Content-Type": "application/json"
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });

  const data = await parseResponseBody(res);
  if (!res.ok) {
    throw new Error(JSON.stringify(data));
  }
  return data as T;
}

async function requestForm<T>(baseUrl: string, path: string, formData: FormData): Promise<T> {
  const res = await fetch(joinUrl(baseUrl, path), {
    method: "POST",
    body: formData
  });
  const data = await parseResponseBody(res);
  if (!res.ok) {
    throw new Error(JSON.stringify(data));
  }
  return data as T;
}

export function createApi(baseUrl: string) {
  return {
    health: () => request<Record<string, unknown>>(baseUrl, "GET", "/v1/health"),
    importZip: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/corpus/import-zip", payload),
    importZipUpload: (formData: FormData) =>
      requestForm<Record<string, unknown>>(baseUrl, "/v1/corpus/import-upload", formData),
    processingResults: (projectId?: string, limit = 200) => {
      const params = new URLSearchParams();
      if ((projectId ?? "").trim()) {
        params.set("project_id", (projectId ?? "").trim());
      }
      params.set("limit", String(limit));
      return request<Record<string, unknown>>(baseUrl, "GET", `/v1/corpus/processing-results?${params.toString()}`);
    },
    listDocuments: (projectId?: string, limit?: number) =>
      request<Record<string, unknown>>(baseUrl, "GET", buildDocumentsPath(projectId, limit)),
    reingestDocument: (documentId: string) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/corpus/documents/${encodeURIComponent(documentId)}/reingest`, {}),
    getDocumentDetail: (documentId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/corpus/documents/${encodeURIComponent(documentId)}/detail`),
    processDocumentChunksLlm: (documentId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/corpus/documents/${encodeURIComponent(documentId)}/process-chunks-llm`, payload),
    listChunks: (projectId?: string, documentId?: string, limit?: number) =>
      request<Record<string, unknown>>(baseUrl, "GET", buildChunksPath(projectId, documentId, limit)),
    search: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/corpus/search", payload),
    importQuestions: (datasetId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/qa/datasets/${datasetId}/import-questions`, payload),
    listDatasetQuestions: (datasetId: string, limit: number) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/qa/datasets/${datasetId}/questions?limit=${encodeURIComponent(String(limit))}`),
    ask: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/qa/ask", payload),
    askBatch: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/qa/ask-batch", payload),
    getRun: (runId: string) => request<Record<string, unknown>>(baseUrl, "GET", `/v1/runs/${runId}`),
    getRunQuestionDetail: (runId: string, questionId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionId)}/detail`),
    listReviewQuestions: (runId: string, filters?: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "GET", buildReviewQuestionsPath(runId, filters)),
    getReviewQuestion: (runId: string, questionId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/review/questions/${encodeURIComponent(questionId)}?run_id=${encodeURIComponent(runId)}`),
    getReviewPdfPreview: (runId: string, questionId: string, documentId?: string, pageId?: string) => {
      const params = new URLSearchParams({ run_id: runId });
      if ((documentId ?? "").trim()) {
        params.set("document_id", (documentId ?? "").trim());
      }
      if ((pageId ?? "").trim()) {
        params.set("page_id", (pageId ?? "").trim());
      }
      return request<Record<string, unknown>>(baseUrl, "GET", `/v1/review/questions/${encodeURIComponent(questionId)}/pdf-preview?${params.toString()}`);
    },
    getReviewReport: (runId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/review/report/${encodeURIComponent(runId)}`),
    generateReviewCandidates: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/generate-candidates?run_id=${encodeURIComponent(runId)}`, payload),
    runReviewMiniCheck: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/mini-check?run_id=${encodeURIComponent(runId)}`, payload),
    acceptReviewCandidate: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/accept-candidate?run_id=${encodeURIComponent(runId)}`, payload),
    saveReviewCustomDecision: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/custom-decision?run_id=${encodeURIComponent(runId)}`, payload),
    lockReviewGold: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/lock-gold?run_id=${encodeURIComponent(runId)}`, payload),
    unlockReviewGold: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/questions/${encodeURIComponent(questionId)}/unlock-gold?run_id=${encodeURIComponent(runId)}`, payload),
    exportReviewReport: (runId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/review/report/${encodeURIComponent(runId)}/export`, payload),
    promoteRunQuestionToGold: (runId: string, questionId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionId)}/promote-to-gold`, payload),
    exportSubmission: (runId: string, payload: { page_index_base: 0 | 1 }) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/runs/${runId}/export-submission`, payload),
    createEvalRun: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/eval/runs", payload),
    getEvalRun: (evalRunId: string) => request<Record<string, unknown>>(baseUrl, "GET", `/v1/eval/runs/${evalRunId}`),
    getEvalReport: (evalRunId: string) => request<Record<string, unknown>>(baseUrl, "GET", `/v1/eval/runs/${evalRunId}/report`),
    compareEvalRuns: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/eval/compare", payload),
    createGoldDataset: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/gold/datasets", payload),
    createGoldQuestion: (goldDatasetId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/gold/datasets/${goldDatasetId}/questions`, payload),
    lockGoldDataset: (goldDatasetId: string) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/gold/datasets/${goldDatasetId}/lock`, {}),
    exportGoldDataset: (goldDatasetId: string) => request<Record<string, unknown>>(baseUrl, "GET", `/v1/gold/datasets/${goldDatasetId}/export`),
    createSynthJob: (payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", "/v1/synth/jobs", payload),
    previewSynth: (jobId: string, payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", `/v1/synth/jobs/${jobId}/preview`, payload),
    publishSynth: (jobId: string, payload: Record<string, unknown>) => request<Record<string, unknown>>(baseUrl, "POST", `/v1/synth/jobs/${jobId}/publish`, payload),
    listPolicies: () => request<Record<string, unknown>>(baseUrl, "GET", "/v1/config/scoring-policies"),
    createExperimentProfile: (payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", "/v1/experiments/profiles", payload),
    listExperimentProfiles: (limit?: number) =>
      request<Record<string, unknown>>(baseUrl, "GET", buildExperimentProfilesPath(limit)),
    createExperiment: (payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", "/v1/experiments", payload),
    getExperiment: (experimentId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/experiments/${encodeURIComponent(experimentId)}`),
    runExperiment: (experimentId: string, payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", `/v1/experiments/${encodeURIComponent(experimentId)}/runs`, payload),
    getExperimentRun: (experimentRunId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/experiments/runs/${encodeURIComponent(experimentRunId)}`),
    getExperimentRunAnalysis: (experimentRunId: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", `/v1/experiments/runs/${encodeURIComponent(experimentRunId)}/analysis`),
    compareExperimentRuns: (payload: Record<string, unknown>) =>
      request<Record<string, unknown>>(baseUrl, "POST", "/v1/experiments/compare", payload),
    getExperimentLeaderboard: (limit?: number, stageType?: string, experimentId?: string) =>
      request<Record<string, unknown>>(baseUrl, "GET", buildExperimentLeaderboardPath(limit, stageType, experimentId))
  };
}

export function defaultRuntimePolicy(useLlm: boolean): RuntimePolicy {
  return {
    use_llm: useLlm,
    max_candidate_pages: 8,
    max_context_paragraphs: 8,
    page_index_base_export: 0,
    scoring_policy_version: "contest_v2026_public_rules_v1",
    allow_dense_fallback: true,
    return_debug_trace: true
  };
}

export { joinUrl };
