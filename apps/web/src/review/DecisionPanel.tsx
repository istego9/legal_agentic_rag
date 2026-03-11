import { Button, Group, Select, SimpleGrid, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewCandidate } from "./types";

type DecisionPanelProps = {
  goldDatasetId: string;
  customAnswer: string;
  customAnswerability: string;
  adjudicationNote: string;
  reviewer: string;
  reviewerConfidence: string;
  strongRunId: string;
  challengerRunId: string;
  strongProfileId: string;
  challengerProfileId: string;
  candidates: ReviewCandidate[];
  onGoldDatasetIdChange: (value: string) => void;
  onCustomAnswerChange: (value: string) => void;
  onCustomAnswerabilityChange: (value: string) => void;
  onAdjudicationNoteChange: (value: string) => void;
  onReviewerChange: (value: string) => void;
  onReviewerConfidenceChange: (value: string) => void;
  onStrongRunIdChange: (value: string) => void;
  onChallengerRunIdChange: (value: string) => void;
  onStrongProfileIdChange: (value: string) => void;
  onChallengerProfileIdChange: (value: string) => void;
  onGenerateCandidates: () => void;
  onSaveCustomDecision: () => void;
  onLockGold: () => void;
  onUnlockGold: () => void;
  onAcceptCandidate: (candidateKind: ReviewCandidate["candidate_kind"]) => void;
};

export function DecisionPanel(props: DecisionPanelProps) {
  return (
    <Stack gap="md">
      <Text fw={600}>{t("reviewDecisionTitle")}</Text>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <TextInput label={t("reviewReviewer")} value={props.reviewer} onChange={(event) => props.onReviewerChange(event.currentTarget.value)} />
        <TextInput
          label={t("reviewReviewerConfidence")}
          value={props.reviewerConfidence}
          onChange={(event) => props.onReviewerConfidenceChange(event.currentTarget.value)}
        />
        <TextInput label={t("datasetIdGold")} value={props.goldDatasetId} onChange={(event) => props.onGoldDatasetIdChange(event.currentTarget.value)} />
        <Select
          label={t("reviewAnswerability")}
          value={props.customAnswerability}
          onChange={(value) => props.onCustomAnswerabilityChange(value || "answerable")}
          data={[
            { value: "answerable", label: t("reviewAnswerable") },
            { value: "abstain", label: t("reviewAbstain") },
          ]}
        />
        <TextInput label={t("reviewStrongRunId")} value={props.strongRunId} onChange={(event) => props.onStrongRunIdChange(event.currentTarget.value)} />
        <TextInput label={t("reviewChallengerRunId")} value={props.challengerRunId} onChange={(event) => props.onChallengerRunIdChange(event.currentTarget.value)} />
        <TextInput
          label={t("reviewStrongProfileId")}
          value={props.strongProfileId}
          onChange={(event) => props.onStrongProfileIdChange(event.currentTarget.value)}
        />
        <TextInput
          label={t("reviewChallengerProfileId")}
          value={props.challengerProfileId}
          onChange={(event) => props.onChallengerProfileIdChange(event.currentTarget.value)}
        />
      </SimpleGrid>
      <Textarea
        label={t("reviewCustomAnswer")}
        value={props.customAnswer}
        onChange={(event) => props.onCustomAnswerChange(event.currentTarget.value)}
        minRows={2}
      />
      <Textarea
        label={t("reviewAdjudicationNote")}
        value={props.adjudicationNote}
        onChange={(event) => props.onAdjudicationNoteChange(event.currentTarget.value)}
        minRows={3}
      />
      <Group gap="xs" wrap="wrap">
        <Button variant="light" onClick={props.onGenerateCandidates}>
          {t("reviewGenerateCandidates")}
        </Button>
        {props.candidates
          .filter((candidate) => candidate.candidate_kind !== "mini_check")
          .map((candidate) => (
            <Button key={candidate.candidate_id} variant="subtle" size="xs" onClick={() => props.onAcceptCandidate(candidate.candidate_kind)}>
              {`${t("reviewAcceptPrefix")} ${candidate.label || candidate.candidate_kind}`}
            </Button>
          ))}
        <Button variant="light" onClick={props.onSaveCustomDecision}>
          {t("reviewSaveCustomDecision")}
        </Button>
        <Button color="green" onClick={props.onLockGold}>
          {t("reviewLockGold")}
        </Button>
        <Button color="orange" variant="light" onClick={props.onUnlockGold}>
          {t("reviewUnlockGold")}
        </Button>
      </Group>
    </Stack>
  );
}
