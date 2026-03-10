declare module "@istego9/style-kit" {
  import type { MantineThemeOverride } from "@mantine/core";

  export function createHq21Theme(overrides?: MantineThemeOverride): MantineThemeOverride;
  export const hq21CssVariables: Record<string, string>;
}
