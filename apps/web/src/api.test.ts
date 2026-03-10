import { afterEach, describe, expect, it, vi } from "vitest";
import { defaultRuntimePolicy, joinUrl } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("api helpers", () => {
  it("builds url with and without base", () => {
    expect(joinUrl("", "/v1/health")).toBe("/v1/health");
    expect(joinUrl("http://localhost:8000", "/v1/health")).toBe("http://localhost:8000/v1/health");
    expect(joinUrl("http://localhost:8000/", "/v1/health")).toBe("http://localhost:8000/v1/health");
  });

  it("returns budget runtime policy", () => {
    const policy = defaultRuntimePolicy(true);
    expect(policy.use_llm).toBe(true);
    expect(policy.max_candidate_pages).toBeGreaterThan(0);
    expect(policy.page_index_base_export).toBe(0);
  });
});
