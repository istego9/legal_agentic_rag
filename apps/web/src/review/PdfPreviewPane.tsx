import { Suspense, lazy } from "react";
import { Button, Group, Paper, Stack, Text } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewPdfPreview } from "./types";

const PdfReviewViewer = lazy(() => import("../PdfReviewViewer"));

type PdfPreviewPaneProps = {
  apiBase: string;
  preview: ReviewPdfPreview | null;
};

export function PdfPreviewPane({ apiBase, preview }: PdfPreviewPaneProps) {
  const fileUrl = preview?.file_url ? `${apiBase.replace(/\/+$/, "")}${preview.file_url}` : "";
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Stack gap={2}>
          <Text fw={600}>{t("reviewPdfPreviewTitle")}</Text>
          <Text size="xs" c="dimmed">{preview?.title || preview?.fallback.doc_id || t("reviewNoDocumentSelected")}</Text>
        </Stack>
        {fileUrl && (
          <Button size="xs" variant="light" component="a" href={fileUrl} target="_blank" rel="noreferrer">
            {t("actionOpenPdf")}
          </Button>
        )}
      </Group>
      <Paper withBorder p="sm" style={{ minHeight: 620 }}>
        {!preview && (
          <Text size="sm" c="dimmed">
            {t("reviewNoPdfPreview")}
          </Text>
        )}
        {preview && fileUrl && (
          <Suspense fallback={<Text size="sm" c="dimmed">{t("stateLoading")}</Text>}>
            <PdfReviewViewer
              src={fileUrl}
              pageNumber={preview.page.page_num + 1}
              chunkTexts={[preview.page.chunk_text].filter(Boolean)}
            />
          </Suspense>
        )}
        {preview && !fileUrl && (
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              {t("reviewStructuredFallback")}
            </Text>
            <Text size="xs" c="dimmed">
              {preview.fallback.doc_id} · p.{preview.fallback.page_number + 1}
            </Text>
            <Text size="sm">{preview.fallback.text || t("reviewNoPageText")}</Text>
            {!!preview.fallback.parse_warnings.length && (
              <Text size="xs" c="orange">
                {t("reviewWarnings")}: {preview.fallback.parse_warnings.join(", ")}
              </Text>
            )}
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}
