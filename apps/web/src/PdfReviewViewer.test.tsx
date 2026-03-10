import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { beforeAll, describe, expect, it, vi } from "vitest";
import PdfReviewViewer, { shouldHighlightTextItem } from "./PdfReviewViewer";
import { hq21Theme } from "./hq21Style";

vi.mock("pdfjs-dist", () => {
  return {
    GlobalWorkerOptions: { workerSrc: "" },
    getDocument: () => ({
      promise: Promise.resolve({
        getPage: async () => ({
          getViewport: () => ({
            width: 400,
            height: 600,
            scale: 1,
            transform: [1, 0, 0, 1, 0, 0],
          }),
          render: () => ({ promise: Promise.resolve() }),
          getTextContent: async () => ({
            items: [
              { str: "Written", transform: [1, 0, 0, 1, 10, 20], width: 40, height: 10 },
              { str: "contract", transform: [1, 0, 0, 1, 60, 20], width: 50, height: 10 },
            ],
          }),
        }),
      }),
    }),
  };
});

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false
    })
  });
});

describe("PdfReviewViewer", () => {
  it("highlights text items that match chunk text", async () => {
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      writable: true,
      value: vi.fn(() => ({})),
    });

    render(
      <MantineProvider theme={hq21Theme} defaultColorScheme="light">
        <PdfReviewViewer
          src="/v1/corpus/documents/doc-1/file"
          pageNumber={1}
          chunkTexts={["Written contract must be provided"]}
        />
      </MantineProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("pdf-highlight-span").length).toBeGreaterThan(0);
    });
  });

  it("normalizes highlight matching conservatively", () => {
    expect(shouldHighlightTextItem("Written", ["Written contract"])).toBe(true);
    expect(shouldHighlightTextItem("Other", ["Written contract"])).toBe(false);
  });
});
