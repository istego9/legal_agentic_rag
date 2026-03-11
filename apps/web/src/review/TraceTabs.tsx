import { Code, ScrollArea, Tabs } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewRecord } from "./types";

type TraceTabsProps = {
  record: ReviewRecord | null;
};

function pretty(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function TraceTabs({ record }: TraceTabsProps) {
  return (
    <Tabs defaultValue="trace" variant="outline">
      <Tabs.List>
        <Tabs.Tab value="trace">{t("reviewTabTrace")}</Tabs.Tab>
        <Tabs.Tab value="retrieval">{t("reviewTabRetrieval")}</Tabs.Tab>
        <Tabs.Tab value="evidence">{t("reviewTabEvidence")}</Tabs.Tab>
        <Tabs.Tab value="telemetry">{t("reviewTabTelemetry")}</Tabs.Tab>
        <Tabs.Tab value="adjudication">{t("reviewTabAdjudication")}</Tabs.Tab>
        <Tabs.Tab value="raw">{t("reviewTabRawJson")}</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="trace" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record?.evidence?.solver_trace)}</Code>
        </ScrollArea>
      </Tabs.Panel>
      <Tabs.Panel value="retrieval" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record?.evidence?.retrieval_stage_trace || record?.evidence?.route_recall_diagnostics)}</Code>
        </ScrollArea>
      </Tabs.Panel>
      <Tabs.Panel value="evidence" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record?.evidence)}</Code>
        </ScrollArea>
      </Tabs.Panel>
      <Tabs.Panel value="telemetry" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record?.evidence?.telemetry_shadow)}</Code>
        </ScrollArea>
      </Tabs.Panel>
      <Tabs.Panel value="adjudication" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record?.accepted_decision)}</Code>
        </ScrollArea>
      </Tabs.Panel>
      <Tabs.Panel value="raw" pt="sm">
        <ScrollArea h={220}>
          <Code block>{pretty(record)}</Code>
        </ScrollArea>
      </Tabs.Panel>
    </Tabs>
  );
}
