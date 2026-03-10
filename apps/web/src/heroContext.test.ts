import { describe, expect, it } from "vitest";
import { resolveHeroActiveContextKey } from "./heroContext";

describe("resolveHeroActiveContextKey", () => {
  it("returns ops internal tool context when ops tab is active", () => {
    expect(resolveHeroActiveContextKey("documents", true)).toBe("workspaceToolOps");
    expect(resolveHeroActiveContextKey("gold", true)).toBe("workspaceToolOps");
  });

  it("returns workspace context when ops tab is not active", () => {
    expect(resolveHeroActiveContextKey("documents", false)).toBe("workspaceDocuments");
    expect(resolveHeroActiveContextKey("gold", false)).toBe("workspaceGold");
  });
});
