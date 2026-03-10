import { describe, expect, it } from "vitest";
import { en, t } from "./i18n";

describe("i18n", () => {
  it("resolves every key", () => {
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(t(key)).toBeTypeOf("string");
      expect(t(key).length).toBeGreaterThan(0);
    }
  });
});
