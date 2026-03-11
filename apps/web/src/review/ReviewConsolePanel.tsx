import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Grid, Group, Loader, Paper, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import type { createApi } from "../api";
import { t } from "../i18n";
import type { ReviewCandidate, ReviewEvidenceRef, ReviewFilters, ReviewPdfPreview, ReviewRecord, ReviewSummary } from "./types";
import { ReviewQuestionList } from "./ReviewQuestionList";
import { CandidateAnswerCards } from "./CandidateAnswerCards";
import { EvidenceTable } from "./EvidenceTable";
import { PdfPreviewPane } from "./PdfPreviewPane";
import { DecisionPanel } from "./DecisionPanel";
import { TraceTabs } from "./TraceTabs";
import { RunReportDrawer } from "./RunReportDrawer";

type ReviewConsolePanelProps = {
  api: ReturnType<typeof createApi>;
  apiBase: string;
  runId: string;
  questionId: string;
  goldDatasetId: string;
  onRunIdChange: (value: string) => void;
  onQuestionIdChange: (value: string) => void;
  onGoldDatasetIdChange: (value: string) => void;
  onRecordLoaded: (record: Record<string, unknown> | null) => void;
  onOpenDebug: (title: string, payload: unknown) => void;
  onSyncPath: (questionId?: string) => void;
};

const initialFilters: ReviewFilters = {
  route: "",
  answer_type: "",
  status: "",
  disagreement_only: false,
  needs_review_only: false,
  gold_locked_only: false,
  no_answer_only: false,
  missing_sources_only: false,
  contract_failures_only: false,
  search: "",
};

type ViewState = {
  loading: boolean;
  error: string;
};

export function ReviewConsolePanel(props: ReviewConsolePanelProps) {
  const [listState, setListState] = useState<ViewState>({ loading: false, error: "" });
  const [detailState, setDetailState] = useState<ViewState>({ loading: false, error: "" });
  const [reviewRecords, setReviewRecords] = useState<ReviewRecord[]>([]);
  const [selectedRecord, setSelectedRecord] = useState<ReviewRecord | null>(null);
  const [reviewSummary, setReviewSummary] = useState<ReviewSummary | null>(null);
  const [reviewPdfPreview, setReviewPdfPreview] = useState<ReviewPdfPreview | null>(null);
  const [reviewReportPayload, setReviewReportPayload] = useState<Record<string, unknown> | null>(null);
  const [reportDrawerOpened, setReportDrawerOpened] = useState(false);
  const [filters, setFilters] = useState<ReviewFilters>(initialFilters);
  const [reviewer, setReviewer] = useState("ui");
  const [reviewerConfidence, setReviewerConfidence] = useState("0.8");
  const [customAnswer, setCustomAnswer] = useState("");
  const [customAnswerability, setCustomAnswerability] = useState("answerable");
  const [adjudicationNote, setAdjudicationNote] = useState("");
  const [strongRunId, setStrongRunId] = useState("");
  const [challengerRunId, setChallengerRunId] = useState("");
  const [strongProfileId, setStrongProfileId] = useState("");
  const [challengerProfileId, setChallengerProfileId] = useState("");

  const routeOptions = useMemo(
    () => Array.from(new Set(reviewRecords.map((record) => record.primary_route).filter(Boolean) as string[])).sort(),
    [reviewRecords]
  );
  const answerTypeOptions = useMemo(
    () => Array.from(new Set(reviewRecords.map((record) => record.answer_type).filter(Boolean))).sort(),
    [reviewRecords]
  );
  const statusOptions = useMemo(
    () => Array.from(new Set(reviewRecords.map((record) => record.status).filter(Boolean))).sort(),
    [reviewRecords]
  );
  const flattenedEvidence = useMemo<ReviewEvidenceRef[]>(
    () =>
      Array.from(
        new Map(
          (selectedRecord?.candidate_bundle ?? [])
            .flatMap((candidate) => candidate.sources)
            .map((source) => [`${source.source_page_id || source.doc_id}-${source.page_number}`, source])
        ).values()
      ),
    [selectedRecord]
  );

  async function loadReviewList(nextQuestionId?: string): Promise<void> {
    if (!props.runId.trim()) {
      return;
    }
    setListState({ loading: true, error: "" });
    try {
      const result = await props.api.listReviewQuestions(props.runId, filters);
      const items = Array.isArray((result as any)?.items) ? (((result as any).items as ReviewRecord[])) : [];
      setReviewRecords(items);
      setReviewSummary(((result as any)?.summary ?? null) as ReviewSummary | null);
      setReviewReportPayload(result);
      const preferredQuestionId = nextQuestionId || props.questionId || items[0]?.question_id || "";
      if (preferredQuestionId) {
        await loadReviewRecord(preferredQuestionId, false);
      } else {
        setSelectedRecord(null);
        props.onRecordLoaded(null);
      }
      setListState({ loading: false, error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setListState({ loading: false, error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function loadReviewRecord(nextQuestionId: string, syncPath = true): Promise<void> {
    if (!props.runId.trim() || !nextQuestionId.trim()) {
      return;
    }
    props.onQuestionIdChange(nextQuestionId);
    setDetailState({ loading: true, error: "" });
    try {
      const result = await props.api.getReviewQuestion(props.runId, nextQuestionId);
      const record = result as ReviewRecord;
      setSelectedRecord(record);
      props.onRecordLoaded(result);
      if (syncPath) {
        props.onSyncPath(nextQuestionId);
      }
      setCustomAnswer(record.accepted_decision?.final_answer == null ? "" : String(record.accepted_decision.final_answer));
      setCustomAnswerability(record.accepted_decision?.answerability || "answerable");
      setAdjudicationNote(record.accepted_decision?.adjudication_note || "");
      await loadPdfPreview(nextQuestionId);
      setDetailState({ loading: false, error: "" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setDetailState({ loading: false, error: message });
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function loadPdfPreview(nextQuestionId: string, documentId?: string, pageId?: string): Promise<void> {
    if (!props.runId.trim() || !nextQuestionId.trim()) {
      return;
    }
    try {
      const result = await props.api.getReviewPdfPreview(props.runId, nextQuestionId, documentId, pageId);
      setReviewPdfPreview(result as ReviewPdfPreview);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  useEffect(() => {
    if (!props.runId.trim()) {
      return;
    }
    void loadReviewList();
  }, [filters, props.runId]);

  async function runGenerateCandidates(): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const result = await props.api.generateReviewCandidates(props.runId, selectedRecord.question_id, {
        reviewer,
        strong_run_id: strongRunId,
        challenger_run_id: challengerRunId,
        strong_profile_id: strongProfileId,
        challenger_profile_id: challengerProfileId,
      });
      const record = ((result as any)?.record ?? null) as ReviewRecord | null;
      if (record) {
        setSelectedRecord(record);
        props.onRecordLoaded(record as unknown as Record<string, unknown>);
      }
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewCandidatesUpdated") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function runMiniCheck(evidence: ReviewEvidenceRef[]): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const systemCandidate = selectedRecord.candidate_bundle.find((candidate) => candidate.candidate_kind === "system");
      const result = await props.api.runReviewMiniCheck(props.runId, selectedRecord.question_id, {
        reviewer,
        candidate_kind: "system",
        candidate_answer: systemCandidate?.answer ?? null,
        candidate_answerability: systemCandidate?.answerability ?? "answerable",
        answer_type: selectedRecord.answer_type,
        evidence,
      });
      const record = ((result as any)?.record ?? null) as ReviewRecord | null;
      if (record) {
        setSelectedRecord(record);
        props.onRecordLoaded(record as unknown as Record<string, unknown>);
      }
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewMiniCheckCompleted") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function acceptCandidate(candidateKind: ReviewCandidate["candidate_kind"]): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const result = await props.api.acceptReviewCandidate(props.runId, selectedRecord.question_id, {
        reviewer,
        candidate_kind: candidateKind,
        reviewer_confidence: reviewerConfidence ? Number(reviewerConfidence) : null,
        adjudication_note: adjudicationNote,
      });
      const record = result as ReviewRecord;
      setSelectedRecord(record);
      props.onRecordLoaded(record as unknown as Record<string, unknown>);
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewDecisionUpdated") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function saveCustomDecision(): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const result = await props.api.saveReviewCustomDecision(props.runId, selectedRecord.question_id, {
        reviewer,
        final_answer: customAnswer,
        answerability: customAnswerability,
        final_sources: flattenedEvidence.filter((item) => item.is_used !== false),
        reviewer_confidence: reviewerConfidence ? Number(reviewerConfidence) : null,
        adjudication_note: adjudicationNote,
      });
      const record = result as ReviewRecord;
      setSelectedRecord(record);
      props.onRecordLoaded(record as unknown as Record<string, unknown>);
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewCustomDecisionSaved") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function lockGold(): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const result = await props.api.lockReviewGold(props.runId, selectedRecord.question_id, {
        gold_dataset_id: props.goldDatasetId,
        reviewer,
        reviewer_confidence: reviewerConfidence ? Number(reviewerConfidence) : null,
        adjudication_note: adjudicationNote,
      });
      const record = result as ReviewRecord;
      setSelectedRecord(record);
      props.onRecordLoaded(record as unknown as Record<string, unknown>);
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewGoldLocked") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function unlockGold(): Promise<void> {
    if (!selectedRecord) {
      return;
    }
    try {
      const result = await props.api.unlockReviewGold(props.runId, selectedRecord.question_id, {
        gold_dataset_id: props.goldDatasetId,
        reviewer,
        adjudication_note: adjudicationNote,
      });
      const record = result as ReviewRecord;
      setSelectedRecord(record);
      props.onRecordLoaded(record as unknown as Record<string, unknown>);
      await loadReviewList(selectedRecord.question_id);
      notifications.show({ color: "green", message: t("reviewGoldUnlocked") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  async function exportReport(): Promise<void> {
    if (!props.runId.trim()) {
      return;
    }
    try {
      const result = await props.api.exportReviewReport(props.runId, { reviewer, format: "both" });
      setReviewReportPayload(result);
      setReportDrawerOpened(true);
      notifications.show({ color: "green", message: t("reviewReportExported") });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      notifications.show({ color: "red", message: message.slice(0, 180) });
    }
  }

  return (
    <Stack gap="lg">
      <Paper withBorder p="md">
        <SimpleGrid cols={{ base: 1, md: 3 }}>
          <TextInput label={t("runId")} value={props.runId} onChange={(event) => props.onRunIdChange(event.currentTarget.value)} />
          <TextInput label={t("questionId")} value={props.questionId} onChange={(event) => props.onQuestionIdChange(event.currentTarget.value)} />
          <TextInput
            label={t("datasetIdGold")}
            value={props.goldDatasetId}
            onChange={(event) => props.onGoldDatasetIdChange(event.currentTarget.value)}
          />
        </SimpleGrid>
        <Group mt="md">
          <Button onClick={() => void loadReviewList()}>{t("reviewLoadList")}</Button>
          <Button variant="light" onClick={() => void loadReviewRecord(props.questionId || selectedRecord?.question_id || "")}>
            {t("reviewLoadRecord")}
          </Button>
          <Button variant="subtle" onClick={() => props.onOpenDebug(t("reviewDebugTitle"), selectedRecord || reviewReportPayload)}>
            {t("actionOpenDebug")}
          </Button>
          <Button variant="light" onClick={() => setReportDrawerOpened(true)}>
            {t("reviewOpenReport")}
          </Button>
        </Group>
      </Paper>

      {listState.loading && <Loader size="sm" />}
      {listState.error && <Alert color="red">{listState.error}</Alert>}

      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, xl: 3 }}>
          <ReviewQuestionList
            records={reviewRecords}
            selectedQuestionId={selectedRecord?.question_id || props.questionId}
            filters={filters}
            routeOptions={routeOptions}
            answerTypeOptions={answerTypeOptions}
            statusOptions={statusOptions}
            onFiltersChange={setFilters}
            onSelectQuestion={(nextQuestionId) => void loadReviewRecord(nextQuestionId)}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 5 }}>
          <Stack gap="lg">
            {detailState.loading && <Loader size="sm" />}
            {detailState.error && <Alert color="red">{detailState.error}</Alert>}
            {!selectedRecord && !detailState.loading && (
              <Paper withBorder p="md">
                <Text size="sm" c="dimmed">
                  {t("reviewEmptySubtitle")}
                </Text>
              </Paper>
            )}
            {selectedRecord && (
              <>
                <Paper withBorder p="md">
                  <Stack gap="xs">
                    <Text fw={600}>{t("reviewQuestionTitle")}</Text>
                    <Text size="xs" c="dimmed">
                      {selectedRecord.question_id}
                    </Text>
                    <Text size="sm">{selectedRecord.question}</Text>
                    <Group gap="xs" wrap="wrap">
                      <Text size="xs" c="dimmed">{t("reviewRoute")}: {selectedRecord.primary_route || "-"}</Text>
                      <Text size="xs" c="dimmed">{t("reviewRiskTier")}: {selectedRecord.risk_tier || "-"}</Text>
                      <Text size="xs" c="dimmed">{t("reviewStatusLabel")}: {selectedRecord.status}</Text>
                    </Group>
                  </Stack>
                </Paper>
                <CandidateAnswerCards
                  candidates={selectedRecord.candidate_bundle}
                  acceptedDecisionSource={selectedRecord.accepted_decision?.decision_source}
                  onAcceptCandidate={(candidateKind) => void acceptCandidate(candidateKind)}
                />
                <EvidenceTable
                  evidence={flattenedEvidence}
                  selectedSourcePageId={reviewPdfPreview?.page.source_page_id || ""}
                  onPinToPdf={(sourcePageId) => {
                    const target = flattenedEvidence.find((item) => item.source_page_id === sourcePageId);
                    if (target) {
                      void loadPdfPreview(selectedRecord.question_id, target.doc_id, "");
                    }
                  }}
                  onSendToMiniCheck={(evidence) => void runMiniCheck(evidence)}
                />
                <DecisionPanel
                  goldDatasetId={props.goldDatasetId}
                  customAnswer={customAnswer}
                  customAnswerability={customAnswerability}
                  adjudicationNote={adjudicationNote}
                  reviewer={reviewer}
                  reviewerConfidence={reviewerConfidence}
                  strongRunId={strongRunId}
                  challengerRunId={challengerRunId}
                  strongProfileId={strongProfileId}
                  challengerProfileId={challengerProfileId}
                  candidates={selectedRecord.candidate_bundle}
                  onGoldDatasetIdChange={props.onGoldDatasetIdChange}
                  onCustomAnswerChange={setCustomAnswer}
                  onCustomAnswerabilityChange={setCustomAnswerability}
                  onAdjudicationNoteChange={setAdjudicationNote}
                  onReviewerChange={setReviewer}
                  onReviewerConfidenceChange={setReviewerConfidence}
                  onStrongRunIdChange={setStrongRunId}
                  onChallengerRunIdChange={setChallengerRunId}
                  onStrongProfileIdChange={setStrongProfileId}
                  onChallengerProfileIdChange={setChallengerProfileId}
                  onGenerateCandidates={() => void runGenerateCandidates()}
                  onSaveCustomDecision={() => void saveCustomDecision()}
                  onLockGold={() => void lockGold()}
                  onUnlockGold={() => void unlockGold()}
                  onAcceptCandidate={(candidateKind) => void acceptCandidate(candidateKind)}
                />
                <TraceTabs record={selectedRecord} />
              </>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 4 }}>
          <PdfPreviewPane apiBase={props.apiBase} preview={reviewPdfPreview} />
        </Grid.Col>
      </Grid>

      <RunReportDrawer
        opened={reportDrawerOpened}
        summary={reviewSummary}
        exportPayload={reviewReportPayload}
        onClose={() => setReportDrawerOpened(false)}
        onExport={() => void exportReport()}
      />
    </Stack>
  );
}
