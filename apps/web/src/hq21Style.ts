import type { MantineThemeOverride } from "@mantine/core";
import { createHq21Theme, hq21CssVariables } from "@istego9/style-kit";

const hq21DesignOverrides: MantineThemeOverride = {
  focusRing: "auto",
  components: {
    Paper: {
      defaultProps: {
        radius: "md"
      },
      styles: {
        root: {
          backgroundColor: "var(--surface-bg)",
          borderColor: "var(--panel-border)",
          boxShadow: "0 1px 2px rgba(16, 24, 40, 0.05)"
        }
      }
    },
    Button: {
      defaultProps: {
        radius: "md"
      },
      styles: {
        root: {
          fontWeight: 600
        }
      }
    },
    Tabs: {
      styles: {
        list: {
          borderColor: "var(--panel-border)",
          backgroundColor: "rgba(255, 255, 255, 0.68)",
          borderRadius: "12px",
          padding: "4px",
          gap: "4px",
          flexWrap: "nowrap",
          overflowX: "auto"
        },
        tab: {
          borderRadius: "8px",
          whiteSpace: "nowrap"
        }
      }
    },
    Input: {
      defaultProps: {
        radius: "md"
      },
      styles: {
        input: {
          backgroundColor: "#ffffff",
          borderColor: "var(--panel-border)"
        },
        label: {
          color: "var(--ink)",
          fontWeight: 600
        }
      }
    },
    Checkbox: {
      styles: {
        label: {
          fontWeight: 500
        }
      }
    },
    Badge: {
      defaultProps: {
        radius: "sm",
        variant: "light"
      },
      styles: {
        root: {
          fontWeight: 600,
          textTransform: "none"
        }
      }
    },
    Code: {
      styles: {
        root: {
          backgroundColor: "var(--surface-muted)",
          border: "1px solid var(--panel-border)",
          borderRadius: "10px"
        }
      }
    }
  }
};

export const hq21Theme = createHq21Theme(hq21DesignOverrides);
export const hq21StyleVariables: Record<string, string> = {
  ...hq21CssVariables,
  "--surface-bg": "rgba(255, 255, 255, 0.92)",
  "--surface-muted": "#f8fafc"
};
