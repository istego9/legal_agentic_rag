import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";

describe("index.html", () => {
  it("publishes the SVG favicon", () => {
    expect(indexHtml).toContain('<link rel="icon" type="image/svg+xml" href="/favicon.svg" />');
  });
});
