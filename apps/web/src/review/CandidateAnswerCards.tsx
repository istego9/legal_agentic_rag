import { Badge, Button, Group, Paper, SimpleGrid, Stack, Text } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewCandidate } from "./types";
import { reviewAnswerPreview, reviewCandidateSlots, reviewSourcesSummary } from "./utils";

type CandidateAnswerCardsProps = {
  candidates: ReviewCandidate[];
  acceptedDecisionSource?: string | null;
  onAcceptCandidate: (candidateKind: ReviewCandidate["candidate_kind"]) => void;
};

function borderColor(candidate: ReviewCandidate | null, acceptedDecisionSource?: string | null): string {
  if (!candidate) {
    return "var(--mantine-color-gray-3)";
  }
  if (acceptedDecisionSource === candidate.candidate_kind) {
    return "var(--mantine-color-green-6)";
  }
  if (candidate.support_status === "not_supported") {
    return "var(--mantine-color-red-6)";
  }
  if (candidate.answerability === "abstain") {
    return "var(--mantine-color-violet-6)";
  }
  return "var(--mantine-color-gray-3)";
}

function answerabilityLabel(value?: string | null): string {
  if (value === "abstain") {
    return t("reviewAbstain");
  }
  if (value === "answerable") {
    return t("reviewAnswerable");
  }
  return t("reviewNotAvailable");
}

export function CandidateAnswerCards({ candidates, acceptedDecisionSource, onAcceptCandidate }: CandidateAnswerCardsProps) {
  const slots = reviewCandidateSlots(candidates);

  return (
    <SimpleGrid cols={{ base: 1, lg: 2, xl: 4 }}>
      {slots.map((candidate, index) => (
        <Paper
          key={candidate?.candidate_kind || index}
          withBorder
          p="md"
          style={{ borderColor: borderColor(candidate, acceptedDecisionSource), minHeight: 220 }}
        >
          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Text fw={600}>{candidate?.label || [t("reviewCandidateSystem"), t("reviewCandidateStrong"), t("reviewCandidateChallenger"), t("reviewCandidateMiniCheck")][index]}</Text>
              <Badge variant="light" color={candidate?.support_status === "not_supported" ? "red" : "gray"}>
                {answerabilityLabel(candidate?.answerability)}
              </Badge>
            </Group>
            {!candidate && (
              <Text size="sm" c="dimmed">
                {t("reviewNotAvailable")}
              </Text>
            )}
            {candidate && (
              <>
                <Text size="sm">{reviewAnswerPreview(candidate.answer)}</Text>
                <Text size="xs" c="dimmed">
                  {t("reviewConfidence")}: {candidate.confidence ?? "-"}
                </Text>
                <Text size="xs" c="dimmed">
                  {t("reviewSourcesLabel")}: {reviewSourcesSummary(candidate.sources)}
                </Text>
                <Text size="xs" c="dimmed" lineClamp={4}>
                  {candidate.reasoning_summary || candidate.unavailable_reason || t("reviewNoReasoningSummary")}
                </Text>
                <Group justify="space-between" align="center" mt="auto">
                  <Text size="xs" c="dimmed">
                    {candidate.created_at ? new Date(candidate.created_at).toLocaleString() : "-"}
                  </Text>
                  <Button size="xs" variant="light" onClick={() => onAcceptCandidate(candidate.candidate_kind)}>
                    {t("reviewUseAsBaseline")}
                  </Button>
                </Group>
              </>
            )}
          </Stack>
        </Paper>
      ))}
    </SimpleGrid>
  );
}
