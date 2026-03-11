import { Badge, Button, Group, Paper, ScrollArea, Stack, Text } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewEvidenceRef } from "./types";
import { reviewSourceLabel } from "./utils";

type EvidenceTableProps = {
  evidence: ReviewEvidenceRef[];
  selectedSourcePageId: string;
  miniCheckTargetLabel: string;
  onPinToPdf: (sourcePageId: string) => void;
  onSendToMiniCheck: (evidence: ReviewEvidenceRef[]) => void;
};

export function EvidenceTable({ evidence, selectedSourcePageId, miniCheckTargetLabel, onPinToPdf, onSendToMiniCheck }: EvidenceTableProps) {
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Stack gap={2}>
          <Text fw={600}>{t("reviewEvidenceTitle")}</Text>
          <Text size="xs" c="dimmed">
            {t("reviewMiniCheckTarget")}: {miniCheckTargetLabel}
          </Text>
        </Stack>
        <Button size="xs" variant="light" disabled={!evidence.length} onClick={() => onSendToMiniCheck(evidence.filter((item) => item.is_used !== false))}>
          {t("reviewSendToMiniCheck")}
        </Button>
      </Group>
      <ScrollArea h={240}>
        <Stack gap="xs">
          {evidence.map((item) => (
            <Paper key={`${item.source_page_id || item.doc_id}-${item.page_number}`} withBorder p="sm">
              <Stack gap={4}>
                <Group justify="space-between" align="center">
                  <Text size="sm" fw={500}>
                    {reviewSourceLabel(item)}
                  </Text>
                  <Group gap={6}>
                    <Badge size="xs" color={item.is_used ? "green" : "gray"} variant="light">
                      {item.is_used ? t("reviewUsedBadge").toLowerCase() : t("reviewRetrievedBadge").toLowerCase()}
                    </Badge>
                    {item.source_origin && (
                      <Badge size="xs" variant="outline">
                        {item.source_origin}
                      </Badge>
                    )}
                  </Group>
                </Group>
                <Text size="xs" c="dimmed" lineClamp={4}>
                  {item.snippet || t("reviewNoSnippet")}
                </Text>
                <Group justify="space-between" align="center">
                  <Text size="xs" c={item.source_page_id === selectedSourcePageId ? "blue" : "dimmed"}>
                    {item.source_page_id || "-"}
                  </Text>
                  <Button size="xs" variant="subtle" onClick={() => onPinToPdf(item.source_page_id || "")}>
                    {t("reviewPinToPdf")}
                  </Button>
                </Group>
              </Stack>
            </Paper>
          ))}
          {!evidence.length && (
            <Paper withBorder p="md">
              <Text size="sm" c="dimmed">
                {t("reviewNoEvidenceSelected")}
              </Text>
            </Paper>
          )}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
