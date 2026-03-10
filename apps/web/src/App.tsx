import { Suspense, lazy, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Alert,
  AppShell,
  Badge,
  Box,
  Burger,
  Button,
  Checkbox,
  Code,
  Divider,
  Drawer,
  FileInput,
  Grid,
  Group,
  Loader,
  NavLink,
  Paper,
  Progress,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconBooks,
  IconChartBar,
  IconCheckupList,
  IconDatabase,
  IconFileAnalytics,
  IconFileStack,
  IconFlask2,
  IconFolders,
  IconLayoutDashboard,
  IconMessageSearch,
  IconRocket,
  IconSettings,
  IconSparkles,
} from "@tabler/icons-react";
import { createApi, defaultRuntimePolicy, joinUrl } from "./api";
import { t } from "./i18n";

const PdfReviewViewer = lazy(() => import("./PdfReviewViewer"));

type SectionKey =
  | "projects"
  | "overview"
  | "corpus"
  | "datasets"
  | "review-runs"
  | "evaluation"
  | "experiments"
  | "gold"
  | "synthetic"
  | "config";

type ConsoleViewState = {
  loading: boolean;
  partial: string;
  error: string;
};

type ProjectWorkspaceMetrics = {
  corpusJobs: number;
  documents: number;
  chunks: number;
  questions: number;
  warnings: number;
};

type ProjectWorkspace = {
  workspaceId: string;
  label: string;
  datasetLabel: string;
  corpusLabel: string;
  projectId: string;
  datasetId: string;
  goldDatasetId: string;
  questionId: string;
  questionText: string;
  answerType: string;
  metrics: ProjectWorkspaceMetrics;
};

type ActionState = {
  loading: boolean;
  error: string;
};

type ActivityStatus = "processing" | "completed" | "failed";

type ActivityItem = {
  id: string;
  label: string;
  status: ActivityStatus;
  timestamp: number;
  artifactId?: string;
  detail?: string;
};

type ValidationLevel = "error" | "warning" | "success";

type ValidationItem = {
  id: string;
  level: ValidationLevel;
  title: string;
  detail: string;
};

type NavItem = {
  key: SectionKey;
  label: string;
  icon: typeof IconLayoutDashboard;
};

function initialConsoleViewState(): ConsoleViewState {
  return {
    loading: false,
    partial: "",
    error: "",
  };
}

function pretty(data: unknown): string {
  if (typeof data === "string") {
    return data;
  }
  return JSON.stringify(data, null, 2);
}

function arrayFrom(data: Record<string, unknown> | null, ...keys: string[]): Array<Record<string, unknown>> {
  for (const key of keys) {
    const value = (data as Record<string, unknown> | null)?.[key];
    if (Array.isArray(value)) {
      return value as Array<Record<string, unknown>>;
    }
  }
  return [];
}

function recordFrom(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function countValue(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.max(0, Math.trunc(parsed));
}

function uniqueTextList(...values: unknown[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const items = Array.isArray(value) ? value : [value];
    for (const item of items) {
      const token = normalizeText(item);
      if (!token) {
        continue;
      }
      const key = token.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      out.push(token);
    }
  }
  return out;
}

function statusCountValue(statusCounts: Record<string, unknown>, ...keys: string[]): number {
  return keys.reduce((total, key) => total + countValue(statusCounts[key]), 0);
}

function deriveParserStageStatus(
  documentStatus: unknown,
  processingSnapshot: Record<string, unknown> | null,
  documentProcessing: Record<string, unknown>
): string {
  const explicitStatus = normalizeText(processingSnapshot?.processing_status);
  if (explicitStatus) {
    return explicitStatus;
  }
  if (normalizeText(documentProcessing.parse_error)) {
    return "failed";
  }
  if (normalizeText(documentProcessing.parse_warning)) {
    return "warning";
  }
  const qualityScore = Number(documentProcessing.text_quality_score);
  if (Number.isFinite(qualityScore) && qualityScore < 0.65) {
    return "needs_review";
  }
  const normalized = normalizeText(documentStatus).toLowerCase();
  if (normalized === "failed") {
    return "failed";
  }
  if (["queued", "running", "processing", "importing"].includes(normalized)) {
    return "processing";
  }
  if (["parsed", "indexed", "completed"].includes(normalized)) {
    return "completed";
  }
  return "unknown";
}

function deriveChunkLlmStageStatus(statusCounts: Record<string, unknown>, totalChunks: number): string {
  const completed = statusCountValue(statusCounts, "completed");
  const failed = statusCountValue(statusCounts, "failed");
  const queued = statusCountValue(statusCounts, "queued", "pending", "processing");
  if (totalChunks > 0 && completed >= totalChunks && failed === 0 && queued === 0) {
    return "completed";
  }
  if (failed > 0 && completed === 0 && queued === 0) {
    return "failed";
  }
  if (completed > 0 || queued > 0) {
    return "processing";
  }
  if (failed > 0) {
    return "needs_review";
  }
  return "unknown";
}

function formatPercentValue(value: unknown, digits = 0): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  return `${(parsed * 100).toFixed(digits)}%`;
}

function processingStatusColor(status: string): string {
  if (status === "completed") return "green";
  if (status === "processing" || status === "pending" || status === "queued") return "blue";
  if (status === "warning") return "yellow";
  if (status === "failed") return "red";
  if (status === "needs_review") return "orange";
  return "gray";
}

function processingStatusLabel(status: string): string {
  if (status === "completed") return t("statusCompleted");
  if (status === "processing" || status === "pending" || status === "queued") return t("statusProcessing");
  if (status === "warning") return t("statusWarning");
  if (status === "failed") return t("statusFailed");
  if (status === "needs_review") return t("statusNeedsReview");
  return t("statusUnknown");
}

function activityStatusColor(status: ActivityStatus): string {
  if (status === "completed") return "green";
  if (status === "failed") return "red";
  return "blue";
}

function metricBadgeColor(delta: number): string {
  if (delta > 0) return "green";
  if (delta < 0) return "red";
  return "gray";
}

function formatMetricValue(value: unknown, digits = 4): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  return parsed.toFixed(digits);
}

function formatDeltaValue(value: unknown, digits = 4): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${parsed.toFixed(digits)}`;
}

function metricDeltaLabel(metric: string): string {
  if (metric === "overall_score_delta") return t("metricOverallDelta");
  if (metric === "answer_score_delta") return t("metricAnswerDelta");
  if (metric === "grounding_score_delta") return t("metricGroundingDelta");
  if (metric === "telemetry_delta") return t("metricTelemetryDelta");
  if (metric === "ttft_factor_delta") return t("metricTtftDelta");
  return metric;
}

function hasFullValueReport(report: unknown): boolean {
  const valueReport = (report ?? {}) as Record<string, unknown>;
  return (
    Array.isArray((valueReport as any)?.by_answer_type) &&
    Array.isArray((valueReport as any)?.by_route_family) &&
    Array.isArray((valueReport as any)?.by_answerability) &&
    Array.isArray((valueReport as any)?.by_document_scope) &&
    Array.isArray((valueReport as any)?.by_corpus_domain) &&
    Array.isArray((valueReport as any)?.by_temporal_scope)
  );
}

function extractArtifactId(result: Record<string, unknown>): string {
  const artifactKeys = [
    "job_id",
    "run_id",
    "eval_run_id",
    "gold_dataset_id",
    "profile_id",
    "experiment_id",
    "experiment_run_id",
  ];
  for (const key of artifactKeys) {
    const value = result[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  return "";
}

function formatSessionTimestamp(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function fileLabelFromValue(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "";
  }
  const segments = raw.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] ?? raw;
}

function displayValue(primary: string, secondary?: string): string {
  return primary.trim() || secondary?.trim() || t("notSet");
}

function normalizeText(value: unknown): string {
  return String(value ?? "").trim();
}

function isSyntheticDocumentTitle(value: string): boolean {
  return /^Document [a-f0-9]{10,}$/i.test(value);
}

function documentTypeLabel(docType: unknown): string {
  switch (String(docType ?? "").trim()) {
    case "law":
      return t("docTypeLaw");
    case "regulation":
      return t("docTypeRegulation");
    case "enactment_notice":
      return t("docTypeEnactmentNotice");
    case "case":
      return t("docTypeCase");
    default:
      return t("docTypeOther");
  }
}

function documentReferenceLabel(document: Record<string, unknown> | null): string {
  const lawNumber = normalizeText(document?.law_number);
  if (lawNumber) {
    return lawNumber;
  }
  const caseId = normalizeText(document?.case_id);
  if (caseId && caseId.toLowerCase() !== "no") {
    return caseId;
  }
  return "";
}

function documentYearLabel(document: Record<string, unknown> | null): string {
  const year = Number(document?.year);
  if (Number.isInteger(year) && year > 0) {
    return String(year);
  }
  return "";
}

function documentPageCountLabel(document: Record<string, unknown> | null): string {
  const pageCount = Number(document?.page_count);
  if (Number.isFinite(pageCount) && pageCount > 0) {
    return String(Math.trunc(pageCount));
  }
  return "";
}

function documentDisplayTitle(document: Record<string, unknown> | null): string {
  const candidates = [
    document?.short_title,
    document?.title_raw,
    document?.title_normalized,
    document?.citation_title,
    document?.title,
  ];
  for (const candidate of candidates) {
    const label = normalizeText(candidate);
    if (label && !isSyntheticDocumentTitle(label)) {
      return label;
    }
  }

  const docType = documentTypeLabel(document?.doc_type);
  const reference = documentReferenceLabel(document);
  if (reference) {
    return `${docType} ${reference}`;
  }
  const year = documentYearLabel(document);
  if (year) {
    return `${docType} ${year}`;
  }
  return t("docUntitled");
}

function pageOptionLabel(page: Record<string, unknown>): string {
  const pageNumber = Number(page.page_num);
  const chunkCount = Number(page.chunk_count);
  const base = Number.isFinite(pageNumber) ? `${t("docViewerPageNumber")} ${Math.trunc(pageNumber) + 1}` : t("docViewerPageSelect");
  if (Number.isFinite(chunkCount) && chunkCount > 0) {
    return `${base} (${Math.trunc(chunkCount)} ${t("docViewerChunks")})`;
  }
  return base;
}

function chunkDisplayLabel(chunk: Record<string, unknown>, index: number): string {
  const ordinalRaw = Number(chunk.chunk_index_on_page ?? chunk.paragraph_index);
  const ordinal = Number.isFinite(ordinalRaw) && ordinalRaw >= 0 ? Math.trunc(ordinalRaw) + 1 : index + 1;
  return `${t("chunkCardTitle")} ${ordinal}`;
}

function previewList(values: unknown, limit = 4): string {
  if (!Array.isArray(values) || values.length === 0) {
    return "";
  }
  const items = values
    .map((value) => normalizeText(value))
    .filter(Boolean);
  if (items.length === 0) {
    return "";
  }
  const preview = items.slice(0, limit).join(", ");
  return items.length > limit ? `${preview} +${items.length - limit}` : preview;
}

function truncateText(value: unknown, maxLength = 220): string {
  const text = normalizeText(value);
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength).trimEnd()}...`;
}

function createProjectWorkspace(index: number, overrides: Partial<ProjectWorkspace> = {}): ProjectWorkspace {
  const defaults: ProjectWorkspace = {
    workspaceId: `project-workspace-${index}`,
    label: formatSessionTimestamp(),
    datasetLabel: "",
    corpusLabel: "",
    projectId: "",
    datasetId: "",
    goldDatasetId: "",
    questionId: "",
    questionText: "",
    answerType: "free_text",
    metrics: {
      corpusJobs: 0,
      documents: 0,
      chunks: 0,
      questions: 0,
      warnings: 0,
    },
  };
  return {
    ...defaults,
    ...overrides,
    metrics: {
      ...defaults.metrics,
      ...(overrides.metrics ?? {}),
    },
  };
}

function MetricCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Paper withBorder p="md" className="metric-card">
      <Stack gap={4}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Text fw={700} size="lg">
          {String(value)}
        </Text>
        {hint && (
          <Text size="xs" c="dimmed">
            {hint}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function SectionCard({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Paper withBorder p="md" className="section-card">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={4}>
            <Text fw={700}>{title}</Text>
            {description && (
              <Text size="sm" c="dimmed">
                {description}
              </Text>
            )}
          </Stack>
          {action}
        </Group>
        {children}
      </Stack>
    </Paper>
  );
}

function ValueReportPanel({
  title,
  rows,
  labelField,
  compare = false,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  labelField: string;
  compare?: boolean;
}) {
  return (
    <Paper withBorder p="sm">
      <Stack gap="xs">
        <Text size="sm" fw={700}>
          {title}
        </Text>
        {rows.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("stateEmpty")}
          </Text>
        )}
        {rows.map((row, index) => (
          <Paper key={`${labelField}-${index}`} withBorder p="xs">
            <Group justify="space-between">
              <Text size="sm" fw={600}>
                {String(row[labelField] ?? t("sliceUnknownLabel"))}
              </Text>
              <Badge variant="light">{String(row.question_count ?? 0)}</Badge>
            </Group>
            <SimpleGrid cols={{ base: 2, md: 2 }}>
              {compare ? (
                <>
                  <Text size="xs">{t("metricOverallDelta")}: {formatDeltaValue(row.overall_delta)}</Text>
                  <Text size="xs">{t("metricGroundingDelta")}: {formatDeltaValue(row.grounding_delta)}</Text>
                  <Text size="xs">{t("valueWeightedOverall")}: {formatDeltaValue(row.weighted_overall_delta)}</Text>
                  <Text size="xs">{t("valueWeightedGrounding")}: {formatDeltaValue(row.weighted_grounding_delta)}</Text>
                </>
              ) : (
                <>
                  <Text size="xs">{t("valueCoverageShare")}: {formatMetricValue(row.coverage_share)}</Text>
                  <Text size="xs">{t("metricOverallScore")}: {formatMetricValue(row.current_overall)}</Text>
                  <Text size="xs">{t("valueWeightedOverall")}: {formatMetricValue(row.weighted_current_overall_value)}</Text>
                  <Text size="xs">{t("valueWeightedGrounding")}: {formatMetricValue(row.weighted_grounding_value)}</Text>
                </>
              )}
            </SimpleGrid>
          </Paper>
        ))}
      </Stack>
    </Paper>
  );
}

function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <Paper withBorder p="lg" className="empty-state">
      <Stack gap="xs" align="flex-start">
        <Text fw={700}>{title}</Text>
        <Text size="sm" c="dimmed">
          {description}
        </Text>
        {action}
      </Stack>
    </Paper>
  );
}

function SnapshotRow({ label, value }: { label: string; value: string | number }) {
  return (
    <Group justify="space-between" wrap="nowrap" align="flex-start">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={600} ta="right">
        {String(value)}
      </Text>
    </Group>
  );
}

function StatusBadge({ label, color }: { label: string; color: string }) {
  return (
    <Badge color={color} variant="light">
      {label}
    </Badge>
  );
}

function StageBadge({ label, status }: { label: string; status: string }) {
  return (
    <Badge color={processingStatusColor(status)} variant="light">
      {label}: {processingStatusLabel(status)}
    </Badge>
  );
}

export default function App() {
  const initialProjectWorkspace = createProjectWorkspace(1);
  const [activeSection, setActiveSection] = useState<SectionKey>("projects");
  const [navOpened, setNavOpened] = useState(false);
  const [jobCenterOpened, setJobCenterOpened] = useState(false);
  const [debugOpened, setDebugOpened] = useState(false);
  const [debugTitle, setDebugTitle] = useState(t("debugLastResponse"));
  const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

  const [projectWorkspaces, setProjectWorkspaces] = useState<ProjectWorkspace[]>([initialProjectWorkspace]);
  const [activeProjectWorkspaceId, setActiveProjectWorkspaceId] = useState(initialProjectWorkspace.workspaceId);
  const [lastPayload, setLastPayload] = useState<unknown>(null);
  const [actionStates, setActionStates] = useState<Record<string, ActionState>>({});
  const [activityLog, setActivityLog] = useState<ActivityItem[]>([]);

  const [healthData, setHealthData] = useState<Record<string, unknown> | null>(null);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [processingData, setProcessingData] = useState<Record<string, unknown> | null>(null);
  const [selectedCorpusJobId, setSelectedCorpusJobId] = useState("");
  const [chunkLimit, setChunkLimit] = useState("");
  const [chunkDocumentFilter, setChunkDocumentFilter] = useState("");
  const [chunkData, setChunkData] = useState<Record<string, unknown> | null>(null);
  const [documentsLimit, setDocumentsLimit] = useState("30");
  const [documentTypeFilter, setDocumentTypeFilter] = useState("all");
  const [documentStatusFilter, setDocumentStatusFilter] = useState("all");
  const [documentQualityFilter, setDocumentQualityFilter] = useState("all");
  const [documentsData, setDocumentsData] = useState<Record<string, unknown> | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [documentDetail, setDocumentDetail] = useState<Record<string, unknown> | null>(null);
  const [reingestDocumentId, setReingestDocumentId] = useState("");
  const [selectedPageId, setSelectedPageId] = useState("");
  const [forceLlmReprocess, setForceLlmReprocess] = useState(false);
  const [reclassifyDocumentWithLlm, setReclassifyDocumentWithLlm] = useState(true);

  const [useLlm, setUseLlm] = useState(false);
  const [questionImportLimit, setQuestionImportLimit] = useState("50");
  const [datasetQuestionsData, setDatasetQuestionsData] = useState<Record<string, unknown> | null>(null);

  const [runId, setRunId] = useState("");
  const [runData, setRunData] = useState<Record<string, unknown> | null>(null);
  const [pageIndexBase, setPageIndexBase] = useState<0 | 1>(0);
  const [runQuestionDetailData, setRunQuestionDetailData] = useState<Record<string, unknown> | null>(null);
  const [runQuestionDetailState, setRunQuestionDetailState] = useState<ConsoleViewState>(initialConsoleViewState);
  const [selectedReviewDocumentId, setSelectedReviewDocumentId] = useState("");
  const [selectedReviewPageId, setSelectedReviewPageId] = useState("");

  const [evalRunId, setEvalRunId] = useState("");
  const [evalRunData, setEvalRunData] = useState<Record<string, unknown> | null>(null);
  const [evalReportData, setEvalReportData] = useState<Record<string, unknown> | null>(null);
  const [evalSlicesState, setEvalSlicesState] = useState<ConsoleViewState>(initialConsoleViewState);
  const [compareLeftEvalRunId, setCompareLeftEvalRunId] = useState("");
  const [compareRightEvalRunId, setCompareRightEvalRunId] = useState("");
  const [evalCompareData, setEvalCompareData] = useState<Record<string, unknown> | null>(null);
  const [evalCompareState, setEvalCompareState] = useState<ConsoleViewState>(initialConsoleViewState);

  const [goldDatasetName, setGoldDatasetName] = useState("gold-v1");
  const [goldDatasetVersion, setGoldDatasetVersion] = useState("1.0.0");
  const [canonicalAnswer, setCanonicalAnswer] = useState("sample");
  const [sourcePageIds, setSourcePageIds] = useState("sample_0");

  const [synthJobId, setSynthJobId] = useState("");
  const [synthTargetCount, setSynthTargetCount] = useState("5");

  const [expProfileName, setExpProfileName] = useState("local-main");
  const [expProfileId, setExpProfileId] = useState("");
  const [expListLimit, setExpListLimit] = useState("20");
  const [experimentName, setExperimentName] = useState("baseline-v1");
  const [experimentId, setExperimentId] = useState("");
  const [experimentRunId, setExperimentRunId] = useState("");
  const [experimentStageMode, setExperimentStageMode] = useState("auto");
  const [experimentProxySampleSize, setExperimentProxySampleSize] = useState("80");
  const [compareLeftRunId, setCompareLeftRunId] = useState("");
  const [compareRightRunId, setCompareRightRunId] = useState("");
  const [experimentProfilesData, setExperimentProfilesData] = useState<Record<string, unknown> | null>(null);
  const [experimentData, setExperimentData] = useState<Record<string, unknown> | null>(null);
  const [experimentRunData, setExperimentRunData] = useState<Record<string, unknown> | null>(null);
  const [experimentAnalysisData, setExperimentAnalysisData] = useState<Record<string, unknown> | null>(null);
  const [experimentCompareData, setExperimentCompareData] = useState<Record<string, unknown> | null>(null);
  const [experimentLeaderboardData, setExperimentLeaderboardData] = useState<Record<string, unknown> | null>(null);
  const [experimentCompareState, setExperimentCompareState] = useState<ConsoleViewState>(initialConsoleViewState);

  const [policiesData, setPoliciesData] = useState<Record<string, unknown> | null>(null);

  const activeProjectWorkspace =
    projectWorkspaces.find((workspace) => workspace.workspaceId === activeProjectWorkspaceId) ??
    projectWorkspaces[0] ??
    initialProjectWorkspace;

  const projectId = activeProjectWorkspace.projectId;
  const datasetLabel = activeProjectWorkspace.datasetLabel;
  const corpusLabel = activeProjectWorkspace.corpusLabel;
  const datasetId = activeProjectWorkspace.datasetId;
  const goldDatasetId = activeProjectWorkspace.goldDatasetId;
  const questionId = activeProjectWorkspace.questionId;
  const questionText = activeProjectWorkspace.questionText;
  const answerType = activeProjectWorkspace.answerType;

  const api = useMemo(() => createApi(apiBase), [apiBase]);

  const processingSummary = ((processingData as any)?.summary ?? {}) as Record<string, unknown>;
  const processingStatusCounts = ((processingSummary as any)?.processing_status_counts ?? {}) as Record<string, unknown>;
  const latestJob = ((processingData as any)?.latest_job ?? null) as Record<string, unknown> | null;
  const corpusJobs = arrayFrom(processingData, "jobs");
  const enrichmentJobs = arrayFrom(processingData, "enrichment_jobs");
  const selectedCorpusJob =
    corpusJobs.find((job) => String(job.job_id ?? "") === selectedCorpusJobId) ??
    corpusJobs[0] ??
    null;
  const processingDocumentsAll = arrayFrom(processingData, "processing_documents");
  const processingDocuments = processingDocumentsAll.slice(0, 12);
  const processingDocumentsById = Object.fromEntries(
    processingDocumentsAll.map((doc) => [String(doc.document_id ?? ""), doc])
  ) as Record<string, Record<string, unknown>>;
  const chunkItems = arrayFrom(chunkData, "items");
  const chunkTotal = Number((chunkData as any)?.total ?? chunkItems.length);
  const chunkDocumentCount = new Set(chunkItems.map((item) => String(item.document_id ?? ""))).size;
  const documentsItems = arrayFrom(documentsData, "items");
  const documentTypeFilterOptions = useMemo(() => {
    const values = Array.from(
      new Set(
        documentsItems
          .map((doc) => normalizeText(doc.doc_type).toLowerCase())
          .filter(Boolean)
      )
    ).sort();
    return [
      { value: "all", label: t("docFilterAllTypes") },
      ...values.map((value) => ({
        value,
        label: documentTypeLabel(value),
      })),
    ];
  }, [documentsItems]);
  const documentStatusFilterOptions = useMemo(
    () => [
      { value: "all", label: t("docFilterAllStatuses") },
      { value: "completed", label: processingStatusLabel("completed") },
      { value: "processing", label: processingStatusLabel("processing") },
      { value: "warning", label: processingStatusLabel("warning") },
      { value: "failed", label: processingStatusLabel("failed") },
      { value: "needs_review", label: processingStatusLabel("needs_review") },
      { value: "unknown", label: processingStatusLabel("unknown") },
    ],
    []
  );
  const documentQualityFilterOptions = useMemo(
    () => [
      { value: "all", label: t("docFilterQualityAll") },
      { value: "needs_review", label: t("docFilterQualityNeedsReview") },
      { value: "parse_warning", label: t("docFilterQualityParseWarning") },
      { value: "clean", label: t("docFilterQualityClean") },
    ],
    []
  );
  const filteredDocumentsItems = useMemo(
    () =>
      documentsItems.filter((doc) => {
        const documentId = String(doc.document_id ?? "");
        const processingDoc = processingDocumentsById[documentId] ?? null;
        const parserStatus = deriveParserStageStatus(doc.status, processingDoc, recordFrom(processingDoc));
        const docType = normalizeText(doc.doc_type).toLowerCase();
        const hasParseWarning = Boolean(
          normalizeText(processingDoc?.parse_warning) || normalizeText(processingDoc?.parse_error)
        );
        const textQualityScore = Number(processingDoc?.text_quality_score);
        const lowTextQuality = Number.isFinite(textQualityScore) && textQualityScore < 0.65;
        const needsReview = parserStatus === "needs_review" || hasParseWarning || lowTextQuality;

        if (documentTypeFilter !== "all" && docType !== documentTypeFilter) {
          return false;
        }
        if (documentStatusFilter !== "all" && parserStatus !== documentStatusFilter) {
          return false;
        }
        if (documentQualityFilter === "needs_review" && !needsReview) {
          return false;
        }
        if (documentQualityFilter === "parse_warning" && !hasParseWarning) {
          return false;
        }
        if (documentQualityFilter === "clean" && needsReview) {
          return false;
        }
        return true;
      }),
    [
      documentQualityFilter,
      documentStatusFilter,
      documentTypeFilter,
      documentsItems,
      processingDocumentsById,
    ]
  );
  const datasetQuestionItems = arrayFrom(datasetQuestionsData, "items");
  const datasetQuestionsTotal = Number((datasetQuestionsData as any)?.total ?? datasetQuestionItems.length);
  const documentDetailPages = arrayFrom(documentDetail, "pages");
  const selectedPage = documentDetailPages.find((page) => String(page.page_id ?? "") === selectedPageId) ?? null;
  const selectedPageAssertions = selectedPage && Array.isArray((selectedPage as any).ontology_assertions)
    ? ((selectedPage as any).ontology_assertions as Array<Record<string, unknown>>)
    : [];
  const selectedPageChunks = selectedPage && Array.isArray((selectedPage as any).chunks)
    ? ((selectedPage as any).chunks as Array<Record<string, unknown>>)
    : [];
  const selectedDocumentManifest = (((documentDetail as any)?.document ?? null) as Record<string, unknown> | null);
  const selectedDocumentFileUrl = documentDetail ? joinUrl(apiBase, String((documentDetail as any)?.file_url ?? "")) : "";
  const detailChunkItems = documentDetailPages.flatMap((page) =>
    Array.isArray((page as any).chunks) ? (((page as any).chunks as Array<Record<string, unknown>>)) : []
  );
  const visibleChunkItems = chunkItems.length > 0 ? chunkItems : detailChunkItems;
  const visibleChunkTotal =
    chunkItems.length > 0 || Number.isFinite(Number((chunkData as any)?.total))
      ? chunkTotal
      : visibleChunkItems.length;
  const visibleChunkDocumentCount =
    chunkItems.length > 0
      ? chunkDocumentCount
      : new Set(visibleChunkItems.map((item) => String(item.document_id ?? ""))).size;
  const documentProcessing = recordFrom((documentDetail as any)?.document_processing);
  const documentOntologyView = recordFrom((documentDetail as any)?.document_ontology_view);
  const selectedProcessingDocument =
    (selectedDocumentId ? processingDocumentsById[selectedDocumentId] : null) ??
    (selectedDocumentManifest ? processingDocumentsById[String(selectedDocumentManifest.document_id ?? "")] : null) ??
    null;
  const documentLlmPayload = recordFrom(documentProcessing.llm_document);
  const documentAgenticEnrichment = recordFrom(documentProcessing.agentic_enrichment);
  const documentLlmStatusCounts = recordFrom(((documentDetail as any)?.summary ?? {}).llm_status_counts);
  const documentChunkCount = countValue((documentDetail as any)?.summary?.chunk_count ?? detailChunkItems.length);
  const chunkLlmCompletedCount = statusCountValue(documentLlmStatusCounts, "completed");
  const chunkLlmFailedCount = statusCountValue(documentLlmStatusCounts, "failed");
  const chunkLlmQueuedCount = statusCountValue(documentLlmStatusCounts, "queued", "pending", "processing");
  const parserStageStatus = deriveParserStageStatus(selectedDocumentManifest?.status, selectedProcessingDocument, documentProcessing);
  const chunkLlmStageStatus = deriveChunkLlmStageStatus(documentLlmStatusCounts, documentChunkCount);
  const documentLlmStatus =
    normalizeText(documentProcessing.llm_document_status) ||
    normalizeText(selectedProcessingDocument?.llm_document_status) ||
    "unknown";
  const agenticStageStatus =
    normalizeText(documentAgenticEnrichment.status) ||
    normalizeText(selectedProcessingDocument?.enrichment_status) ||
    "unknown";
  const ontologyAssertionCount = countValue(
    (documentDetail as any)?.summary?.ontology_assertion_count ??
      documentAgenticEnrichment.assertion_count ??
      selectedProcessingDocument?.agent_assertion_count
  );
  const candidateOntologyCount = countValue(
    documentAgenticEnrichment.candidate_entry_count ?? selectedProcessingDocument?.candidate_ontology_count
  );
  const activeOntologyCount = countValue(
    documentAgenticEnrichment.active_entry_count ?? selectedProcessingDocument?.active_ontology_count
  );
  const chunkCoverageValue = formatPercentValue(
    documentAgenticEnrichment.chunk_coverage_ratio ?? selectedProcessingDocument?.agent_chunk_coverage_ratio
  );
  const documentTopicValues = uniqueTextList(
    documentLlmPayload.key_topics,
    documentLlmPayload.tags,
    documentProcessing.tags,
    selectedProcessingDocument?.tags
  );
  const documentEntityValues = uniqueTextList(
    documentLlmPayload.key_entities,
    documentProcessing.entities,
    selectedProcessingDocument?.entities,
    selectedDocumentManifest?.entity_names
  );
  const documentReferenceValues = uniqueTextList(
    documentLlmPayload.article_refs,
    documentLlmPayload.law_refs,
    documentLlmPayload.case_refs,
    selectedProcessingDocument?.article_refs,
    selectedProcessingDocument?.law_refs,
    selectedProcessingDocument?.case_refs
  );
  const ontologyActorValues = uniqueTextList(documentOntologyView.actor_summary);
  const ontologyBeneficiaryValues = uniqueTextList(documentOntologyView.beneficiary_summary);

  const evalMetrics = ((evalRunData as any)?.metrics ?? {}) as Record<string, unknown>;
  const evalSliceSet = ((evalMetrics as any)?.slices ?? {}) as Record<string, unknown>;
  const evalSliceByAnswerType = Array.isArray((evalSliceSet as any)?.by_answer_type)
    ? (((evalSliceSet as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const evalSliceByRouteFamily = Array.isArray((evalSliceSet as any)?.by_route_family)
    ? (((evalSliceSet as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const evalCompareMetricDeltas = ((evalCompareData as any)?.metric_deltas ?? {}) as Record<string, unknown>;
  const evalCompareSlices = ((evalCompareData as any)?.compare_slices ?? {}) as Record<string, unknown>;
  const evalCompareByAnswerType = Array.isArray((evalCompareSlices as any)?.by_answer_type)
    ? (((evalCompareSlices as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const evalCompareByRouteFamily = Array.isArray((evalCompareSlices as any)?.by_route_family)
    ? (((evalCompareSlices as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const evalCompareQuestionDeltas = Array.isArray((evalCompareData as any)?.question_deltas)
    ? (((evalCompareData as any).question_deltas as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueReport = (((evalCompareData as any)?.value_report ?? {}) as Record<string, unknown>);
  const evalCompareValueByAnswerType = Array.isArray((evalCompareValueReport as any)?.by_answer_type)
    ? (((evalCompareValueReport as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueByRouteFamily = Array.isArray((evalCompareValueReport as any)?.by_route_family)
    ? (((evalCompareValueReport as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueByAnswerability = Array.isArray((evalCompareValueReport as any)?.by_answerability)
    ? (((evalCompareValueReport as any).by_answerability as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueByDocumentScope = Array.isArray((evalCompareValueReport as any)?.by_document_scope)
    ? (((evalCompareValueReport as any).by_document_scope as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueByCorpusDomain = Array.isArray((evalCompareValueReport as any)?.by_corpus_domain)
    ? (((evalCompareValueReport as any).by_corpus_domain as Array<Record<string, unknown>>))
    : [];
  const evalCompareValueByTemporalScope = Array.isArray((evalCompareValueReport as any)?.by_temporal_scope)
    ? (((evalCompareValueReport as any).by_temporal_scope as Array<Record<string, unknown>>))
    : [];
  const evalReportItems = arrayFrom(evalReportData, "items");
  const evalValueReport = (((evalMetrics as any)?.value_report ?? (evalReportData as any)?.value_report) ?? {}) as Record<
    string,
    unknown
  >;
  const evalValueByRouteFamily = Array.isArray((evalValueReport as any)?.by_route_family)
    ? (((evalValueReport as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const evalValueByAnswerType = Array.isArray((evalValueReport as any)?.by_answer_type)
    ? (((evalValueReport as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const evalValueByAnswerability = Array.isArray((evalValueReport as any)?.by_answerability)
    ? (((evalValueReport as any).by_answerability as Array<Record<string, unknown>>))
    : [];
  const evalValueByDocumentScope = Array.isArray((evalValueReport as any)?.by_document_scope)
    ? (((evalValueReport as any).by_document_scope as Array<Record<string, unknown>>))
    : [];
  const evalValueByCorpusDomain = Array.isArray((evalValueReport as any)?.by_corpus_domain)
    ? (((evalValueReport as any).by_corpus_domain as Array<Record<string, unknown>>))
    : [];
  const evalValueByTemporalScope = Array.isArray((evalValueReport as any)?.by_temporal_scope)
    ? (((evalValueReport as any).by_temporal_scope as Array<Record<string, unknown>>))
    : [];
  const evalTopRegressions = [...evalReportItems]
    .sort(
      (left, right) =>
        Number((left.overall_score ?? left.overall_proxy) ?? 0) - Number((right.overall_score ?? right.overall_proxy) ?? 0)
    )
    .slice(0, 5);
  const evalCompareTopRegressions = [...evalCompareQuestionDeltas]
    .sort((left, right) => Number(left.delta ?? 0) - Number(right.delta ?? 0))
    .slice(0, 5);

  const reviewEvidence = ((runQuestionDetailData as any)?.evidence ?? {}) as Record<string, unknown>;
  const reviewViewer = ((runQuestionDetailData as any)?.document_viewer ?? {}) as Record<string, unknown>;
  const reviewDocuments = arrayFrom(reviewViewer as Record<string, unknown>, "documents");
  const selectedReviewDocument =
    reviewDocuments.find((doc) => String(doc.document_id ?? "") === selectedReviewDocumentId) ??
    reviewDocuments[0] ??
    null;
  const selectedReviewPages = selectedReviewDocument && Array.isArray((selectedReviewDocument as any).pages)
    ? (((selectedReviewDocument as any).pages as Array<Record<string, unknown>>))
    : [];
  const selectedReviewPage =
    selectedReviewPages.find((page) => String(page.page_id ?? "") === selectedReviewPageId) ??
    selectedReviewPages.find((page) => Boolean(page.used)) ??
    selectedReviewPages[0] ??
    null;
  const selectedReviewPdfSrc = selectedReviewDocument
    ? joinUrl(apiBase, String((selectedReviewDocument as any).file_url ?? ""))
    : "";

  const experimentProfiles = arrayFrom(experimentProfilesData, "items", "profiles");
  const experimentLeaderboard = arrayFrom(experimentLeaderboardData, "items", "results");
  const experimentMetricDeltas = ((experimentCompareData as any)?.metric_deltas ?? {}) as Record<string, unknown>;
  const experimentCompareSlices = ((experimentCompareData as any)?.compare_slices ?? {}) as Record<string, unknown>;
  const experimentCompareByAnswerType = Array.isArray((experimentCompareSlices as any)?.by_answer_type)
    ? (((experimentCompareSlices as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const experimentCompareByRouteFamily = Array.isArray((experimentCompareSlices as any)?.by_route_family)
    ? (((experimentCompareSlices as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const experimentQuestionDeltas = Array.isArray((experimentCompareData as any)?.question_deltas)
    ? (((experimentCompareData as any).question_deltas as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueReport = (((experimentCompareData as any)?.value_report ?? {}) as Record<string, unknown>);
  const experimentCompareValueByAnswerType = Array.isArray((experimentCompareValueReport as any)?.by_answer_type)
    ? (((experimentCompareValueReport as any).by_answer_type as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueByRouteFamily = Array.isArray((experimentCompareValueReport as any)?.by_route_family)
    ? (((experimentCompareValueReport as any).by_route_family as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueByAnswerability = Array.isArray((experimentCompareValueReport as any)?.by_answerability)
    ? (((experimentCompareValueReport as any).by_answerability as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueByDocumentScope = Array.isArray((experimentCompareValueReport as any)?.by_document_scope)
    ? (((experimentCompareValueReport as any).by_document_scope as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueByCorpusDomain = Array.isArray((experimentCompareValueReport as any)?.by_corpus_domain)
    ? (((experimentCompareValueReport as any).by_corpus_domain as Array<Record<string, unknown>>))
    : [];
  const experimentCompareValueByTemporalScope = Array.isArray((experimentCompareValueReport as any)?.by_temporal_scope)
    ? (((experimentCompareValueReport as any).by_temporal_scope as Array<Record<string, unknown>>))
    : [];
  const experimentTopRegressions = [...experimentQuestionDeltas]
    .sort((left, right) => Number(left.delta ?? 0) - Number(right.delta ?? 0))
    .slice(0, 5);

  const processingResultsLoading = Boolean(actionStates.processingResults?.loading);
  const documentsLoading = Boolean(actionStates.loadDocuments?.loading);
  const processingSummaryDocuments = Number(processingSummary.documents);
  const documentsTotal = Number((documentsData as any)?.total ?? documentsItems.length);
  const resolvedDocumentsCount =
    Number.isFinite(processingSummaryDocuments) && processingSummaryDocuments >= 0
      ? Math.trunc(processingSummaryDocuments)
      : Number.isFinite(documentsTotal) && documentsTotal >= 0
        ? Math.trunc(documentsTotal)
        : documentsItems.length;

  const qualityValues = processingDocumentsAll
    .map((doc) => Number(doc.text_quality_score))
    .filter((value) => Number.isFinite(value));
  const qualityAverage = qualityValues.length > 0
    ? qualityValues.reduce((acc, value) => acc + value, 0) / qualityValues.length
    : null;
  const parseWarningsCount = processingDocumentsAll.filter((doc) => Boolean(doc.parse_warning)).length;
  const parseErrorsCount = processingDocumentsAll.filter((doc) => Boolean(doc.parse_error)).length;
  const ontologyTagPool = Array.from(
    new Set(
      processingDocumentsAll.flatMap((doc) =>
        Array.isArray(doc.tags) ? (doc.tags as Array<unknown>).map((v) => String(v)) : []
      )
    )
  ).slice(0, 12);
  const docTypeRows = Object.entries((processingSummary.by_doc_type as Record<string, unknown>) ?? {}).map(
    ([docType, count]) => ({
      docType,
      count: Number(count) || 0,
    })
  );

  function applyProcessingResults(result: Record<string, unknown>): void {
    setProcessingData(result);
    const jobs = arrayFrom(result, "jobs");
    if (jobs.length > 0) {
      setSelectedCorpusJobId((current) => current.trim() || String(jobs[0].job_id ?? ""));
    }
    const latestCorpusLabel = fileLabelFromValue((result as any)?.latest_job?.blob_url ?? jobs[0]?.blob_url ?? zipFile?.name ?? "");
    if (latestCorpusLabel) {
      updateActiveProjectWorkspace({ corpusLabel: latestCorpusLabel });
    }
  }

  function applyDocumentsResult(result: Record<string, unknown>): void {
    setDocumentsData(result);
  }

  useEffect(() => {
    const nextMetrics: ProjectWorkspaceMetrics = {
      corpusJobs: corpusJobs.length,
      documents: resolvedDocumentsCount,
      chunks: chunkTotal,
      questions: datasetQuestionsTotal,
      warnings: parseWarningsCount,
    };

    setProjectWorkspaces((current) =>
      current.map((workspace) => {
        if (workspace.workspaceId !== activeProjectWorkspace.workspaceId) {
          return workspace;
        }
        if (
          workspace.metrics.corpusJobs === nextMetrics.corpusJobs &&
          workspace.metrics.documents === nextMetrics.documents &&
          workspace.metrics.chunks === nextMetrics.chunks &&
          workspace.metrics.questions === nextMetrics.questions &&
          workspace.metrics.warnings === nextMetrics.warnings
        ) {
          return workspace;
        }
        return {
          ...workspace,
          metrics: nextMetrics,
        };
      })
    );
  }, [
    activeProjectWorkspace.workspaceId,
    chunkTotal,
    corpusJobs.length,
    datasetQuestionsTotal,
    resolvedDocumentsCount,
    parseWarningsCount,
  ]);

  useEffect(() => {
    if (activeSection !== "corpus" || processingData || processingResultsLoading) {
      return;
    }

    void (async () => {
      try {
        const result = await api.processingResults();
        applyProcessingResults(result);
      } catch {
        // Keep the corpus screen quiet on initial load; the explicit button still surfaces errors.
      }
    })();
  }, [activeSection, api, processingData, processingResultsLoading]);

  useEffect(() => {
    if (activeSection !== "corpus" || documentsData || documentsLoading) {
      return;
    }
    if (corpusJobs.length === 0 && (!Number.isFinite(processingSummaryDocuments) || processingSummaryDocuments <= 0)) {
      return;
    }

    void (async () => {
      try {
        const parsedLimit = documentsLimit.trim().length > 0 ? Number(documentsLimit) : undefined;
        const result = await api.listDocuments(
          undefined,
          parsedLimit === undefined ? undefined : Math.trunc(parsedLimit)
        );
        applyDocumentsResult(result);
      } catch {
        // Keep the corpus screen quiet on initial load; the explicit button still surfaces errors.
      }
    })();
  }, [activeSection, api, corpusJobs.length, documentsData, documentsLimit, documentsLoading, processingSummaryDocuments]);

  function setActionState(key: string, patch: Partial<ActionState>): void {
    setActionStates((current) => ({
      ...current,
      [key]: {
        ...(current[key] ?? {}),
        loading: false,
        error: "",
        ...patch,
      },
    }));
  }

  function isActionLoading(key: string): boolean {
    return Boolean(actionStates[key]?.loading);
  }

  function openDebug(title: string, payload: unknown): void {
    setDebugTitle(title);
    setLastPayload(payload);
    setDebugOpened(true);
  }

  async function runTracked<T extends Record<string, unknown>>(
    key: string,
    label: string,
    fn: () => Promise<T>,
    options?: {
      successMessage?: string;
      onSuccess?: (result: T) => void | Promise<void>;
    }
  ): Promise<T | null> {
    const activityId = `${key}-${Date.now()}`;
    setActionState(key, { loading: true, error: "" });
    setJobCenterOpened(true);
    setActivityLog((current) => [
      {
        id: activityId,
        label,
        status: "processing" as ActivityStatus,
        timestamp: Date.now(),
      },
      ...current,
    ].slice(0, 24));

    try {
      const result = await fn();
      setLastPayload(result);
      setDebugTitle(label);
      await options?.onSuccess?.(result);
      const artifactId = extractArtifactId(result);
      setActivityLog((current) =>
        current.map((item) =>
          item.id === activityId
            ? {
                ...item,
                status: "completed",
                artifactId,
              }
            : item
        )
      );
      notifications.show({
        color: "green",
        message: options?.successMessage ?? t("stateSuccess"),
      });
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setLastPayload({ error: message });
      setDebugTitle(label);
      setActionState(key, { error: message });
      setActivityLog((current) =>
        current.map((item) =>
          item.id === activityId
            ? {
                ...item,
                status: "failed",
                detail: message,
              }
            : item
        )
      );
      notifications.show({ color: "red", message: message.slice(0, 180) });
      return null;
    } finally {
      setActionState(key, { loading: false });
    }
  }

  function updateProjectWorkspace(workspaceId: string, patch: Partial<ProjectWorkspace>): void {
    setProjectWorkspaces((current) =>
      current.map((workspace) => {
        if (workspace.workspaceId !== workspaceId) {
          return workspace;
        }
        return {
          ...workspace,
          ...patch,
          metrics: {
            ...workspace.metrics,
            ...(patch.metrics ?? {}),
          },
        };
      })
    );
  }

  function updateActiveProjectWorkspace(patch: Partial<ProjectWorkspace>): void {
    updateProjectWorkspace(activeProjectWorkspace.workspaceId, patch);
  }

  function addProjectWorkspace(): void {
    const nextWorkspace = createProjectWorkspace(projectWorkspaces.length + 1);
    setProjectWorkspaces((current) => [...current, nextWorkspace]);
    setActiveProjectWorkspaceId(nextWorkspace.workspaceId);
  }

  function setActiveProjectId(value: string): void {
    updateActiveProjectWorkspace({ projectId: value });
    setProcessingData(null);
    setChunkData(null);
    setDocumentsData(null);
    setDocumentDetail(null);
    setSelectedCorpusJobId("");
    setSelectedDocumentId("");
    setSelectedPageId("");
  }

  function setActiveDatasetId(value: string): void {
    updateActiveProjectWorkspace({ datasetId: value });
    setDatasetQuestionsData(null);
  }

  function setActiveDatasetLabel(value: string): void {
    updateActiveProjectWorkspace({ datasetLabel: value });
  }

  function handleZipFileChange(file: File | null): void {
    setZipFile(file);
    if (file) {
      updateActiveProjectWorkspace({ corpusLabel: file.name });
    }
  }

  function setActiveGoldDatasetId(value: string): void {
    updateActiveProjectWorkspace({ goldDatasetId: value });
  }

  function navigate(section: SectionKey): void {
    setActiveSection(section);
    setNavOpened(false);
  }

  async function importCorpusZip(): Promise<void> {
    if (!zipFile) {
      notifications.show({ color: "red", message: t("errZipFileRequired") });
      return;
    }

    const form = new FormData();
    form.append("parse_policy", "balanced");
    form.append("dedupe_enabled", "true");
    form.append("file", zipFile);

    const result = await runTracked("importCorpus", t("actionImport"), () => api.importZipUpload(form), {
      onSuccess: () => {
        if (zipFile?.name) {
          updateActiveProjectWorkspace({ corpusLabel: zipFile.name });
        }
      },
    });
    if (!result) {
      return;
    }

    try {
      const processingResult = await api.processingResults();
      applyProcessingResults(processingResult);
      const parsedLimit = documentsLimit.trim().length > 0 ? Number(documentsLimit) : undefined;
      const documentsResult = await api.listDocuments(
        undefined,
        parsedLimit === undefined ? undefined : Math.trunc(parsedLimit)
      );
      applyDocumentsResult(documentsResult);
    } catch {
      // Keep the successful import notification; the explicit refresh controls remain available.
    }
  }

  async function loadHealth(): Promise<void> {
    await runTracked("health", t("actionPing"), () => api.health(), {
      onSuccess: (result) => setHealthData(result),
    });
  }

  async function loadProcessingResults(): Promise<void> {
    await runTracked("processingResults", t("actionLoadProcessingResults"), () => api.processingResults(), {
      onSuccess: (result) => {
        applyProcessingResults(result);
      },
    });
  }

  async function loadChunks(): Promise<void> {
    const parsedLimit = chunkLimit.trim().length > 0 ? Number(chunkLimit) : undefined;
    if (parsedLimit !== undefined && (!Number.isFinite(parsedLimit) || parsedLimit <= 0)) {
      notifications.show({ color: "red", message: t("errChunkLimitInvalid") });
      return;
    }

    await runTracked("loadChunks", t("actionLoadChunks"), () =>
      api.listChunks(undefined, chunkDocumentFilter.trim() || undefined, parsedLimit === undefined ? undefined : Math.trunc(parsedLimit)), {
      onSuccess: (result) => setChunkData(result),
    });
  }

  async function loadDocuments(): Promise<void> {
    const parsedLimit = documentsLimit.trim().length > 0 ? Number(documentsLimit) : undefined;
    await runTracked("loadDocuments", t("actionLoadDocuments"), () =>
      api.listDocuments(undefined, parsedLimit === undefined ? undefined : Math.trunc(parsedLimit)), {
      onSuccess: (result) => applyDocumentsResult(result),
    });
  }

  async function openDocument(documentId: string): Promise<void> {
    const normalizedDocumentId = documentId.trim();
    if (!normalizedDocumentId) {
      return;
    }

    setActionState("openDocument", { loading: true, error: "" });
    try {
      const result = await api.getDocumentDetail(normalizedDocumentId);
      setSelectedDocumentId(normalizedDocumentId);
      setDocumentDetail(result);
      const pages = arrayFrom(result, "pages");
      setSelectedPageId(pages.length > 0 ? String(pages[0].page_id ?? "") : "");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setActionState("openDocument", { error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    } finally {
      setActionState("openDocument", { loading: false });
    }
  }

  async function reingestDocument(documentId: string): Promise<void> {
    const normalizedDocumentId = documentId.trim();
    if (!normalizedDocumentId) {
      return;
    }

    setReingestDocumentId(normalizedDocumentId);
    const result = await runTracked("reingestDocument", t("actionReingestDocument"), () =>
      api.reingestDocument(normalizedDocumentId)
    );
    if (!result) {
      setReingestDocumentId("");
      return;
    }

    try {
      const processingResult = await api.processingResults();
      applyProcessingResults(processingResult);
      const parsedLimit = documentsLimit.trim().length > 0 ? Number(documentsLimit) : undefined;
      const documentsResult = await api.listDocuments(
        undefined,
        parsedLimit === undefined ? undefined : Math.trunc(parsedLimit)
      );
      applyDocumentsResult(documentsResult);
      if (selectedDocumentId === normalizedDocumentId) {
        await openDocument(normalizedDocumentId);
      }
    } catch {
      // Re-ingest request succeeded; keep refresh failures non-blocking.
    } finally {
      setReingestDocumentId("");
    }
  }

  async function runDocumentLlm(): Promise<void> {
    if (!selectedDocumentId) {
      notifications.show({ color: "red", message: t("noDocumentSelected") });
      return;
    }

    await runTracked("runDocumentLlm", t("actionRunDocumentLlm"), () =>
      api.processDocumentChunksLlm(selectedDocumentId, {
        force: forceLlmReprocess,
        reclassify_document: reclassifyDocumentWithLlm,
      }), {
      onSuccess: async () => {
        await openDocument(selectedDocumentId);
      },
    });
  }

  async function importQuestions(): Promise<void> {
    await runTracked("importQuestions", t("actionImportPublicQuestions"), () =>
      api.importQuestions(datasetId, {
        project_id: projectId,
        source: "public_dataset",
        limit: Number(questionImportLimit) || 50,
      }));
  }

  async function loadDatasetQuestions(): Promise<void> {
    await runTracked("listQuestions", t("actionListImportedQuestions"), () => api.listDatasetQuestions(datasetId, Number(questionImportLimit) || 50), {
      onSuccess: (result) => setDatasetQuestionsData(result),
    });
  }

  async function askSingle(): Promise<void> {
    await runTracked("askSingle", t("actionAsk"), () =>
      api.ask({
        project_id: projectId,
        question: {
          id: questionId,
          question: questionText,
          answer_type: answerType,
          tags: ["ui"],
        },
        runtime_policy: defaultRuntimePolicy(useLlm),
      }));
  }

  async function askBatch(): Promise<void> {
    await runTracked("askBatch", t("actionRunBatch"), () =>
      api.askBatch({
        project_id: projectId,
        dataset_id: datasetId,
        question_ids: questionId ? [questionId] : [],
        runtime_policy: defaultRuntimePolicy(useLlm),
      }), {
      onSuccess: (result) => {
        if ((result as any)?.run_id) {
          setRunId(String((result as any).run_id));
        }
      },
    });
  }

  async function loadRun(): Promise<void> {
    await runTracked("getRun", t("actionGetRun"), () => api.getRun(runId), {
      onSuccess: (result) => setRunData(result),
    });
  }

  async function exportSubmission(): Promise<void> {
    await runTracked("exportSubmission", t("actionExportSubmission"), () =>
      api.exportSubmission(runId, { page_index_base: pageIndexBase }));
  }

  async function loadRunQuestionDetail(): Promise<void> {
    setRunQuestionDetailState({ loading: true, partial: "", error: "" });
    try {
      const result = await api.getRunQuestionDetail(runId, questionId);
      setRunQuestionDetailData(result);
      const documents = arrayFrom((result as any)?.document_viewer ?? {}, "documents");
      const defaultDocumentId = String((result as any)?.document_viewer?.default_document_id ?? documents[0]?.document_id ?? "");
      const selectedDoc =
        documents.find((doc) => String(doc.document_id ?? "") === defaultDocumentId) ??
        documents[0] ??
        null;
      const selectedPages = selectedDoc && Array.isArray((selectedDoc as any).pages)
        ? (((selectedDoc as any).pages as Array<Record<string, unknown>>))
        : [];
      const defaultPageId = String((result as any)?.document_viewer?.default_page_id ?? selectedPages[0]?.page_id ?? "");
      setSelectedReviewDocumentId(defaultDocumentId);
      setSelectedReviewPageId(defaultPageId);
      setRunQuestionDetailState({ loading: false, partial: "", error: "" });
      setLastPayload(result);
      setDebugTitle(t("reviewDebugTitle"));
      setJobCenterOpened(true);
      setActivityLog((current) => [
        {
          id: `review-${Date.now()}`,
          label: t("actionLoadRunQuestionReview"),
          status: "completed" as ActivityStatus,
          timestamp: Date.now(),
          artifactId: runId,
        },
        ...current,
      ].slice(0, 24));
      notifications.show({ color: "green", message: t("stateSuccess") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRunQuestionDetailState({ loading: false, partial: "", error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function promoteRunQuestionToGold(): Promise<void> {
    await runTracked("promoteGold", t("actionPromoteToGold"), () =>
      api.promoteRunQuestionToGold(runId, questionId, {
        gold_dataset_id: goldDatasetId,
      }));
  }

  async function createEvalRun(): Promise<void> {
    await runTracked("createEvalRun", t("actionCreateEvalRun"), () =>
      api.createEvalRun({
        run_id: runId,
        gold_dataset_id: goldDatasetId,
        scoring_policy_version: "contest_v2026_public_rules_v1",
        judge_policy_version: "judge_v1",
      }), {
      onSuccess: (result) => {
        if ((result as any)?.eval_run_id) {
          setEvalRunId(String((result as any).eval_run_id));
        }
      },
    });
  }

  async function loadEvalRunConsoleView(): Promise<void> {
    setEvalSlicesState({ loading: true, partial: "", error: "" });
    try {
      const result = await api.getEvalRun(evalRunId);
      setEvalRunData(result);
      const slices = (result as any)?.metrics?.slices;
      const valueReport = (result as any)?.metrics?.value_report;
      const hasExpectedSlices =
        Boolean(slices) &&
        Array.isArray((slices as any)?.by_answer_type) &&
        Array.isArray((slices as any)?.by_route_family);
      const hasValueReport = hasFullValueReport(valueReport);
      setEvalSlicesState({
        loading: false,
        partial: hasExpectedSlices && hasValueReport ? "" : t("consoleScorerPartial"),
        error: "",
      });
      setLastPayload(result);
      setDebugTitle(t("evaluationDebugTitle"));
      notifications.show({ color: "green", message: t("stateSuccess") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setEvalSlicesState({ loading: false, partial: "", error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function loadEvalReportConsoleView(): Promise<void> {
    setEvalSlicesState((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const result = await api.getEvalReport(evalRunId);
      setEvalReportData(result);
      const hasItems = Array.isArray((result as any)?.items);
      const hasValueReport = hasFullValueReport((result as any)?.value_report ?? (evalRunData as any)?.metrics?.value_report);
      setEvalSlicesState((prev) => ({
        ...prev,
        loading: false,
        partial: hasItems && hasValueReport ? prev.partial : t("consoleScorerReportPartial"),
        error: "",
      }));
      setLastPayload(result);
      setDebugTitle(t("evaluationDebugTitle"));
      notifications.show({ color: "green", message: t("stateSuccess") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setEvalSlicesState((prev) => ({ ...prev, loading: false, error: message }));
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function loadEvalCompareConsoleView(): Promise<void> {
    setEvalCompareState({ loading: true, partial: "", error: "" });
    try {
      const result = await api.compareEvalRuns({
        left_eval_run_id: compareLeftEvalRunId,
        right_eval_run_id: compareRightEvalRunId,
      });
      setEvalCompareData(result);
      const slices = (result as any)?.compare_slices;
      const valueReport = (result as any)?.value_report;
      const hasQuestionDeltas = Array.isArray((result as any)?.question_deltas);
      const hasExpectedPayload =
        Boolean(slices) &&
        Array.isArray((slices as any)?.by_answer_type) &&
        Array.isArray((slices as any)?.by_route_family) &&
        hasQuestionDeltas &&
        hasFullValueReport(valueReport);
      setEvalCompareState({
        loading: false,
        partial: hasExpectedPayload ? "" : t("consoleComparePartial"),
        error: "",
      });
      setLastPayload(result);
      setDebugTitle(t("evaluationDebugTitle"));
      notifications.show({ color: "green", message: t("stateSuccess") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setEvalCompareState({ loading: false, partial: "", error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function createExperimentProfile(): Promise<void> {
    await runTracked("createExperimentProfile", t("actionCreateExperimentProfile"), () =>
      api.createExperimentProfile({
        name: expProfileName,
        project_id: projectId,
        dataset_id: datasetId,
        gold_dataset_id: goldDatasetId,
        endpoint_target: "local",
        active: true,
      }), {
      onSuccess: (result) => {
        if ((result as any)?.profile_id) {
          setExpProfileId(String((result as any).profile_id));
        }
      },
    });
  }

  async function listExperimentProfiles(): Promise<void> {
    await runTracked("listExperimentProfiles", t("actionListExperimentProfiles"), () =>
      api.listExperimentProfiles(Number(expListLimit) || 20), {
      onSuccess: (result) => setExperimentProfilesData(result),
    });
  }

  async function createExperiment(): Promise<void> {
    await runTracked("createExperiment", t("actionCreateExperiment"), () =>
      api.createExperiment({
        name: experimentName,
        profile_id: expProfileId,
        gold_dataset_id: goldDatasetId,
      }), {
      onSuccess: (result) => {
        setExperimentData(result);
        if ((result as any)?.experiment_id) {
          setExperimentId(String((result as any).experiment_id));
        }
      },
    });
  }

  async function getExperiment(): Promise<void> {
    await runTracked("getExperiment", t("actionGetExperiment"), () => api.getExperiment(experimentId), {
      onSuccess: (result) => setExperimentData(result),
    });
  }

  async function runExperiment(): Promise<void> {
    await runTracked("runExperiment", t("actionRunExperiment"), () =>
      api.runExperiment(experimentId, {
        stage_mode: experimentStageMode,
        proxy_sample_size:
          experimentProxySampleSize.trim().length > 0 ? Number(experimentProxySampleSize) : undefined,
        actor: "ui",
        agent_mode: false,
      }), {
      onSuccess: (result) => {
        if ((result as any)?.experiment_run_id) {
          setExperimentRunId(String((result as any).experiment_run_id));
        }
      },
    });
  }

  async function getExperimentRun(): Promise<void> {
    await runTracked("getExperimentRun", t("actionGetExperimentRun"), () => api.getExperimentRun(experimentRunId), {
      onSuccess: (result) => setExperimentRunData(result),
    });
  }

  async function getExperimentAnalysis(): Promise<void> {
    await runTracked("getExperimentAnalysis", t("actionGetExperimentAnalysis"), () => api.getExperimentRunAnalysis(experimentRunId), {
      onSuccess: (result) => setExperimentAnalysisData(result),
    });
  }

  async function loadExperimentCompareConsoleView(): Promise<void> {
    setExperimentCompareState({ loading: true, partial: "", error: "" });
    try {
      const result = await api.compareExperimentRuns({
        left_experiment_run_id: compareLeftRunId,
        right_experiment_run_id: compareRightRunId,
      });
      setExperimentCompareData(result);
      const slices = (result as any)?.compare_slices;
      const hasSliceArrays =
        Boolean(slices) &&
        Array.isArray((slices as any)?.by_answer_type) &&
        Array.isArray((slices as any)?.by_route_family);
      const hasQuestionDeltas = Array.isArray((result as any)?.question_deltas);
      const valueReport = (result as any)?.value_report;
      const hasValueReport =
        Boolean(valueReport) &&
        Array.isArray((valueReport as any)?.by_answer_type) &&
        Array.isArray((valueReport as any)?.by_route_family) &&
        Array.isArray((valueReport as any)?.by_answerability) &&
        Array.isArray((valueReport as any)?.by_document_scope) &&
        Array.isArray((valueReport as any)?.by_corpus_domain) &&
        Array.isArray((valueReport as any)?.by_temporal_scope);
      setExperimentCompareState({
        loading: false,
        partial: hasSliceArrays && hasQuestionDeltas && hasValueReport ? "" : t("consoleComparePartial"),
        error: "",
      });
      setLastPayload(result);
      setDebugTitle(t("experimentsDebugTitle"));
      notifications.show({ color: "green", message: t("stateSuccess") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setExperimentCompareState({ loading: false, partial: "", error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function loadExperimentLeaderboard(): Promise<void> {
    await runTracked("getLeaderboard", t("actionGetLeaderboard"), () =>
      api.getExperimentLeaderboard(Number(expListLimit) || 20, "full", experimentId || undefined), {
      onSuccess: (result) => setExperimentLeaderboardData(result),
    });
  }

  async function createGoldDataset(): Promise<void> {
    await runTracked("createGoldDataset", t("actionCreateGoldDataset"), () =>
      api.createGoldDataset({
        project_id: projectId,
        name: goldDatasetName,
        version: goldDatasetVersion,
      }), {
      onSuccess: (result) => {
        if ((result as any)?.gold_dataset_id) {
          setActiveGoldDatasetId(String((result as any).gold_dataset_id));
        }
      },
    });
  }

  async function createGoldQuestion(): Promise<void> {
    await runTracked("createGoldQuestion", t("actionCreateGoldQuestion"), () =>
      api.createGoldQuestion(goldDatasetId, {
        question_id: questionId,
        canonical_answer: canonicalAnswer,
        answer_type: answerType,
        source_sets: [
          {
            source_set_id: "11111111-1111-1111-1111-111111111111",
            is_primary: true,
            page_ids: sourcePageIds.split(",").map((value) => value.trim()).filter(Boolean),
            notes: "from-ui",
          },
        ],
      }));
  }

  async function lockGoldDataset(): Promise<void> {
    await runTracked("lockGoldDataset", t("actionLockGoldDataset"), () => api.lockGoldDataset(goldDatasetId));
  }

  async function exportGoldDataset(): Promise<void> {
    await runTracked("exportGoldDataset", t("actionExportGoldDataset"), () => api.exportGoldDataset(goldDatasetId));
  }

  async function createSynthJob(): Promise<void> {
    await runTracked("createSynthJob", t("actionCreateSynthJob"), () =>
      api.createSynthJob({
        job_id: "00000000-0000-0000-0000-000000000000",
        project_id: projectId,
        status: "queued",
        source_scope: { document_ids: [], doc_types: [] },
        generation_policy: {
          target_count: Number(synthTargetCount) || 5,
          answer_type_mix: { free_text: 1 },
          route_mix: { article_lookup: 1 },
          adversarial_ratio: 0,
          paraphrase_ratio: 0,
          require_human_review: true,
        },
      }), {
      onSuccess: (result) => {
        if ((result as any)?.job_id) {
          setSynthJobId(String((result as any).job_id));
        }
      },
    });
  }

  async function previewSynth(): Promise<void> {
    await runTracked("previewSynth", t("actionPreviewSynth"), () => api.previewSynth(synthJobId, { limit: 20 }));
  }

  async function publishSynth(): Promise<void> {
    await runTracked("publishSynth", t("actionPublishSynth"), () => api.publishSynth(synthJobId, {}));
  }

  async function loadPolicies(): Promise<void> {
    await runTracked("listPolicies", t("actionListPolicies"), () => api.listPolicies(), {
      onSuccess: (result) => setPoliciesData(result),
    });
  }

  const validationItems: ValidationItem[] = [];
  if (!projectId.trim()) {
    validationItems.push({
      id: "project-missing",
      level: "error",
      title: t("validationProjectMissingTitle"),
      detail: t("validationProjectMissingDetail"),
    });
  }
  if (!datasetId.trim()) {
    validationItems.push({
      id: "dataset-missing",
      level: "warning",
      title: t("validationDatasetMissingTitle"),
      detail: t("validationDatasetMissingDetail"),
    });
  }
  if (!goldDatasetId.trim()) {
    validationItems.push({
      id: "gold-missing",
      level: "warning",
      title: t("validationGoldMissingTitle"),
      detail: t("validationGoldMissingDetail"),
    });
  }
  if (corpusJobs.length === 0) {
    validationItems.push({
      id: "corpus-missing",
      level: "warning",
      title: t("validationCorpusMissingTitle"),
      detail: t("validationCorpusMissingDetail"),
    });
  }
  if (runId.trim() && !evalRunId.trim()) {
    validationItems.push({
      id: "eval-needed",
      level: "success",
      title: t("validationEvalNeededTitle"),
      detail: t("validationEvalNeededDetail"),
    });
  }

  const readinessLabel = validationItems.some((item) => item.level === "error")
    ? t("readinessBlocked")
    : !runId.trim()
      ? t("readinessReview")
      : !evalRunId.trim()
        ? t("readinessEval")
        : t("readinessReady");

  const readinessColor = validationItems.some((item) => item.level === "error")
    ? "red"
    : !runId.trim()
      ? "yellow"
      : !evalRunId.trim()
        ? "blue"
        : "green";

  const recommendedActions = [
    !projectId.trim() ? { label: t("nextActionConfigureProject"), section: "projects" as SectionKey } : null,
    corpusJobs.length === 0 ? { label: t("nextActionOpenCorpus"), section: "corpus" as SectionKey } : null,
    datasetQuestionsTotal === 0 ? { label: t("nextActionOpenDatasets"), section: "datasets" as SectionKey } : null,
    !runId.trim() ? { label: t("nextActionOpenReview"), section: "review-runs" as SectionKey } : null,
    runId.trim() && !evalRunId.trim() ? { label: t("nextActionRunEvaluation"), section: "evaluation" as SectionKey } : null,
    runQuestionDetailData ? { label: t("nextActionPromoteGold"), section: "gold" as SectionKey } : null,
  ].filter(Boolean) as Array<{ label: string; section: SectionKey }>;

  const navItems: NavItem[] = [
    { key: "projects", label: t("navProjects"), icon: IconFolders },
    { key: "overview", label: t("navOverview"), icon: IconLayoutDashboard },
    { key: "corpus", label: t("navCorpus"), icon: IconDatabase },
    { key: "datasets", label: t("navDatasets"), icon: IconBooks },
    { key: "review-runs", label: t("navReviewRuns"), icon: IconMessageSearch },
    { key: "evaluation", label: t("navEvaluation"), icon: IconChartBar },
    { key: "experiments", label: t("navExperiments"), icon: IconFlask2 },
    { key: "gold", label: t("navGold"), icon: IconRocket },
    { key: "synthetic", label: t("navSynthetic"), icon: IconSparkles },
    { key: "config", label: t("navConfig"), icon: IconSettings },
  ];

  function renderProjectsScreen() {
    return (
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <SectionCard
            title={t("projectsPanelTitle")}
            description={t("projectsIndexSubtitle")}
            action={
              <Button size="xs" variant="light" onClick={() => addProjectWorkspace()}>
                {t("actionAddProject")}
              </Button>
            }
          >
            <Stack gap="sm">
              {projectWorkspaces.map((workspace) => {
                const isActive = workspace.workspaceId === activeProjectWorkspace.workspaceId;
                return (
                  <Paper
                    key={workspace.workspaceId}
                    withBorder
                    p="md"
                    className={`project-card${isActive ? " project-card-active" : ""}`}
                    onClick={() => setActiveProjectWorkspaceId(workspace.workspaceId)}
                  >
                    <Stack gap="sm">
                      <Group justify="space-between" align="flex-start" wrap="nowrap">
                        <Stack gap={2}>
                          <Text fw={700}>{workspace.label}</Text>
                          <Text size="xs" c="dimmed">
                            {workspace.projectId || t("projectIdEmpty")}
                          </Text>
                        </Stack>
                        {isActive && <Badge>{t("projectActiveBadge")}</Badge>}
                      </Group>
                      <Group gap={6} wrap="wrap">
                        <Badge variant="outline">
                          {t("corpusShortLabel")}: {displayValue(workspace.corpusLabel)}
                        </Badge>
                        <Badge variant="outline">
                          {t("datasetShortLabel")}: {displayValue(workspace.datasetLabel, workspace.datasetId)}
                        </Badge>
                        <Badge color={readinessColor} variant="light">
                          {readinessLabel}
                        </Badge>
                      </Group>
                      <SimpleGrid cols={2} spacing="xs">
                        <MetricCard label={t("snapshotCorpusJobs")} value={workspace.metrics.corpusJobs} />
                        <MetricCard label={t("snapshotDocuments")} value={workspace.metrics.documents} />
                        <MetricCard label={t("snapshotChunks")} value={workspace.metrics.chunks} />
                        <MetricCard label={t("projectMetricQuestions")} value={workspace.metrics.questions} />
                      </SimpleGrid>
                    </Stack>
                  </Paper>
                );
              })}
            </Stack>
          </SectionCard>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 7 }}>
          <Stack gap="lg">
            <SectionCard title={t("projectFocusTitle")} description={t("projectSettingsSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextInput
                  label={t("projectName")}
                  value={activeProjectWorkspace.label}
                  onChange={(event) => updateActiveProjectWorkspace({ label: event.currentTarget.value })}
                />
                <TextInput label={t("corpusPackageName")} value={corpusLabel} readOnly />
                <TextInput
                  label={t("projectId")}
                  value={projectId}
                  onChange={(event) => setActiveProjectId(event.currentTarget.value)}
                />
                <TextInput
                  label={t("datasetName")}
                  value={datasetLabel}
                  onChange={(event) => setActiveDatasetLabel(event.currentTarget.value)}
                />
                <TextInput
                  label={t("datasetId")}
                  value={datasetId}
                  onChange={(event) => setActiveDatasetId(event.currentTarget.value)}
                />
                <TextInput
                  label={t("datasetIdGold")}
                  value={goldDatasetId}
                  onChange={(event) => setActiveGoldDatasetId(event.currentTarget.value)}
                />
                <TextInput
                  label={t("questionId")}
                  value={questionId}
                  onChange={(event) => updateActiveProjectWorkspace({ questionId: event.currentTarget.value })}
                />
                <Select
                  label={t("answerType")}
                  value={answerType}
                  onChange={(value) => updateActiveProjectWorkspace({ answerType: value || "free_text" })}
                  data={["boolean", "number", "date", "name", "names", "free_text"]}
                />
              </SimpleGrid>
              <TextInput
                label={t("questionText")}
                value={questionText}
                onChange={(event) => updateActiveProjectWorkspace({ questionText: event.currentTarget.value })}
              />
            </SectionCard>

            <SectionCard title={t("projectOverviewActiveConfig")} description={t("projectsConfigSubtitle")}>
              <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                <MetricCard label={t("projectId")} value={projectId || t("notSet")} />
                <MetricCard label={t("corpusPackageName")} value={displayValue(corpusLabel)} />
                <MetricCard label={t("datasetName")} value={displayValue(datasetLabel, datasetId)} />
                <MetricCard label={t("datasetIdGold")} value={goldDatasetId || "-"} />
                <MetricCard label={t("runId")} value={runId || "-"} />
              </SimpleGrid>
            </SectionCard>
          </Stack>
        </Grid.Col>
      </Grid>
    );
  }

  function renderOverviewScreen() {
    return (
      <Stack gap="lg">
        <SimpleGrid cols={{ base: 1, sm: 2, xl: 5 }}>
          <MetricCard label={t("snapshotCorpusJobs")} value={corpusJobs.length} />
          <MetricCard label={t("snapshotDocuments")} value={documentsItems.length} />
          <MetricCard label={t("snapshotChunks")} value={chunkTotal} />
          <MetricCard label={t("projectMetricQuestions")} value={datasetQuestionsTotal} />
          <MetricCard label={t("overviewReadiness")} value={readinessLabel} />
        </SimpleGrid>

        <Grid gutter="lg">
          <Grid.Col span={{ base: 12, xl: 7 }}>
            <Stack gap="lg">
              <SectionCard title={t("projectOverviewActiveConfig")} description={t("overviewConfigSubtitle")}>
                <SimpleGrid cols={{ base: 1, sm: 2, xl: 3 }}>
                  <MetricCard label={t("corpusPackageName")} value={displayValue(corpusLabel)} />
                  <MetricCard label={t("datasetName")} value={displayValue(datasetLabel, datasetId)} />
                  <MetricCard label={t("datasetIdGold")} value={goldDatasetId || "-"} />
                  <MetricCard label={t("runId")} value={runId || "-"} />
                  <MetricCard label={t("evalRunId")} value={evalRunId || "-"} />
                  <MetricCard label={t("experimentId")} value={experimentId || "-"} />
                  <MetricCard label={t("snapshotSynthJob")} value={synthJobId || "-"} />
                </SimpleGrid>
              </SectionCard>

              <SectionCard title={t("projectOverviewProcessLane")} description={t("overviewProcessSubtitle")}>
                <SimpleGrid cols={{ base: 1, sm: 2, xl: 5 }}>
                  <MetricCard label={t("processIngest")} value={corpusJobs.length > 0 ? t("statusCompleted") : t("stateEmpty")} />
                  <MetricCard label={t("processReview")} value={runId ? t("statusCompleted") : t("stateEmpty")} />
                  <MetricCard label={t("processEval")} value={evalRunId ? t("statusCompleted") : t("stateEmpty")} />
                  <MetricCard label={t("processExperiment")} value={experimentRunId || experimentId ? t("statusProcessing") : t("stateEmpty")} />
                  <MetricCard label={t("processGold")} value={goldDatasetId ? t("statusCompleted") : t("stateEmpty")} />
                </SimpleGrid>
              </SectionCard>
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, xl: 5 }}>
            <Stack gap="lg">
              <SectionCard title={t("projectOverviewValidationTitle")} description={t("overviewValidationSubtitle")}>
                <Stack gap="sm">
                  {validationItems.length === 0 && (
                    <Alert color="green" icon={<IconCheckupList size={16} />}>
                      <Text size="sm">{t("validationAllGood")}</Text>
                    </Alert>
                  )}
                  {validationItems.map((item) => (
                    <Alert
                      key={item.id}
                      color={item.level === "error" ? "red" : item.level === "warning" ? "yellow" : "green"}
                      icon={item.level === "success" ? <IconCheckupList size={16} /> : <IconFileAnalytics size={16} />}
                    >
                      <Stack gap={2}>
                        <Text size="sm" fw={600}>
                          {item.title}
                        </Text>
                        <Text size="xs">{item.detail}</Text>
                      </Stack>
                    </Alert>
                  ))}
                </Stack>
              </SectionCard>

              <SectionCard title={t("projectOverviewNextActions")} description={t("overviewNextActionsSubtitle")}>
                <Group gap="sm" wrap="wrap">
                  {recommendedActions.map((action) => (
                    <Button key={action.label} variant="light" onClick={() => navigate(action.section)}>
                      {action.label}
                    </Button>
                  ))}
                </Group>
              </SectionCard>

              <SectionCard title={t("projectOverviewRecentActivity")} description={t("overviewActivitySubtitle")}>
                <Stack gap="sm">
                  {activityLog.length === 0 && (
                    <Text size="sm" c="dimmed">
                      {t("activityEmpty")}
                    </Text>
                  )}
                  {activityLog.slice(0, 5).map((item) => (
                    <Paper key={item.id} withBorder p="sm">
                      <Group justify="space-between">
                        <Stack gap={2}>
                          <Text size="sm" fw={600}>
                            {item.label}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {new Date(item.timestamp).toLocaleTimeString()}
                          </Text>
                        </Stack>
                        <StatusBadge label={processingStatusLabel(item.status)} color={activityStatusColor(item.status)} />
                      </Group>
                      {item.artifactId && (
                        <Text size="xs" c="dimmed" mt={6}>
                          {t("activityArtifact")}: {item.artifactId}
                        </Text>
                      )}
                    </Paper>
                  ))}
                </Stack>
              </SectionCard>
            </Stack>
          </Grid.Col>
        </Grid>
      </Stack>
    );
  }

  function renderCorpusScreen() {
    return (
      <Stack gap="lg">
        <SectionCard title={t("corpusImportTitle")} description={t("corpusImportSubtitle")}>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <FileInput
              label={t("zipFile")}
              value={zipFile}
              onChange={handleZipFileChange}
              accept=".zip,application/zip"
              placeholder={t("zipPlaceholder")}
            />
            <Group align="flex-end">
              <Button loading={isActionLoading("importCorpus")} onClick={() => importCorpusZip()}>
                {t("actionImport")}
              </Button>
              <Button variant="light" loading={isActionLoading("processingResults")} onClick={() => loadProcessingResults()}>
                {t("actionLoadProcessingResults")}
              </Button>
            </Group>
          </SimpleGrid>
        </SectionCard>

        <Tabs defaultValue="documents" variant="outline">
          <Tabs.List>
            <Tabs.Tab value="documents">{t("corpusTabDocuments")}</Tabs.Tab>
            <Tabs.Tab value="processing">{t("corpusTabProcessing")}</Tabs.Tab>
            <Tabs.Tab value="enrichment">{t("corpusTabEnrichment")}</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="processing" pt="md">
            <Grid gutter="lg">
              <Grid.Col span={{ base: 12, xl: 4 }}>
                <SectionCard title={t("corpusJobsTitle")} description={t("corpusJobsSubtitle")}>
                  <Stack gap="sm">
                    {corpusJobs.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("noCorpusJobs")}
                      </Text>
                    )}
                    {corpusJobs.map((job, index) => {
                      const jobId = String(job.job_id ?? `job-${index}`);
                      const isActive = jobId === String((selectedCorpusJob as any)?.job_id ?? "");
                      return (
                        <Paper
                          key={jobId}
                          withBorder
                          p="sm"
                          className={`project-card${isActive ? " project-card-active" : ""}`}
                          onClick={() => setSelectedCorpusJobId(jobId)}
                        >
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>
                                {fileLabelFromValue(job.blob_url ?? job.job_id ?? `job_${index + 1}`)}
                              </Text>
                              <StatusBadge
                                label={processingStatusLabel(String(job.status ?? "unknown"))}
                              color={processingStatusColor(String(job.status ?? "unknown"))}
                            />
                          </Group>
                        </Paper>
                      );
                    })}
                  </Stack>
                </SectionCard>
              </Grid.Col>

              <Grid.Col span={{ base: 12, xl: 8 }}>
                <Stack gap="lg">
                  <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                    <MetricCard label={t("summaryDocuments")} value={String(processingSummary.documents ?? 0)} />
                    <MetricCard label={t("summaryPages")} value={String(processingSummary.pages ?? 0)} />
                    <MetricCard label={t("summaryParagraphs")} value={String(processingSummary.paragraphs ?? 0)} />
                    <MetricCard label={t("corpusWarningsCount")} value={parseWarningsCount} />
                  </SimpleGrid>

                  <SectionCard title={t("corpusDiagnosticsTitle")} description={t("corpusDiagnosticsSubtitle")}>
                    <SimpleGrid cols={{ base: 1, md: 3 }}>
                      <MetricCard
                        label={t("corpusAvgQuality")}
                        value={qualityAverage === null ? "-" : qualityAverage.toFixed(3)}
                      />
                      <MetricCard label={t("corpusWarningsCount")} value={parseWarningsCount} />
                      <MetricCard label={t("corpusErrorsCount")} value={parseErrorsCount} />
                    </SimpleGrid>
                    <Group gap={6} mt="sm">
                      {Object.entries(processingStatusCounts).map(([status, count]) => (
                        <Badge key={status} color={processingStatusColor(status)} variant="light">
                          {processingStatusLabel(status)}: {String(count)}
                        </Badge>
                      ))}
                    </Group>
                    <Divider />
                    <Text size="sm" fw={700}>
                      {t("corpusDocTypesTitle")}
                    </Text>
                    <Group gap={6}>
                      {docTypeRows.map((row) => (
                        <Badge key={row.docType} variant="outline">
                          {documentTypeLabel(row.docType)}: {row.count}
                        </Badge>
                      ))}
                    </Group>
                    {latestJob && (
                      <Button variant="subtle" size="xs" onClick={() => openDebug(t("corpusDebugTitle"), latestJob)}>
                        {t("actionOpenDebug")}
                      </Button>
                    )}
                  </SectionCard>

                  <SectionCard title={t("corpusEnrichmentJobsTitle")} description={t("corpusEnrichmentJobsSubtitle")}>
                    {enrichmentJobs.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                    <SimpleGrid cols={{ base: 1, md: 2 }}>
                      {enrichmentJobs.slice(0, 4).map((job, index) => (
                        <Paper key={String(job.job_id ?? index)} withBorder p="sm">
                          <Stack gap="xs">
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>
                                {String(job.processing_profile_version ?? job.job_id ?? `enrichment-${index + 1}`)}
                              </Text>
                              <StatusBadge
                                label={processingStatusLabel(String(job.status ?? "unknown"))}
                                color={processingStatusColor(String(job.status ?? "unknown"))}
                              />
                            </Group>
                            <SimpleGrid cols={{ base: 2, sm: 2 }}>
                              <SnapshotRow
                                label={t("summaryDocuments")}
                                value={`${countValue(job.processed_document_count)}/${countValue(job.document_count)}`}
                              />
                              <SnapshotRow
                                label={t("chunkTotal")}
                                value={`${countValue(job.processed_chunk_count)}/${countValue(job.chunk_count)}`}
                              />
                              <SnapshotRow label={t("corpusCandidateOntology")} value={countValue(job.candidate_entry_count)} />
                              <SnapshotRow label={t("corpusActiveOntology")} value={countValue(job.active_entry_count)} />
                            </SimpleGrid>
                            <Text size="xs" c="dimmed">
                              {t("docLlmModel")}: {String(job.llm_model_version ?? "-")}
                            </Text>
                          </Stack>
                        </Paper>
                      ))}
                    </SimpleGrid>
                  </SectionCard>
                </Stack>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="documents" pt="md">
            <Stack gap="lg">
              <SectionCard title={t("corpusDocumentsTitle")} description={t("corpusDocumentsSubtitle")}>
                <SimpleGrid cols={{ base: 1, md: 4 }}>
                  <TextInput
                    label={t("documentsLimit")}
                    value={documentsLimit}
                    onChange={(event) => setDocumentsLimit(event.currentTarget.value)}
                  />
                  <TextInput
                    label={t("chunkDocumentFilter")}
                    value={chunkDocumentFilter}
                    onChange={(event) => setChunkDocumentFilter(event.currentTarget.value)}
                  />
                  <TextInput
                    label={t("chunkLimit")}
                    value={chunkLimit}
                    onChange={(event) => setChunkLimit(event.currentTarget.value)}
                  />
                  <Group align="flex-end">
                    <Button loading={isActionLoading("loadDocuments")} onClick={() => loadDocuments()}>
                      {t("actionLoadDocuments")}
                    </Button>
                    <Button variant="light" loading={isActionLoading("loadChunks")} onClick={() => loadChunks()}>
                      {t("actionLoadChunks")}
                    </Button>
                  </Group>
                </SimpleGrid>
              </SectionCard>

              <Grid gutter="lg">
                <Grid.Col span={{ base: 12, xl: 3 }}>
                  <SectionCard title={t("corpusJobsTitle")} description={t("corpusJobsSubtitle")}>
                    <Stack gap="sm">
                      {corpusJobs.length === 0 && (
                        <Text size="sm" c="dimmed">
                          {t("noCorpusJobs")}
                        </Text>
                      )}
                      {corpusJobs.map((job, index) => {
                        const jobId = String(job.job_id ?? `job-${index}`);
                        const isActive = jobId === String((selectedCorpusJob as any)?.job_id ?? "");
                        return (
                          <Paper
                            key={jobId}
                            withBorder
                            p="sm"
                            className={`project-card${isActive ? " project-card-active" : ""}`}
                            onClick={() => setSelectedCorpusJobId(jobId)}
                          >
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>
                                {fileLabelFromValue(job.blob_url ?? job.job_id ?? `job_${index + 1}`)}
                              </Text>
                              <StatusBadge
                                label={processingStatusLabel(String(job.status ?? "unknown"))}
                                color={processingStatusColor(String(job.status ?? "unknown"))}
                              />
                            </Group>
                          </Paper>
                        );
                      })}
                    </Stack>
                  </SectionCard>
                </Grid.Col>

                <Grid.Col span={{ base: 12, xl: 4 }}>
                  <SectionCard title={t("sectionDocuments")} description={t("documentsListSubtitle")}>
                    <Stack gap="sm">
                      <SimpleGrid cols={{ base: 1, md: 3 }}>
                        <Select
                          label={t("docFilterType")}
                          value={documentTypeFilter}
                          onChange={(value) => setDocumentTypeFilter(value || "all")}
                          data={documentTypeFilterOptions}
                        />
                        <Select
                          label={t("docFilterStatus")}
                          value={documentStatusFilter}
                          onChange={(value) => setDocumentStatusFilter(value || "all")}
                          data={documentStatusFilterOptions}
                        />
                        <Select
                          label={t("docFilterQuality")}
                          value={documentQualityFilter}
                          onChange={(value) => setDocumentQualityFilter(value || "all")}
                          data={documentQualityFilterOptions}
                        />
                      </SimpleGrid>
                      {filteredDocumentsItems.length === 0 && (
                        <Text size="sm" c="dimmed">
                          {documentsItems.length === 0 ? t("noDocumentsData") : t("noDocumentsMatchFilters")}
                        </Text>
                      )}
                      {filteredDocumentsItems.map((doc, index) => {
                        const documentId = String(doc.document_id ?? "");
                        const processingDoc = processingDocumentsById[documentId] ?? null;
                        const parserStatus = deriveParserStageStatus(doc.status, processingDoc, recordFrom(processingDoc));
                        const docLlmStatus = normalizeText(processingDoc?.llm_document_status);
                        const agenticStatus = normalizeText(processingDoc?.enrichment_status);
                        const docCoverage = formatPercentValue(processingDoc?.agent_chunk_coverage_ratio);

                        return (
                          <Paper key={String(doc.document_id ?? index)} withBorder p="sm">
                            <Stack gap={6}>
                              <Group justify="space-between">
                                <Stack gap={6}>
                                  <Text size="sm" fw={600}>
                                    {documentDisplayTitle(doc)}
                                  </Text>
                                  <Group gap={6}>
                                    <Badge variant="light">{documentTypeLabel(doc.doc_type)}</Badge>
                                    {documentReferenceLabel(doc) && (
                                      <Badge variant="outline">{documentReferenceLabel(doc)}</Badge>
                                    )}
                                    {documentYearLabel(doc) && (
                                      <Badge variant="outline">
                                        {t("docCardYear")}: {documentYearLabel(doc)}
                                      </Badge>
                                    )}
                                    {documentPageCountLabel(doc) && (
                                      <Badge variant="outline">
                                        {t("docCardPages")}: {documentPageCountLabel(doc)}
                                      </Badge>
                                    )}
                                  </Group>
                                  <Group gap={6}>
                                    <StageBadge label={t("corpusParserStage")} status={parserStatus} />
                                    {agenticStatus && <StageBadge label={t("corpusAgenticStage")} status={agenticStatus} />}
                                    {docLlmStatus && <StageBadge label={t("corpusDocumentLlmStage")} status={docLlmStatus} />}
                                  </Group>
                                  {(countValue(processingDoc?.agent_assertion_count) > 0 || docCoverage !== "-") && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusOntologyAssertions")}: {countValue(processingDoc?.agent_assertion_count)} · {t("corpusChunkCoverage")}: {docCoverage}
                                    </Text>
                                  )}
                                </Stack>
                                <Button
                                  size="xs"
                                  variant={selectedDocumentId === documentId ? "filled" : "light"}
                                  onClick={() => openDocument(documentId)}
                                >
                                  {t("actionOpenDocument")}
                                </Button>
                                <Button
                                  size="xs"
                                  variant="subtle"
                                  loading={isActionLoading("reingestDocument") && reingestDocumentId === documentId}
                                  onClick={() => reingestDocument(documentId)}
                                >
                                  {t("actionReingestDocument")}
                                </Button>
                              </Group>
                            </Stack>
                          </Paper>
                        );
                      })}
                    </Stack>
                  </SectionCard>
                </Grid.Col>

                <Grid.Col span={{ base: 12, xl: 5 }}>
                  <Stack gap="lg">
                    <SectionCard title={t("sectionDocumentViewer")} description={t("documentViewerSubtitle")}>
                      {!documentDetail && (
                        <EmptyState
                          title={t("noDocumentSelected")}
                          description={t("documentViewerEmptySubtitle")}
                        />
                      )}
                      {documentDetail && (
                        <Stack gap="md">
                          <Paper withBorder p="sm">
                            <Stack gap={6}>
                              <Text fw={700}>{documentDisplayTitle(selectedDocumentManifest)}</Text>
                              <Group gap={6}>
                                <Badge variant="light">{documentTypeLabel(selectedDocumentManifest?.doc_type)}</Badge>
                                {documentReferenceLabel(selectedDocumentManifest) && (
                                  <Badge variant="outline">{documentReferenceLabel(selectedDocumentManifest)}</Badge>
                                )}
                                {documentYearLabel(selectedDocumentManifest) && (
                                  <Badge variant="outline">
                                    {t("docCardYear")}: {documentYearLabel(selectedDocumentManifest)}
                                  </Badge>
                                )}
                                {documentPageCountLabel(selectedDocumentManifest) && (
                                  <Badge variant="outline">
                                    {t("docCardPages")}: {documentPageCountLabel(selectedDocumentManifest)}
                                  </Badge>
                                )}
                              </Group>
                            </Stack>
                          </Paper>

                          <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                            <MetricCard label={t("docViewerPages")} value={String((documentDetail as any)?.summary?.page_count ?? 0)} />
                            <MetricCard label={t("docViewerChunks")} value={String((documentDetail as any)?.summary?.chunk_count ?? 0)} />
                            <MetricCard label={t("docTextQuality")} value={formatMetricValue(documentProcessing.text_quality_score, 3)} />
                            <MetricCard label={t("corpusParserStatus")} value={processingStatusLabel(parserStageStatus)} />
                          </SimpleGrid>

                          <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                            <MetricCard
                              label={t("corpusChunkLlmCoverage")}
                              value={documentChunkCount > 0 ? `${chunkLlmCompletedCount}/${documentChunkCount}` : "-"}
                              hint={`${t("statusFailed")}: ${chunkLlmFailedCount} · ${t("statusProcessing")}: ${chunkLlmQueuedCount}`}
                            />
                            <MetricCard label={t("docLlmStatus")} value={processingStatusLabel(documentLlmStatus)} />
                            <MetricCard label={t("docAgenticStatus")} value={processingStatusLabel(agenticStageStatus)} />
                            <MetricCard
                              label={t("corpusOntologyAssertions")}
                              value={ontologyAssertionCount}
                              hint={`${t("corpusCandidateOntology")}: ${candidateOntologyCount} · ${t("corpusActiveOntology")}: ${activeOntologyCount}`}
                            />
                          </SimpleGrid>

                          <Group gap={6}>
                            <StageBadge label={t("corpusParserStage")} status={parserStageStatus} />
                            <StageBadge label={t("corpusChunkLlmStage")} status={chunkLlmStageStatus} />
                            <StageBadge label={t("corpusDocumentLlmStage")} status={documentLlmStatus} />
                            <StageBadge label={t("corpusAgenticStage")} status={agenticStageStatus} />
                          </Group>

                          <Text size="sm" c="dimmed">
                            {t("corpusProcessingNote")}
                          </Text>

                          <Paper withBorder p="sm">
                            <Grid gutter="md">
                              <Grid.Col span={{ base: 12, xl: 7 }}>
                                <Stack gap="xs">
                                  <Text size="sm" fw={700}>
                                    {t("corpusLlmSummaryTitle")}
                                  </Text>
                                  <Text size="sm">
                                    {displayValue(
                                      String(documentLlmPayload.summary ?? ""),
                                      String(selectedProcessingDocument?.compact_summary ?? "")
                                    )}
                                  </Text>
                                  {documentTopicValues.length > 0 && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusDocumentTopics")}: {previewList(documentTopicValues, 6)}
                                    </Text>
                                  )}
                                  {documentEntityValues.length > 0 && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusDocumentEntities")}: {previewList(documentEntityValues, 6)}
                                    </Text>
                                  )}
                                  {documentReferenceValues.length > 0 && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusDocumentRefs")}: {previewList(documentReferenceValues, 6)}
                                    </Text>
                                  )}
                                </Stack>
                              </Grid.Col>
                              <Grid.Col span={{ base: 12, xl: 5 }}>
                                <Stack gap="xs">
                                  <Text size="sm" fw={700}>
                                    {t("corpusOntologySummaryTitle")}
                                  </Text>
                                  <SnapshotRow label={t("corpusChunkCoverage")} value={chunkCoverageValue} />
                                  <SnapshotRow label={t("corpusOntologyAssertions")} value={ontologyAssertionCount} />
                                  <SnapshotRow label={t("corpusCandidateOntology")} value={candidateOntologyCount} />
                                  <SnapshotRow label={t("corpusActiveOntology")} value={activeOntologyCount} />
                                  {ontologyActorValues.length > 0 && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusOntologyActors")}: {previewList(ontologyActorValues, 6)}
                                    </Text>
                                  )}
                                  {ontologyBeneficiaryValues.length > 0 && (
                                    <Text size="xs" c="dimmed">
                                      {t("corpusOntologyBeneficiaries")}: {previewList(ontologyBeneficiaryValues, 6)}
                                    </Text>
                                  )}
                                </Stack>
                              </Grid.Col>
                            </Grid>
                          </Paper>

                          <SimpleGrid cols={{ base: 1, md: 3 }}>
                            <Select
                              label={t("docViewerPageSelect")}
                              value={selectedPageId}
                              onChange={(value) => setSelectedPageId(value || "")}
                              data={documentDetailPages.map((page) => ({
                                value: String(page.page_id ?? ""),
                                label: pageOptionLabel(page),
                              }))}
                            />
                            <Checkbox
                              mt={30}
                              label={t("llmForceReprocess")}
                              checked={forceLlmReprocess}
                              onChange={(event) => setForceLlmReprocess(event.currentTarget.checked)}
                            />
                            <Checkbox
                              mt={30}
                              label={t("llmReclassifyDocument")}
                              checked={reclassifyDocumentWithLlm}
                              onChange={(event) => setReclassifyDocumentWithLlm(event.currentTarget.checked)}
                            />
                          </SimpleGrid>

                          <Group>
                            <Button loading={isActionLoading("runDocumentLlm")} onClick={() => runDocumentLlm()}>
                              {t("actionRunDocumentLlm")}
                            </Button>
                            <Button variant="light" loading={isActionLoading("openDocument")} onClick={() => openDocument(selectedDocumentId)}>
                              {t("actionRefreshDocument")}
                            </Button>
                            {selectedDocumentFileUrl && (
                              <Button component="a" href={selectedDocumentFileUrl} target="_blank" rel="noreferrer" variant="light">
                                {t("actionOpenPdf")}
                              </Button>
                            )}
                            <Button variant="subtle" size="xs" onClick={() => openDebug(t("documentViewerDebugTitle"), documentDetail)}>
                              {t("actionOpenDebug")}
                            </Button>
                          </Group>

                          <Grid gutter="md">
                            <Grid.Col span={{ base: 12, xl: 6 }}>
                              <Paper withBorder p="sm">
                                <Stack gap="xs">
                                  <Text size="sm" fw={700}>
                                    {t("docViewerPageText")}
                                  </Text>
                                  <Group gap={6}>
                                    <Badge variant="light">
                                      {t("docViewerPageNumber")}: {selectedPage ? Number((selectedPage as any)?.page_num ?? 0) + 1 : "-"}
                                    </Badge>
                                    <Badge variant="outline">
                                      {t("docViewerPageChunkCount")}: {selectedPageChunks.length}
                                    </Badge>
                                  </Group>
                                  <Text size="sm">{String((selectedPage as any)?.text ?? "")}</Text>
                                </Stack>
                              </Paper>
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, xl: 6 }}>
                              <Paper withBorder p="sm">
                                <Stack gap="xs">
                                  <Text size="sm" fw={700}>
                                    {t("docViewerPageChunks")}
                                  </Text>
                                  {selectedPageChunks.length === 0 && (
                                    <Text size="sm" c="dimmed">
                                      {t("noChunkData")}
                                    </Text>
                                  )}
                                  {selectedPageChunks.map((chunk, index) => (
                                    <Paper withBorder p="xs" key={String(chunk.paragraph_id ?? index)}>
                                      <Stack gap={8}>
                                        <Group justify="space-between">
                                          <Text size="sm" fw={700}>
                                            {chunkDisplayLabel(chunk, index)}
                                          </Text>
                                          <Group gap={6}>
                                            <Badge color={processingStatusColor(String(chunk.llm_status ?? "unknown"))} variant="light">
                                              {processingStatusLabel(String(chunk.llm_status ?? "unknown"))}
                                            </Badge>
                                            <Badge variant="outline">
                                              {t("llmSectionType")}: {displayValue(String(chunk.llm_section_type ?? ""), String(chunk.summary_tag ?? ""))}
                                            </Badge>
                                          </Group>
                                        </Group>
                                        <SimpleGrid cols={{ base: 2, sm: 3 }}>
                                          <SnapshotRow label={t("chunkParagraphClass")} value={String(chunk.paragraph_class ?? t("notSet"))} />
                                          <SnapshotRow label={t("chunkEntities")} value={Array.isArray(chunk.entities) ? chunk.entities.length : 0} />
                                          <SnapshotRow label={t("chunkCaseRefs")} value={Array.isArray(chunk.case_refs) ? chunk.case_refs.length : 0} />
                                          <SnapshotRow label={t("chunkLawRefs")} value={Array.isArray(chunk.law_refs) ? chunk.law_refs.length : 0} />
                                          <SnapshotRow label={t("chunkDates")} value={Array.isArray(chunk.dates) ? chunk.dates.length : 0} />
                                          <SnapshotRow label={t("chunkTags")} value={Array.isArray(chunk.llm_tags) ? chunk.llm_tags.length : 0} />
                                        </SimpleGrid>
                                        {previewList(chunk.llm_tags) && (
                                          <Text size="xs" c="dimmed">
                                            {t("chunkTags")}: {previewList(chunk.llm_tags)}
                                          </Text>
                                        )}
                                        {previewList(chunk.entities) && (
                                          <Text size="xs" c="dimmed">
                                            {t("chunkEntities")}: {previewList(chunk.entities)}
                                          </Text>
                                        )}
                                        {previewList(chunk.case_refs) && (
                                          <Text size="xs" c="dimmed">
                                            {t("chunkCaseRefs")}: {previewList(chunk.case_refs)}
                                          </Text>
                                        )}
                                        <Text size="sm">{displayValue(String(chunk.llm_summary ?? ""), String(chunk.text ?? "-"))}</Text>
                                        {normalizeText(chunk.llm_summary) && normalizeText(chunk.text) !== normalizeText(chunk.llm_summary) && (
                                          <Text size="xs" c="dimmed">
                                            {truncateText(chunk.text)}
                                          </Text>
                                        )}
                                      </Stack>
                                    </Paper>
                                  ))}
                                  {selectedPageAssertions.length > 0 && (
                                    <>
                                      <Divider />
                                      <Text size="sm" fw={700}>
                                        {t("corpusPageAssertionsTitle")}
                                      </Text>
                                      {selectedPageAssertions.map((assertion, index) => (
                                        <Paper
                                          key={String(assertion.assertion_id ?? `assertion-${index}`)}
                                          withBorder
                                          p="xs"
                                        >
                                          <Stack gap={4}>
                                            <Text size="sm" fw={600}>
                                              {displayValue(String(assertion.subject_text ?? ""))}{" "}
                                              {displayValue(String(assertion.relation_type ?? ""), "refers_to")}{" "}
                                              {displayValue(String(assertion.object_text ?? ""))}
                                            </Text>
                                            <Text size="xs" c="dimmed">
                                              {String(assertion.modality ?? t("notSet"))}
                                            </Text>
                                          </Stack>
                                        </Paper>
                                      ))}
                                    </>
                                  )}
                                </Stack>
                              </Paper>
                            </Grid.Col>
                          </Grid>
                        </Stack>
                      )}
                    </SectionCard>

                    <SectionCard title={t("corpusChunkSummaryTitle")} description={t("corpusChunkSummarySubtitle")}>
                      <SimpleGrid cols={{ base: 1, sm: 2 }}>
                        <MetricCard label={t("chunkTotal")} value={visibleChunkTotal} />
                        <MetricCard label={t("chunkDocumentCount")} value={visibleChunkDocumentCount} />
                      </SimpleGrid>
                    </SectionCard>
                  </Stack>
                </Grid.Col>
              </Grid>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="enrichment" pt="md">
            <SectionCard title={t("corpusEnrichmentTitle")} description={t("corpusEnrichmentSubtitle")}>
              {!documentDetail && (
                <EmptyState
                  title={t("corpusEnrichmentEmptyTitle")}
                  description={t("corpusEnrichmentEmptySubtitle")}
                  action={
                    <Button variant="light" onClick={() => navigate("corpus")}>
                      {t("actionOpenDocument")}
                    </Button>
                  }
                />
              )}
              {documentDetail && (
                <Stack gap="md">
                  <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                    <MetricCard label={t("corpusParserStatus")} value={processingStatusLabel(parserStageStatus)} />
                    <MetricCard label={t("corpusChunkLlmCoverage")} value={documentChunkCount > 0 ? `${chunkLlmCompletedCount}/${documentChunkCount}` : "-"} />
                    <MetricCard label={t("docLlmStatus")} value={processingStatusLabel(documentLlmStatus)} />
                    <MetricCard label={t("docAgenticStatus")} value={processingStatusLabel(agenticStageStatus)} />
                  </SimpleGrid>
                  <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                    <MetricCard label={t("docLlmModel")} value={String(documentProcessing.llm_document_model ?? "-")} />
                    <MetricCard label={t("corpusOntologyAssertions")} value={ontologyAssertionCount} />
                    <MetricCard label={t("corpusCandidateOntology")} value={candidateOntologyCount} />
                    <MetricCard label={t("corpusActiveOntology")} value={activeOntologyCount} />
                  </SimpleGrid>
                  <Group gap={6}>
                    <StageBadge label={t("corpusParserStage")} status={parserStageStatus} />
                    <StageBadge label={t("corpusChunkLlmStage")} status={chunkLlmStageStatus} />
                    <StageBadge label={t("corpusDocumentLlmStage")} status={documentLlmStatus} />
                    <StageBadge label={t("corpusAgenticStage")} status={agenticStageStatus} />
                    {ontologyTagPool.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                    {ontologyTagPool.map((tag) => (
                      <Badge key={tag} variant="outline">
                        {tag}
                      </Badge>
                    ))}
                  </Group>
                  <Text size="sm" c="dimmed">
                    {t("corpusProcessingNote")}
                  </Text>
                  <Button variant="subtle" size="xs" onClick={() => openDebug(t("corpusEnrichmentDebugTitle"), documentDetail)}>
                    {t("actionOpenDebug")}
                  </Button>
                </Stack>
              )}
            </SectionCard>
          </Tabs.Panel>
        </Tabs>
      </Stack>
    );
  }

  function renderDatasetsScreen() {
    return (
      <Tabs defaultValue="datasets" variant="outline">
        <Tabs.List>
          <Tabs.Tab value="datasets">{t("datasetsTabDatasets")}</Tabs.Tab>
          <Tabs.Tab value="questions">{t("datasetsTabQuestions")}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="datasets" pt="md">
          <Stack gap="lg">
            <SectionCard title={t("datasetsTitle")} description={t("datasetsSubtitle")}>
              <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                <MetricCard label={t("datasetName")} value={displayValue(datasetLabel, datasetId)} />
                <MetricCard label={t("projectMetricQuestions")} value={datasetQuestionsTotal} />
                <MetricCard label={t("questionImportLimit")} value={questionImportLimit} />
                <MetricCard label={t("overviewReadiness")} value={readinessLabel} />
              </SimpleGrid>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                <TextInput label={t("datasetName")} value={datasetLabel} onChange={(event) => setActiveDatasetLabel(event.currentTarget.value)} />
                <TextInput label={t("datasetId")} value={datasetId} onChange={(event) => setActiveDatasetId(event.currentTarget.value)} />
                <TextInput
                  label={t("questionImportLimit")}
                  value={questionImportLimit}
                  onChange={(event) => setQuestionImportLimit(event.currentTarget.value)}
                />
                <Group align="flex-end">
                  <Button loading={isActionLoading("importQuestions")} onClick={() => importQuestions()}>
                    {t("actionImportPublicQuestions")}
                  </Button>
                  <Button variant="light" loading={isActionLoading("listQuestions")} onClick={() => loadDatasetQuestions()}>
                    {t("actionListImportedQuestions")}
                  </Button>
                </Group>
              </SimpleGrid>
            </SectionCard>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="questions" pt="md">
          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, xl: 7 }}>
              <SectionCard title={t("datasetQuestionsTitle")} description={t("datasetQuestionsSubtitle")}>
                {datasetQuestionItems.length === 0 && (
                  <EmptyState title={t("stateEmpty")} description={t("datasetQuestionsEmptySubtitle")} />
                )}
                {datasetQuestionItems.length > 0 && (
                  <ScrollArea>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>{t("questionId")}</th>
                          <th>{t("questionText")}</th>
                          <th>{t("answerType")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {datasetQuestionItems.map((question, index) => (
                          <tr
                            key={String(question.question_id ?? index)}
                            onClick={() => {
                              updateActiveProjectWorkspace({
                                questionId: String(question.question_id ?? ""),
                                questionText: String(question.question ?? question.prompt ?? ""),
                                answerType: String(question.answer_type ?? "free_text"),
                              });
                            }}
                          >
                            <td>{String(question.question_id ?? "-")}</td>
                            <td>{String(question.question ?? question.prompt ?? "-")}</td>
                            <td>{String(question.answer_type ?? "-")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollArea>
                )}
              </SectionCard>
            </Grid.Col>

            <Grid.Col span={{ base: 12, xl: 5 }}>
              <Stack gap="lg">
                <SectionCard title={t("datasetsQuestionWorkspaceTitle")} description={t("datasetsQuestionWorkspaceSubtitle")}>
                  <Stack gap="sm">
                    <TextInput
                      label={t("questionId")}
                      value={questionId}
                      onChange={(event) => updateActiveProjectWorkspace({ questionId: event.currentTarget.value })}
                    />
                    <Select
                      label={t("answerType")}
                      value={answerType}
                      onChange={(value) => updateActiveProjectWorkspace({ answerType: value || "free_text" })}
                      data={["boolean", "number", "date", "name", "names", "free_text"]}
                    />
                    <Checkbox
                      label={t("useLlm")}
                      checked={useLlm}
                      onChange={(event) => setUseLlm(event.currentTarget.checked)}
                    />
                    <TextInput
                      label={t("questionText")}
                      value={questionText}
                      onChange={(event) => updateActiveProjectWorkspace({ questionText: event.currentTarget.value })}
                    />
                    <Group>
                      <Button loading={isActionLoading("askSingle")} onClick={() => askSingle()}>
                        {t("actionAsk")}
                      </Button>
                      <Button variant="light" loading={isActionLoading("askBatch")} onClick={() => askBatch()}>
                        {t("actionRunBatch")}
                      </Button>
                    </Group>
                  </Stack>
                </SectionCard>
              </Stack>
            </Grid.Col>
          </Grid>
        </Tabs.Panel>
      </Tabs>
    );
  }

  function renderReviewRunsScreen() {
    return (
      <Tabs defaultValue="runs" variant="outline">
        <Tabs.List>
          <Tabs.Tab value="runs">{t("runsTabRuns")}</Tabs.Tab>
          <Tabs.Tab value="review">{t("runsTabReview")}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="runs" pt="md">
          <Stack gap="lg">
            <SectionCard title={t("sectionRunOps")} description={t("runsSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                <TextInput label={t("runId")} value={runId} onChange={(event) => setRunId(event.currentTarget.value)} />
                <Select
                  label={t("pageIndexBase")}
                  value={String(pageIndexBase)}
                  onChange={(value) => setPageIndexBase(value === "1" ? 1 : 0)}
                  data={[
                    { value: "0", label: "0" },
                    { value: "1", label: "1" },
                  ]}
                />
                <Group align="flex-end">
                  <Button loading={isActionLoading("getRun")} onClick={() => loadRun()}>
                    {t("actionGetRun")}
                  </Button>
                  <Button variant="light" loading={isActionLoading("exportSubmission")} onClick={() => exportSubmission()}>
                    {t("actionExportSubmission")}
                  </Button>
                </Group>
              </SimpleGrid>
              {runData && (
                <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
                  <MetricCard label={t("runId")} value={String((runData as any)?.run_id ?? runId)} />
                  <MetricCard label={t("datasetId")} value={String((runData as any)?.dataset_id ?? datasetId)} />
                  <MetricCard label={t("projectId")} value={String((runData as any)?.project_id ?? projectId)} />
                  <MetricCard label={t("questionCount")} value={String((runData as any)?.question_count ?? "-")} />
                </SimpleGrid>
              )}
            </SectionCard>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="review" pt="md">
          <Stack gap="lg">
            <SectionCard title={t("sectionRunQuestionReview")} description={t("reviewSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                <TextInput
                  label={t("questionId")}
                  value={questionId}
                  onChange={(event) => updateActiveProjectWorkspace({ questionId: event.currentTarget.value })}
                />
                <TextInput
                  label={t("datasetIdGold")}
                  value={goldDatasetId}
                  onChange={(event) => setActiveGoldDatasetId(event.currentTarget.value)}
                />
                <Group align="flex-end">
                  <Button loading={runQuestionDetailState.loading} onClick={() => loadRunQuestionDetail()}>
                    {t("actionLoadRunQuestionReview")}
                  </Button>
                  <Button
                    variant="light"
                    disabled={!runQuestionDetailData}
                    loading={isActionLoading("promoteGold")}
                    onClick={() => promoteRunQuestionToGold()}
                  >
                    {t("actionPromoteToGold")}
                  </Button>
                </Group>
              </SimpleGrid>
            </SectionCard>

            {runQuestionDetailState.loading && <Loader size="sm" />}
            {!runQuestionDetailState.loading && runQuestionDetailState.error && (
              <Alert color="red">{`${t("stateError")}: ${runQuestionDetailState.error}`}</Alert>
            )}

            {!runQuestionDetailState.loading && !runQuestionDetailState.error && !runQuestionDetailData && (
              <EmptyState title={t("reviewEmptyTitle")} description={t("reviewEmptySubtitle")} />
            )}

            {!runQuestionDetailState.loading && !runQuestionDetailState.error && runQuestionDetailData && (
              <Grid gutter="lg">
                <Grid.Col span={{ base: 12, xl: 4 }}>
                  <Stack gap="lg">
                    <SectionCard title={t("reviewQuestionTitle")}>
                      <Text size="xs" c="dimmed">
                        {String((runQuestionDetailData as any)?.question?.id ?? questionId)}
                      </Text>
                      <Text size="sm">{String((runQuestionDetailData as any)?.question?.question ?? "-")}</Text>
                      <SimpleGrid cols={2}>
                        <MetricCard label={t("answerType")} value={String((runQuestionDetailData as any)?.response?.answer_type ?? "-")} />
                        <MetricCard label={t("reviewRoute")} value={String((runQuestionDetailData as any)?.response?.route_name ?? "-")} />
                      </SimpleGrid>
                    </SectionCard>

                    <SectionCard title={t("reviewAnswerTitle")} action={
                      <Button variant="subtle" size="xs" onClick={() => openDebug(t("reviewDebugTitle"), runQuestionDetailData)}>
                        {t("actionOpenDebug")}
                      </Button>
                    }>
                      <Text size="sm">{String((runQuestionDetailData as any)?.response?.answer ?? "-")}</Text>
                      <SimpleGrid cols={{ base: 1, sm: 2 }}>
                        <MetricCard
                          label={t("reviewConfidence")}
                          value={formatMetricValue((runQuestionDetailData as any)?.response?.confidence, 3)}
                        />
                        <MetricCard
                          label={t("reviewUsedPages")}
                          value={String(Array.isArray((reviewEvidence as any)?.used_page_ids) ? ((reviewEvidence as any).used_page_ids as Array<unknown>).length : 0)}
                        />
                      </SimpleGrid>
                    </SectionCard>

                    <SectionCard title={t("reviewEvidenceTitle")}>
                      <Stack gap="sm">
                        {selectedReviewPages.length === 0 && (
                          <Text size="sm" c="dimmed">
                            {t("stateEmpty")}
                          </Text>
                        )}
                        {selectedReviewPages.map((page) => (
                          <Paper
                            key={String(page.page_id ?? "")}
                            withBorder
                            p="xs"
                            className={String(page.page_id ?? "") === String(selectedReviewPageId) ? "project-card-active" : ""}
                          >
                            <Stack gap={4}>
                              <Group justify="space-between" align="center">
                                <Button
                                  size="xs"
                                  variant={String(page.page_id ?? "") === String(selectedReviewPageId) ? "filled" : "light"}
                                  onClick={() => {
                                    setSelectedReviewPageId(String(page.page_id ?? ""));
                                    setSelectedReviewDocumentId(String((selectedReviewDocument as any)?.document_id ?? ""));
                                  }}
                                >
                                  {String(page.source_page_id ?? page.page_id ?? "page")}
                                </Button>
                                <Badge color={Boolean((page as any).used) ? "green" : "gray"} variant="light">
                                  {Boolean((page as any).used) ? t("reviewUsedBadge") : t("reviewRetrievedBadge")}
                                </Badge>
                              </Group>
                              <Text size="xs" c="dimmed">
                                {String(page.chunk_id ?? "-")}
                              </Text>
                              <Text size="xs">{String(page.chunk_text ?? "-")}</Text>
                            </Stack>
                          </Paper>
                        ))}
                      </Stack>
                    </SectionCard>
                  </Stack>
                </Grid.Col>

                <Grid.Col span={{ base: 12, xl: 8 }}>
                  <Stack gap="lg">
                    <SectionCard title={t("reviewDocumentTitle")}>
                      <Group justify="space-between" align="flex-start" wrap="wrap">
                        <Stack gap={4}>
                          <Text size="xs" c="dimmed">
                            {String((selectedReviewDocument as any)?.title ?? "-")}
                          </Text>
                        </Stack>
                        <Select
                          value={selectedReviewDocumentId}
                          onChange={(value) => {
                            const nextDocumentId = value || "";
                            setSelectedReviewDocumentId(nextDocumentId);
                            const nextDocument = reviewDocuments.find((doc) => String(doc.document_id ?? "") === nextDocumentId) ?? null;
                            const nextPages = nextDocument && Array.isArray((nextDocument as any).pages)
                              ? (((nextDocument as any).pages as Array<Record<string, unknown>>))
                              : [];
                            const firstUsedPage = nextPages.find((page) => Boolean(page.used)) ?? nextPages[0] ?? null;
                            setSelectedReviewPageId(String((firstUsedPage as any)?.page_id ?? ""));
                          }}
                          data={reviewDocuments.map((doc) => ({
                            value: String(doc.document_id ?? ""),
                            label: String(doc.title ?? doc.document_id ?? "document"),
                          }))}
                        />
                      </Group>
                      <Group>
                        <Button
                          size="xs"
                          variant="light"
                          disabled={
                            !selectedReviewPage ||
                            selectedReviewPages.findIndex((page) => String(page.page_id ?? "") === String((selectedReviewPage as any)?.page_id ?? "")) <= 0
                          }
                          onClick={() => {
                            const index = selectedReviewPages.findIndex(
                              (page) => String(page.page_id ?? "") === String((selectedReviewPage as any)?.page_id ?? "")
                            );
                            const previous = index > 0 ? selectedReviewPages[index - 1] : null;
                            if (previous) {
                              setSelectedReviewPageId(String(previous.page_id ?? ""));
                            }
                          }}
                        >
                          {t("reviewPrevPage")}
                        </Button>
                        <Button
                          size="xs"
                          variant="light"
                          disabled={
                            !selectedReviewPage ||
                            selectedReviewPages.findIndex((page) => String(page.page_id ?? "") === String((selectedReviewPage as any)?.page_id ?? "")) >=
                              selectedReviewPages.length - 1
                          }
                          onClick={() => {
                            const index = selectedReviewPages.findIndex(
                              (page) => String(page.page_id ?? "") === String((selectedReviewPage as any)?.page_id ?? "")
                            );
                            const next = index >= 0 && index < selectedReviewPages.length - 1 ? selectedReviewPages[index + 1] : null;
                            if (next) {
                              setSelectedReviewPageId(String(next.page_id ?? ""));
                            }
                          }}
                        >
                          {t("reviewNextPage")}
                        </Button>
                        <Text size="xs" c="dimmed">
                          {selectedReviewPage ? `${Number((selectedReviewPage as any).page_num ?? 0) + 1} / ${selectedReviewPages.length}` : "-"}
                        </Text>
                      </Group>
                    </SectionCard>

                    <Paper withBorder p="xs" style={{ minHeight: 720 }}>
                      {!selectedReviewPdfSrc && (
                        <Text size="sm" c="dimmed">
                          {t("stateEmpty")}
                        </Text>
                      )}
                      {selectedReviewPdfSrc && (
                        <Suspense fallback={<Text size="sm" c="dimmed">{t("stateLoading")}</Text>}>
                          <PdfReviewViewer
                            src={selectedReviewPdfSrc}
                            pageNumber={Number((selectedReviewPage as any)?.page_num ?? 0) + 1}
                            chunkTexts={
                              selectedReviewPages
                                .filter((page) => String(page.page_id ?? "") === String((selectedReviewPage as any)?.page_id ?? ""))
                                .map((page) => String(page.chunk_text ?? ""))
                            }
                          />
                        </Suspense>
                      )}
                    </Paper>
                  </Stack>
                </Grid.Col>
              </Grid>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    );
  }

  function renderEvaluationScreen() {
    return (
      <Stack gap="lg">
        <SectionCard title={t("sectionEvalOps")} description={t("evaluationSubtitle")}>
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <TextInput label={t("datasetIdGold")} value={goldDatasetId} onChange={(event) => setActiveGoldDatasetId(event.currentTarget.value)} />
            <TextInput label={t("runId")} value={runId} onChange={(event) => setRunId(event.currentTarget.value)} />
            <TextInput label={t("evalRunId")} value={evalRunId} onChange={(event) => setEvalRunId(event.currentTarget.value)} />
          </SimpleGrid>
          <Group>
            <Button loading={isActionLoading("createEvalRun")} onClick={() => createEvalRun()}>
              {t("actionCreateEvalRun")}
            </Button>
            <Button variant="light" loading={evalSlicesState.loading} onClick={() => loadEvalRunConsoleView()}>
              {t("actionGetEvalRun")}
            </Button>
            <Button variant="light" loading={evalSlicesState.loading} onClick={() => loadEvalReportConsoleView()}>
              {t("actionGetEvalReport")}
            </Button>
          </Group>
        </SectionCard>

        <SectionCard title={t("sectionEvalCompare")}>
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              <TextInput label={t("evalLeftRunId")} value={compareLeftEvalRunId} onChange={(event) => setCompareLeftEvalRunId(event.currentTarget.value)} />
              <TextInput label={t("evalRightRunId")} value={compareRightEvalRunId} onChange={(event) => setCompareRightEvalRunId(event.currentTarget.value)} />
            </SimpleGrid>
            <Group>
              <Button variant="light" loading={evalCompareState.loading} onClick={() => loadEvalCompareConsoleView()}>
                {t("actionCompareEvalRuns")}
              </Button>
            </Group>
            {evalCompareState.loading && <Text size="sm" c="dimmed">{t("stateLoading")}</Text>}
            {!evalCompareState.loading && evalCompareState.error && (
              <Text size="sm" c="red">{`${t("stateError")}: ${evalCompareState.error}`}</Text>
            )}
            {!evalCompareState.loading && !evalCompareState.error && evalCompareState.partial && (
              <Text size="sm" c="yellow.8">{`${t("statePartial")}: ${evalCompareState.partial}`}</Text>
            )}
            {!evalCompareState.loading && !evalCompareState.error && !evalCompareData && (
              <EmptyState title={t("evaluationCompareEmptyTitle")} description={t("evaluationCompareEmptySubtitle")} />
            )}
            {!evalCompareState.loading && !evalCompareState.error && evalCompareData && (
              <Stack gap="md">
                <SimpleGrid cols={{ base: 2, md: 5 }}>
                  {Object.entries(evalCompareMetricDeltas).map(([metric, value]) => (
                    <Paper withBorder p="xs" key={`eval-compare-metric-${metric}`}>
                      <Text size="xs" c="dimmed">{metricDeltaLabel(metric)}</Text>
                      <Badge variant="light" color={metricBadgeColor(Number(value ?? 0))}>
                        {formatDeltaValue(value)}
                      </Badge>
                    </Paper>
                  ))}
                </SimpleGrid>
                <SimpleGrid cols={{ base: 1, md: 2 }}>
                  <Paper withBorder p="sm">
                    <Stack gap="xs">
                      <Text size="sm" fw={700}>{t("sliceByAnswerType")}</Text>
                      {evalCompareByAnswerType.length === 0 && <Text size="sm" c="dimmed">{t("stateEmpty")}</Text>}
                      {evalCompareByAnswerType.map((row, index) => (
                        <Paper key={`eval-compare-answer-${index}`} withBorder p="xs">
                          <Group justify="space-between">
                            <Text size="sm" fw={600}>{String(row.answer_type ?? t("sliceUnknownLabel"))}</Text>
                            <Badge variant="light">{String(row.left_question_count ?? 0)} / {String(row.right_question_count ?? 0)}</Badge>
                          </Group>
                          <SimpleGrid cols={{ base: 2, md: 2 }}>
                            <Text size="xs">{t("metricOverallDelta")}: {formatDeltaValue(row.overall_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricGroundingDelta")}: {formatDeltaValue(row.grounding_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricAnswerDelta")}: {formatDeltaValue(row.answer_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricTtftDelta")}: {formatDeltaValue(row.ttft_factor_mean_delta)}</Text>
                          </SimpleGrid>
                        </Paper>
                      ))}
                    </Stack>
                  </Paper>
                  <Paper withBorder p="sm">
                    <Stack gap="xs">
                      <Text size="sm" fw={700}>{t("sliceByRouteFamily")}</Text>
                      {evalCompareByRouteFamily.length === 0 && <Text size="sm" c="dimmed">{t("stateEmpty")}</Text>}
                      {evalCompareByRouteFamily.map((row, index) => (
                        <Paper key={`eval-compare-route-${index}`} withBorder p="xs">
                          <Group justify="space-between">
                            <Text size="sm" fw={600}>{String(row.route_family ?? t("sliceUnknownLabel"))}</Text>
                            <Badge variant="light">{String(row.left_question_count ?? 0)} / {String(row.right_question_count ?? 0)}</Badge>
                          </Group>
                          <SimpleGrid cols={{ base: 2, md: 2 }}>
                            <Text size="xs">{t("metricOverallDelta")}: {formatDeltaValue(row.overall_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricGroundingDelta")}: {formatDeltaValue(row.grounding_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricAnswerDelta")}: {formatDeltaValue(row.answer_score_mean_delta)}</Text>
                            <Text size="xs">{t("metricTelemetryDelta")}: {formatDeltaValue(row.telemetry_factor_mean_delta)}</Text>
                          </SimpleGrid>
                        </Paper>
                      ))}
                    </Stack>
                  </Paper>
                </SimpleGrid>
                <SectionCard title={t("sectionValueReport")}>
                  <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
                    <ValueReportPanel title={t("valueByAnswerType")} rows={evalCompareValueByAnswerType} labelField="answer_type" compare />
                    <ValueReportPanel title={t("valueByRouteFamily")} rows={evalCompareValueByRouteFamily} labelField="route_family" compare />
                    <ValueReportPanel title={t("valueByAnswerability")} rows={evalCompareValueByAnswerability} labelField="answerability" compare />
                    <ValueReportPanel title={t("valueByDocumentScope")} rows={evalCompareValueByDocumentScope} labelField="document_scope" compare />
                    <ValueReportPanel title={t("valueByCorpusDomain")} rows={evalCompareValueByCorpusDomain} labelField="corpus_domain" compare />
                    <ValueReportPanel title={t("valueByTemporalScope")} rows={evalCompareValueByTemporalScope} labelField="temporal_scope" compare />
                  </SimpleGrid>
                </SectionCard>
                <SectionCard title={t("sectionTopRegressions")}>
                  <Stack gap="sm">
                    {evalCompareTopRegressions.map((row, index) => (
                      <Paper key={`eval-compare-reg-${index}`} withBorder p="xs">
                        <Group justify="space-between">
                          <Text size="sm">{String(row.question_id ?? t("unknownQuestionId"))}</Text>
                          <Badge color={metricBadgeColor(Number(row.delta ?? 0))}>{formatDeltaValue(row.delta)}</Badge>
                        </Group>
                      </Paper>
                    ))}
                    {evalCompareTopRegressions.length === 0 && <Text size="sm" c="dimmed">{t("stateEmpty")}</Text>}
                  </Stack>
                </SectionCard>
              </Stack>
            )}
          </Stack>
        </SectionCard>

        {evalSlicesState.loading && <Text size="sm" c="dimmed">{t("stateLoading")}</Text>}
        {evalSlicesState.error && <Alert color="red">{`${t("stateError")}: ${evalSlicesState.error}`}</Alert>}
        {evalSlicesState.partial && !evalSlicesState.error && <Alert color="yellow">{`${t("statePartial")}: ${evalSlicesState.partial}`}</Alert>}
        {!evalRunData && !evalSlicesState.loading && (
          <EmptyState title={t("evaluationEmptyTitle")} description={t("evaluationEmptySubtitle")} />
        )}

        {evalRunData && (
          <Stack gap="lg">
            <SimpleGrid cols={{ base: 1, sm: 2, xl: 5 }}>
              <MetricCard label={t("metricOverallScore")} value={formatMetricValue((evalMetrics as any)?.overall_score)} />
              <MetricCard label={t("metricAnswerScore")} value={formatMetricValue((evalMetrics as any)?.answer_score_mean)} />
              <MetricCard label={t("metricGroundingScore")} value={formatMetricValue((evalMetrics as any)?.grounding_score_mean)} />
              <MetricCard label={t("metricTelemetryFactor")} value={formatMetricValue((evalMetrics as any)?.telemetry_factor)} />
              <MetricCard label={t("metricTtftFactor")} value={formatMetricValue((evalMetrics as any)?.ttft_factor)} />
            </SimpleGrid>

            <SectionCard title={t("evaluationSlicesTitle")} action={
              <Button variant="subtle" size="xs" onClick={() => openDebug(t("evaluationDebugTitle"), evalRunData)}>
                {t("actionOpenDebug")}
              </Button>
            }>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Paper withBorder p="sm">
                  <Stack gap="xs">
                    <Text size="sm" fw={700}>
                      {t("sliceByAnswerType")}
                    </Text>
                    {evalSliceByAnswerType.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                    {evalSliceByAnswerType.map((row, index) => (
                      <Paper key={`eval-answer-${index}`} withBorder p="xs">
                        <Group justify="space-between">
                          <Text size="sm" fw={600}>
                            {String(row.answer_type ?? t("sliceUnknownLabel"))}
                          </Text>
                          <Badge variant="light">{String(row.question_count ?? 0)}</Badge>
                        </Group>
                        <Text size="xs">{t("metricOverallScore")}: {formatMetricValue(row.overall_score_mean)}</Text>
                      </Paper>
                    ))}
                  </Stack>
                </Paper>
                <Paper withBorder p="sm">
                  <Stack gap="xs">
                    <Text size="sm" fw={700}>
                      {t("sliceByRouteFamily")}
                    </Text>
                    {evalSliceByRouteFamily.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                    {evalSliceByRouteFamily.map((row, index) => (
                      <Paper key={`eval-route-${index}`} withBorder p="xs">
                        <Group justify="space-between">
                          <Text size="sm" fw={600}>
                            {String(row.route_family ?? t("sliceUnknownLabel"))}
                          </Text>
                          <Badge variant="light">{String(row.question_count ?? 0)}</Badge>
                        </Group>
                        <Text size="xs">{t("metricGroundingScore")}: {formatMetricValue(row.grounding_score_mean)}</Text>
                      </Paper>
                    ))}
                  </Stack>
                </Paper>
              </SimpleGrid>
            </SectionCard>

            <Grid gutter="lg">
              <Grid.Col span={{ base: 12, md: 6 }}>
                <SectionCard title={t("sectionValueReport")}>
                  <SimpleGrid cols={{ base: 1, xl: 2 }}>
                    <ValueReportPanel title={t("valueByAnswerType")} rows={evalValueByAnswerType} labelField="answer_type" />
                    <ValueReportPanel title={t("valueByRouteFamily")} rows={evalValueByRouteFamily} labelField="route_family" />
                    <ValueReportPanel title={t("valueByAnswerability")} rows={evalValueByAnswerability} labelField="answerability" />
                    <ValueReportPanel title={t("valueByDocumentScope")} rows={evalValueByDocumentScope} labelField="document_scope" />
                    <ValueReportPanel title={t("valueByCorpusDomain")} rows={evalValueByCorpusDomain} labelField="corpus_domain" />
                    <ValueReportPanel title={t("valueByTemporalScope")} rows={evalValueByTemporalScope} labelField="temporal_scope" />
                  </SimpleGrid>
                </SectionCard>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6 }}>
                <SectionCard title={t("sectionTopRegressions")}>
                  <Stack gap="sm">
                    {evalTopRegressions.map((row, index) => (
                      <Paper key={`eval-reg-${index}`} withBorder p="xs">
                        <Group justify="space-between">
                          <Text size="sm">{String(row.question_id ?? t("unknownQuestionId"))}</Text>
                          <Badge color={metricBadgeColor(Number((row.overall_score ?? row.overall_proxy) ?? 0))}>
                            {formatMetricValue(row.overall_score ?? row.overall_proxy)}
                          </Badge>
                        </Group>
                      </Paper>
                    ))}
                    {evalTopRegressions.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                    {evalReportItems.length > 0 && (
                    <Button variant="light" onClick={() => navigate("review-runs")}>
                      {t("actionOpenReview")}
                    </Button>
                    )}
                  </Stack>
                </SectionCard>
              </Grid.Col>
            </Grid>
          </Stack>
        )}
      </Stack>
    );
  }

  function renderExperimentsScreen() {
    return (
      <Tabs defaultValue="profiles" variant="outline">
        <Tabs.List>
          <Tabs.Tab value="profiles">{t("experimentsTabProfiles")}</Tabs.Tab>
          <Tabs.Tab value="experiments">{t("experimentsTabExperiments")}</Tabs.Tab>
          <Tabs.Tab value="compare">{t("experimentsTabCompare")}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="profiles" pt="md">
          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, xl: 6 }}>
              <SectionCard title={t("sectionExperimentProfiles")} description={t("experimentsProfilesSubtitle")}>
                <SimpleGrid cols={{ base: 1, md: 2 }}>
                  <TextInput label={t("experimentProfileName")} value={expProfileName} onChange={(event) => setExpProfileName(event.currentTarget.value)} />
                  <TextInput label={t("datasetId")} value={datasetId} onChange={(event) => setActiveDatasetId(event.currentTarget.value)} />
                  <TextInput label={t("datasetIdGold")} value={goldDatasetId} onChange={(event) => setActiveGoldDatasetId(event.currentTarget.value)} />
                  <TextInput label={t("experimentListLimit")} value={expListLimit} onChange={(event) => setExpListLimit(event.currentTarget.value)} />
                </SimpleGrid>
                <Group>
                  <Button loading={isActionLoading("createExperimentProfile")} onClick={() => createExperimentProfile()}>
                    {t("actionCreateExperimentProfile")}
                  </Button>
                  <Button variant="light" loading={isActionLoading("listExperimentProfiles")} onClick={() => listExperimentProfiles()}>
                    {t("actionListExperimentProfiles")}
                  </Button>
                </Group>
              </SectionCard>
            </Grid.Col>
            <Grid.Col span={{ base: 12, xl: 6 }}>
              <SectionCard title={t("experimentsProfilesListTitle")}>
                <Stack gap="sm">
                  {experimentProfiles.length === 0 && (
                    <Text size="sm" c="dimmed">
                      {t("stateEmpty")}
                    </Text>
                  )}
                  {experimentProfiles.map((profile, index) => (
                    <Paper key={String(profile.profile_id ?? index)} withBorder p="sm">
                      <Group justify="space-between">
                        <Stack gap={2}>
                          <Text size="sm" fw={600}>
                            {String(profile.name ?? profile.profile_id ?? "-")}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {String(profile.profile_id ?? "-")}
                          </Text>
                        </Stack>
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => setExpProfileId(String(profile.profile_id ?? ""))}
                        >
                          {t("actionSetActive")}
                        </Button>
                      </Group>
                    </Paper>
                  ))}
                </Stack>
              </SectionCard>
            </Grid.Col>
          </Grid>
        </Tabs.Panel>

        <Tabs.Panel value="experiments" pt="md">
          <Stack gap="lg">
            <SectionCard title={t("sectionExperimentComposer")} description={t("experimentsComposerSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                <TextInput label={t("experimentProfileId")} value={expProfileId} onChange={(event) => setExpProfileId(event.currentTarget.value)} />
                <TextInput label={t("experimentName")} value={experimentName} onChange={(event) => setExperimentName(event.currentTarget.value)} />
                <TextInput label={t("experimentId")} value={experimentId} onChange={(event) => setExperimentId(event.currentTarget.value)} />
              </SimpleGrid>
              <Group>
                <Button loading={isActionLoading("createExperiment")} onClick={() => createExperiment()}>
                  {t("actionCreateExperiment")}
                </Button>
                <Button variant="light" loading={isActionLoading("getExperiment")} onClick={() => getExperiment()}>
                  {t("actionGetExperiment")}
                </Button>
              </Group>
            </SectionCard>

            <SectionCard title={t("sectionExperimentRuns")} description={t("experimentsRunsSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 4 }}>
                <TextInput label={t("experimentId")} value={experimentId} onChange={(event) => setExperimentId(event.currentTarget.value)} />
                <Select
                  label={t("experimentStageMode")}
                  value={experimentStageMode}
                  onChange={(value) => setExperimentStageMode(value || "auto")}
                  data={[
                    { value: "auto", label: "auto" },
                    { value: "proxy", label: "proxy" },
                    { value: "full", label: "full" },
                  ]}
                />
                <TextInput
                  label={t("experimentProxySampleSize")}
                  value={experimentProxySampleSize}
                  onChange={(event) => setExperimentProxySampleSize(event.currentTarget.value)}
                />
                <TextInput
                  label={t("experimentRunId")}
                  value={experimentRunId}
                  onChange={(event) => setExperimentRunId(event.currentTarget.value)}
                />
              </SimpleGrid>
              <Group>
                <Button loading={isActionLoading("runExperiment")} onClick={() => runExperiment()}>
                  {t("actionRunExperiment")}
                </Button>
                <Button variant="light" loading={isActionLoading("getExperimentRun")} onClick={() => getExperimentRun()}>
                  {t("actionGetExperimentRun")}
                </Button>
                <Button variant="light" loading={isActionLoading("getExperimentAnalysis")} onClick={() => getExperimentAnalysis()}>
                  {t("actionGetExperimentAnalysis")}
                </Button>
              </Group>
              <SimpleGrid cols={{ base: 1, sm: 3 }}>
                <MetricCard label={t("experimentId")} value={experimentId || "-"} />
                <MetricCard label={t("experimentRunId")} value={experimentRunId || "-"} />
                <MetricCard label={t("experimentStageMode")} value={experimentStageMode} />
              </SimpleGrid>
            </SectionCard>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="compare" pt="md">
          <Stack gap="lg">
            <SectionCard title={t("sectionExperimentCompare")} description={t("experimentsCompareSubtitle")}>
              <SimpleGrid cols={{ base: 1, md: 3 }}>
                <TextInput label={t("experimentLeftRunId")} value={compareLeftRunId} onChange={(event) => setCompareLeftRunId(event.currentTarget.value)} />
                <TextInput label={t("experimentRightRunId")} value={compareRightRunId} onChange={(event) => setCompareRightRunId(event.currentTarget.value)} />
                <Group align="flex-end">
                  <Button loading={experimentCompareState.loading} onClick={() => loadExperimentCompareConsoleView()}>
                    {t("actionCompareExperiments")}
                  </Button>
                  <Button variant="light" loading={isActionLoading("getLeaderboard")} onClick={() => loadExperimentLeaderboard()}>
                    {t("actionGetLeaderboard")}
                  </Button>
                </Group>
              </SimpleGrid>
            </SectionCard>

            {experimentCompareState.loading && <Text size="sm" c="dimmed">{t("stateLoading")}</Text>}
            {experimentCompareState.error && <Alert color="red">{`${t("stateError")}: ${experimentCompareState.error}`}</Alert>}
            {experimentCompareState.partial && !experimentCompareState.error && (
              <Alert color="yellow">{`${t("statePartial")}: ${experimentCompareState.partial}`}</Alert>
            )}
            {!experimentCompareState.loading && !experimentCompareState.error && !experimentCompareData && (
              <EmptyState title={t("experimentsCompareEmptyTitle")} description={t("experimentsCompareEmptySubtitle")} />
            )}

            {experimentCompareData && (
              <Stack gap="lg">
                <SimpleGrid cols={{ base: 1, sm: 2, xl: 5 }}>
                  {Object.entries(experimentMetricDeltas).map(([metric, value]) => (
                    <MetricCard key={metric} label={metricDeltaLabel(metric)} value={formatDeltaValue(value)} />
                  ))}
                </SimpleGrid>

                <Grid gutter="lg">
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <SectionCard title={t("sliceByAnswerType")}>
                      <Stack gap="sm">
                        {experimentCompareByAnswerType.map((row, index) => (
                          <Paper key={`compare-answer-${index}`} withBorder p="xs">
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>
                                {String(row.answer_type ?? t("sliceUnknownLabel"))}
                              </Text>
                              <Badge variant="light">
                                {String(row.left_question_count ?? 0)} / {String(row.right_question_count ?? 0)}
                              </Badge>
                            </Group>
                            <Text size="xs">{t("metricOverallDelta")}: {formatDeltaValue(row.overall_score_mean_delta)}</Text>
                          </Paper>
                        ))}
                        {experimentCompareByAnswerType.length === 0 && (
                          <Text size="sm" c="dimmed">
                            {t("stateEmpty")}
                          </Text>
                        )}
                      </Stack>
                    </SectionCard>
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <SectionCard title={t("sliceByRouteFamily")}>
                      <Stack gap="sm">
                        {experimentCompareByRouteFamily.map((row, index) => (
                          <Paper key={`compare-route-${index}`} withBorder p="xs">
                            <Group justify="space-between">
                              <Text size="sm" fw={600}>
                                {String(row.route_family ?? t("sliceUnknownLabel"))}
                              </Text>
                              <Badge variant="light">
                                {String(row.left_question_count ?? 0)} / {String(row.right_question_count ?? 0)}
                              </Badge>
                            </Group>
                            <Text size="xs">{t("metricGroundingDelta")}: {formatDeltaValue(row.grounding_score_mean_delta)}</Text>
                          </Paper>
                        ))}
                        {experimentCompareByRouteFamily.length === 0 && (
                          <Text size="sm" c="dimmed">
                            {t("stateEmpty")}
                          </Text>
                        )}
                      </Stack>
                    </SectionCard>
                  </Grid.Col>
                </Grid>

                <SectionCard title={t("sectionValueReport")}>
                  <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
                    <ValueReportPanel title={t("valueByAnswerType")} rows={experimentCompareValueByAnswerType} labelField="answer_type" compare />
                    <ValueReportPanel title={t("valueByRouteFamily")} rows={experimentCompareValueByRouteFamily} labelField="route_family" compare />
                    <ValueReportPanel title={t("valueByAnswerability")} rows={experimentCompareValueByAnswerability} labelField="answerability" compare />
                    <ValueReportPanel title={t("valueByDocumentScope")} rows={experimentCompareValueByDocumentScope} labelField="document_scope" compare />
                    <ValueReportPanel title={t("valueByCorpusDomain")} rows={experimentCompareValueByCorpusDomain} labelField="corpus_domain" compare />
                    <ValueReportPanel title={t("valueByTemporalScope")} rows={experimentCompareValueByTemporalScope} labelField="temporal_scope" compare />
                  </SimpleGrid>
                </SectionCard>

                <SectionCard title={t("sectionTopRegressions")}>
                  <Stack gap="sm">
                    {experimentTopRegressions.map((row, index) => (
                      <Paper key={`exp-reg-${index}`} withBorder p="xs">
                        <Group justify="space-between">
                          <Text size="sm">{String(row.question_id ?? t("unknownQuestionId"))}</Text>
                          <Badge color={metricBadgeColor(Number(row.delta ?? 0))}>{formatDeltaValue(row.delta)}</Badge>
                        </Group>
                      </Paper>
                    ))}
                    {experimentTopRegressions.length === 0 && (
                      <Text size="sm" c="dimmed">
                        {t("stateEmpty")}
                      </Text>
                    )}
                  </Stack>
                </SectionCard>
              </Stack>
            )}

            <SectionCard title={t("experimentsLeaderboardTitle")}>
              <Stack gap="sm">
                {experimentLeaderboard.map((item, index) => (
                  <Paper key={`leaderboard-${index}`} withBorder p="xs">
                    <Group justify="space-between">
                      <Text size="sm" fw={600}>
                        {String(item.experiment_name ?? item.experiment_id ?? "-")}
                      </Text>
                      <Badge variant="light">{formatMetricValue(item.overall_score ?? item.score)}</Badge>
                    </Group>
                  </Paper>
                ))}
                {experimentLeaderboard.length === 0 && (
                  <Text size="sm" c="dimmed">
                    {t("stateEmpty")}
                  </Text>
                )}
              </Stack>
            </SectionCard>
          </Stack>
        </Tabs.Panel>
      </Tabs>
    );
  }

  function renderGoldScreen() {
    return (
      <Stack gap="lg">
        <SectionCard title={t("sectionDatasetOps")} description={t("goldDatasetSubtitle")}>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <TextInput label={t("goldDatasetName")} value={goldDatasetName} onChange={(event) => setGoldDatasetName(event.currentTarget.value)} />
            <TextInput label={t("goldDatasetVersion")} value={goldDatasetVersion} onChange={(event) => setGoldDatasetVersion(event.currentTarget.value)} />
          </SimpleGrid>
          <Group>
            <Button loading={isActionLoading("createGoldDataset")} onClick={() => createGoldDataset()}>
              {t("actionCreateGoldDataset")}
            </Button>
            <Button variant="light" loading={isActionLoading("lockGoldDataset")} onClick={() => lockGoldDataset()}>
              {t("actionLockGoldDataset")}
            </Button>
            <Button variant="light" loading={isActionLoading("exportGoldDataset")} onClick={() => exportGoldDataset()}>
              {t("actionExportGoldDataset")}
            </Button>
          </Group>
        </SectionCard>

        <SectionCard title={t("sectionQuestionOps")} description={t("goldQuestionSubtitle")}>
          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <TextInput label={t("datasetId")} value={goldDatasetId} onChange={(event) => setActiveGoldDatasetId(event.currentTarget.value)} />
            <TextInput label={t("canonicalAnswer")} value={canonicalAnswer} onChange={(event) => setCanonicalAnswer(event.currentTarget.value)} />
            <TextInput label={t("sourcePageIds")} value={sourcePageIds} onChange={(event) => setSourcePageIds(event.currentTarget.value)} />
          </SimpleGrid>
          <Group>
            <Button loading={isActionLoading("createGoldQuestion")} onClick={() => createGoldQuestion()}>
              {t("actionCreateGoldQuestion")}
            </Button>
          </Group>
        </SectionCard>
      </Stack>
    );
  }

  function renderSyntheticScreen() {
    return (
      <Stack gap="lg">
        <SectionCard title={t("sectionSynthJob")} description={t("synthJobSubtitle")}>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <TextInput label={t("synthTargetCount")} value={synthTargetCount} onChange={(event) => setSynthTargetCount(event.currentTarget.value)} />
            <TextInput label={t("synthJobId")} value={synthJobId} onChange={(event) => setSynthJobId(event.currentTarget.value)} />
          </SimpleGrid>
          <Group>
            <Button loading={isActionLoading("createSynthJob")} onClick={() => createSynthJob()}>
              {t("actionCreateSynthJob")}
            </Button>
            <Button variant="light" loading={isActionLoading("previewSynth")} onClick={() => previewSynth()}>
              {t("actionPreviewSynth")}
            </Button>
            <Button variant="light" loading={isActionLoading("publishSynth")} onClick={() => publishSynth()}>
              {t("actionPublishSynth")}
            </Button>
          </Group>
        </SectionCard>
      </Stack>
    );
  }

  function renderConfigScreen() {
    return (
      <Stack gap="lg">
        <SectionCard title={t("configHealthTitle")} description={t("configHealthSubtitle")}>
          <Group>
            <Button loading={isActionLoading("health")} onClick={() => loadHealth()}>
              {t("actionPing")}
            </Button>
            <Button variant="light" loading={isActionLoading("listPolicies")} onClick={() => loadPolicies()}>
              {t("actionListPolicies")}
            </Button>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2, xl: 4 }}>
            <MetricCard label={t("configBackendStatus")} value={healthData ? t("configBackendHealthy") : t("configBackendUnknown")} />
            <MetricCard label={t("projectId")} value={projectId || "-"} />
            <MetricCard label={t("datasetId")} value={datasetId || "-"} />
            <MetricCard label={t("datasetIdGold")} value={goldDatasetId || "-"} />
          </SimpleGrid>
        </SectionCard>

        <SectionCard title={t("configPoliciesTitle")} description={t("configPoliciesSubtitle")}>
          {!policiesData && (
            <Text size="sm" c="dimmed">
              {t("stateEmpty")}
            </Text>
          )}
          {policiesData && (
            <Stack gap="sm">
              <SnapshotRow label={t("configPoliciesLoaded")} value={Object.keys(policiesData).length} />
              <Button variant="subtle" size="xs" onClick={() => openDebug(t("configDebugTitle"), policiesData)}>
                {t("actionOpenDebug")}
              </Button>
            </Stack>
          )}
        </SectionCard>
      </Stack>
    );
  }

  function renderSectionContent() {
    if (activeSection === "projects") return renderProjectsScreen();
    if (activeSection === "overview") return renderOverviewScreen();
    if (activeSection === "corpus") return renderCorpusScreen();
    if (activeSection === "datasets") return renderDatasetsScreen();
    if (activeSection === "review-runs") return renderReviewRunsScreen();
    if (activeSection === "evaluation") return renderEvaluationScreen();
    if (activeSection === "experiments") return renderExperimentsScreen();
    if (activeSection === "gold") return renderGoldScreen();
    if (activeSection === "synthetic") return renderSyntheticScreen();
    return renderConfigScreen();
  }

  return (
    <>
      <Drawer
        opened={jobCenterOpened}
        onClose={() => setJobCenterOpened(false)}
        position="right"
        size="md"
        title={t("jobCenterTitle")}
      >
        <Stack gap="sm">
          {activityLog.length === 0 && (
            <Text size="sm" c="dimmed">
              {t("jobCenterEmpty")}
            </Text>
          )}
          {activityLog.map((item) => (
            <Paper key={item.id} withBorder p="sm">
              <Stack gap={6}>
                <Group justify="space-between">
                  <Text size="sm" fw={600}>
                    {item.label}
                  </Text>
                  <StatusBadge label={processingStatusLabel(item.status)} color={activityStatusColor(item.status)} />
                </Group>
                <Text size="xs" c="dimmed">
                  {new Date(item.timestamp).toLocaleString()}
                </Text>
                {item.artifactId && (
                  <Text size="xs" c="dimmed">
                    {t("activityArtifact")}: {item.artifactId}
                  </Text>
                )}
                {item.detail && (
                  <Text size="xs" c="red">
                    {item.detail}
                  </Text>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      </Drawer>

      <Drawer
        opened={debugOpened}
        onClose={() => setDebugOpened(false)}
        position="right"
        size="lg"
        title={debugTitle}
      >
        <Code block className="debug-code">
          {lastPayload === null ? t("debugEmpty") : pretty(lastPayload)}
        </Code>
      </Drawer>

      <AppShell
        padding={0}
        navbar={{ width: 292, breakpoint: "sm", collapsed: { mobile: !navOpened } }}
        header={{ height: 92 }}
      >
        <AppShell.Header className="app-header">
          <div className="app-header-inner">
            <Group align="flex-start" gap="md" wrap="wrap" className="header-primary">
              <Burger opened={navOpened} onClick={() => setNavOpened((opened) => !opened)} hiddenFrom="sm" size="sm" />
              <Box className="brand-block">
                <Text size="xs" fw={700} c="dimmed">
                  {t("appEyebrow")}
                </Text>
                <Title order={2} className="brand-title">
                  {t("appTitle")}
                </Title>
                <Text size="sm" c="dimmed">
                  {t("appSubtitle")}
                </Text>
              </Box>
            </Group>

            <Group gap="sm" wrap="wrap" className="header-actions">
              <Badge variant="outline">
                {t("projectsPanelTitle")}: {activeProjectWorkspace.label}
              </Badge>
              <Badge variant="outline">
                {t("corpusShortLabel")}: {displayValue(corpusLabel)}
              </Badge>
              <Badge variant="outline">
                {t("datasetShortLabel")}: {displayValue(datasetLabel, datasetId)}
              </Badge>
              <Badge variant="outline" color={readinessColor}>
                {readinessLabel}
              </Badge>
              <Button variant="light" onClick={() => setJobCenterOpened(true)}>
                {t("actionOpenJobs")} ({activityLog.filter((item) => item.status === "processing").length})
              </Button>
              <Button variant="subtle" onClick={() => setDebugOpened(true)}>
                {t("actionOpenDebug")}
              </Button>
            </Group>
          </div>
        </AppShell.Header>

        <AppShell.Navbar className="app-navbar">
          <div className="app-navbar-inner">
            <Paper withBorder p="md" className="nav-context-card">
              <Stack gap="xs">
                <Text fw={700}>{activeProjectWorkspace.label}</Text>
                <Text size="xs" c="dimmed">
                  {projectId || t("projectIdEmpty")}
                </Text>
                <Group gap={6} wrap="wrap">
                  <Badge variant="outline">{t("corpusShortLabel")}: {displayValue(corpusLabel)}</Badge>
                  <Badge variant="outline">{t("datasetShortLabel")}: {displayValue(datasetLabel, datasetId)}</Badge>
                  <Badge variant="outline">{t("qaShortLabel")}: {displayValue(questionId)}</Badge>
                </Group>
                <Progress value={validationItems.some((item) => item.level === "error") ? 35 : runId ? (evalRunId ? 100 : 70) : 45} />
              </Stack>
            </Paper>

            <ScrollArea className="nav-scroll">
              <Stack gap={6} mt="md">
                {navItems.map((item) => (
                  <NavLink
                    key={item.key}
                    active={activeSection === item.key}
                    onClick={() => navigate(item.key)}
                    label={item.label}
                    leftSection={
                      <ThemeIcon variant="light" size="sm">
                        <item.icon size={16} />
                      </ThemeIcon>
                    }
                  />
                ))}
              </Stack>
            </ScrollArea>
          </div>
        </AppShell.Navbar>

        <AppShell.Main className="app-main">
          <div className="section-header">
            <Group justify="space-between" align="center" wrap="wrap">
              <Stack gap={2}>
                <Text size="xs" fw={700} c="dimmed">
                  {t("activeProjectLabel")}
                </Text>
                <Title order={3}>{navItems.find((item) => item.key === activeSection)?.label}</Title>
              </Stack>
              <Group gap="sm" wrap="wrap">
                <StatusBadge label={healthData ? t("configBackendHealthy") : t("configBackendUnknown")} color={healthData ? "green" : "gray"} />
                <StatusBadge label={readinessLabel} color={readinessColor} />
              </Group>
            </Group>
          </div>
          <div className="section-body">{renderSectionContent()}</div>
        </AppShell.Main>
      </AppShell>
    </>
  );
}
