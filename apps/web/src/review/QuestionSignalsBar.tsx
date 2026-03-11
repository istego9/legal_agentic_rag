import { Badge, Group } from "@mantine/core";
import { t } from "../i18n";

type QuestionSignalsBarProps = {
  flags: string[];
  status: string;
};

const colorByFlag: Record<string, string> = {
  answer_conflict: "red",
  sources_conflict: "yellow",
  answerability_conflict: "violet",
  mini_check_fail: "red",
  missing_sources: "orange",
  telemetry_bad: "pink",
  contract_failure_present: "red",
  auto_lock_candidate: "green",
  gold_locked: "green",
};

const labelByFlag: Record<string, string> = {
  answer_conflict: "reviewFlagAnswerConflict",
  sources_conflict: "reviewFlagSourcesConflict",
  answerability_conflict: "reviewFlagAnswerabilityConflict",
  mini_check_fail: "reviewFlagMiniCheckFail",
  missing_sources: "reviewFlagMissingSources",
  telemetry_bad: "reviewFlagTelemetryBad",
  contract_failure_present: "reviewFlagContractFailure",
  auto_lock_candidate: "reviewFlagAutoLock",
  gold_locked: "reviewFlagGoldLocked",
  needs_review: "reviewFlagNeedsReview",
  review_in_progress: "reviewFlagInProgress",
  not_ready: "reviewFlagNotReady",
  exported: "reviewFlagExported",
};

export function QuestionSignalsBar({ flags, status }: QuestionSignalsBarProps) {
  const tokens = flags.length ? flags : [status];
  return (
    <Group gap={6} wrap="wrap">
      {tokens.map((flag) => (
        <Badge key={flag} size="xs" variant="light" color={colorByFlag[flag] || "gray"}>
          {t((labelByFlag[flag] || "reviewFlagGeneric") as never)}
        </Badge>
      ))}
    </Group>
  );
}
