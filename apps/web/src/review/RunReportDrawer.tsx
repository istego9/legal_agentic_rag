import { Button, Code, Drawer, Group, Stack, Text } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewSummary } from "./types";

type RunReportDrawerProps = {
  opened: boolean;
  summary: ReviewSummary | null;
  exportPayload: Record<string, unknown> | null;
  downloadUrl: string;
  onClose: () => void;
  onExport: () => void;
};

export function RunReportDrawer({ opened, summary, exportPayload, downloadUrl, onClose, onExport }: RunReportDrawerProps) {
  return (
    <Drawer opened={opened} onClose={onClose} position="right" title={t("reviewRunReportTitle")} size="lg">
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Text fw={600}>{summary?.run_id || t("reviewNoRunSelected")}</Text>
          <Group gap={6}>
            <Button size="xs" onClick={onExport}>
              {t("reviewExportReport")}
            </Button>
            <Button size="xs" variant="light" component="a" href={downloadUrl} target="_blank" rel="noreferrer" disabled={!downloadUrl}>
              {t("reviewDownloadJson")}
            </Button>
          </Group>
        </Group>
        <Text size="sm">{t("reviewSummaryTotal")}: {summary?.total_questions ?? 0}</Text>
        <Text size="sm">{t("reviewSummaryNeedsReview")}: {summary?.needs_review_count ?? 0}</Text>
        <Text size="sm">{t("reviewSummaryAutoLock")}: {summary?.auto_lock_candidates ?? 0}</Text>
        <Text size="sm">{t("reviewSummaryGoldLocked")}: {summary?.locked_gold_count ?? 0}</Text>
        <Code block>{JSON.stringify(exportPayload ?? summary ?? {}, null, 2)}</Code>
      </Stack>
    </Drawer>
  );
}
