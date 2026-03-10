import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Group, Loader, Stack, Text } from "@mantine/core";
import { GlobalWorkerOptions, getDocument } from "pdfjs-dist";

GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.mjs", import.meta.url).toString();

type PdfTextItem = {
  text: string;
  left: number;
  top: number;
  width: number;
  height: number;
};

function normalize(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

export function shouldHighlightTextItem(text: string, chunkTexts: string[]): boolean {
  const item = normalize(text);
  if (!item || item.length < 2) {
    return false;
  }
  return chunkTexts.some((chunk) => {
    const normalizedChunk = normalize(chunk);
    return normalizedChunk.includes(item) || item.includes(normalizedChunk);
  });
}

export default function PdfReviewViewer({
  src,
  pageNumber,
  chunkTexts,
}: {
  src: string;
  pageNumber: number;
  chunkTexts: string[];
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [textItems, setTextItems] = useState<PdfTextItem[]>([]);
  const normalizedChunkTexts = useMemo(() => chunkTexts.filter((item) => item.trim().length > 0), [chunkTexts]);

  useEffect(() => {
    let cancelled = false;
    async function renderPdfPage() {
      if (!src) {
        setTextItems([]);
        setError("");
        return;
      }
      setLoading(true);
      setError("");
      try {
        const pdf = await getDocument(src).promise;
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale: 1.25 });
        const canvas = canvasRef.current;
        if (!canvas) {
          return;
        }
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("Canvas context unavailable");
        }
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: context, viewport }).promise;
        const content = await page.getTextContent();
        if (cancelled) {
          return;
        }
        const items = content.items
          .map((item: any) => {
            const transform = viewport.transform;
            const [a, b, c, d, e, f] = item.transform;
            const left = a * transform[0] + c * transform[2] + e * transform[4];
            const top = b * transform[1] + d * transform[3] + f * transform[5];
            const width = Math.max(item.width * viewport.scale, 8);
            const height = Math.max(Math.abs(item.height || 12) * viewport.scale, 12);
            return {
              text: String(item.str ?? ""),
              left,
              top: viewport.height - top - height,
              width,
              height,
            } satisfies PdfTextItem;
          })
          .filter((item) => item.text.trim().length > 0);
        setTextItems(items);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setTextItems([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void renderPdfPage();
    return () => {
      cancelled = true;
    };
  }, [pageNumber, src]);

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text size="xs" c="dimmed">{src ? `PDF page ${pageNumber}` : "No PDF source"}</Text>
        {loading && <Loader size="xs" />}
      </Group>
      {error && (
        <Text size="sm" c="red">{error}</Text>
      )}
      <Box
        style={{
          position: "relative",
          width: "100%",
          minHeight: 640,
          overflow: "auto",
          background: "white",
        }}
      >
        <canvas ref={canvasRef} style={{ width: "100%", height: "auto", display: "block" }} />
        <Box
          data-testid="pdf-text-layer"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
          }}
        >
          {textItems.map((item, index) => {
            const highlighted = shouldHighlightTextItem(item.text, normalizedChunkTexts);
            return (
              <span
                key={`${index}-${item.text}`}
                data-testid={highlighted ? "pdf-highlight-span" : "pdf-text-span"}
                style={{
                  position: "absolute",
                  left: item.left,
                  top: item.top,
                  width: item.width,
                  height: item.height,
                  background: highlighted ? "rgba(255, 226, 89, 0.55)" : "transparent",
                  color: "transparent",
                  userSelect: "text",
                }}
              >
                {item.text}
              </span>
            );
          })}
        </Box>
      </Box>
    </Stack>
  );
}
