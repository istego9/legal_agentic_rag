import { Badge, Checkbox, Group, Paper, ScrollArea, Select, Stack, Text, TextInput } from "@mantine/core";
import { t } from "../i18n";
import type { ReviewFilters, ReviewRecord } from "./types";
import { QuestionSignalsBar } from "./QuestionSignalsBar";

type ReviewQuestionListProps = {
  records: ReviewRecord[];
  selectedQuestionId: string;
  filters: ReviewFilters;
  routeOptions: string[];
  answerTypeOptions: string[];
  statusOptions: string[];
  onFiltersChange: (next: ReviewFilters) => void;
  onSelectQuestion: (questionId: string) => void;
};

export function ReviewQuestionList({
  records,
  selectedQuestionId,
  filters,
  routeOptions,
  answerTypeOptions,
  statusOptions,
  onFiltersChange,
  onSelectQuestion,
}: ReviewQuestionListProps) {
  return (
    <Stack gap="md">
      <TextInput
        label={t("reviewSearchLabel")}
        value={filters.search}
        onChange={(event) => onFiltersChange({ ...filters, search: event.currentTarget.value })}
        placeholder={t("reviewSearchPlaceholder")}
      />
      <Group grow>
        <Select
          label={t("reviewRouteFilter")}
          value={filters.route}
          onChange={(value) => onFiltersChange({ ...filters, route: value || "" })}
          data={[{ value: "", label: t("reviewAllRoutes") }, ...routeOptions.map((value) => ({ value, label: value }))]}
        />
        <Select
          label={t("reviewAnswerTypeFilter")}
          value={filters.answer_type}
          onChange={(value) => onFiltersChange({ ...filters, answer_type: value || "" })}
          data={[{ value: "", label: t("reviewAllAnswerTypes") }, ...answerTypeOptions.map((value) => ({ value, label: value }))]}
        />
      </Group>
      <Select
        label={t("reviewStatusFilter")}
        value={filters.status}
        onChange={(value) => onFiltersChange({ ...filters, status: value || "" })}
        data={[{ value: "", label: t("reviewAllStatuses") }, ...statusOptions.map((value) => ({ value, label: value }))]}
      />
      <Group gap="xs" wrap="wrap">
        <Checkbox
          label={t("reviewDisagreementOnly")}
          checked={filters.disagreement_only}
          onChange={(event) => onFiltersChange({ ...filters, disagreement_only: event.currentTarget.checked })}
        />
        <Checkbox
          label={t("reviewNeedsReviewOnly")}
          checked={filters.needs_review_only}
          onChange={(event) => onFiltersChange({ ...filters, needs_review_only: event.currentTarget.checked })}
        />
        <Checkbox
          label={t("reviewGoldLockedOnly")}
          checked={filters.gold_locked_only}
          onChange={(event) => onFiltersChange({ ...filters, gold_locked_only: event.currentTarget.checked })}
        />
        <Checkbox
          label={t("reviewNoAnswerOnly")}
          checked={filters.no_answer_only}
          onChange={(event) => onFiltersChange({ ...filters, no_answer_only: event.currentTarget.checked })}
        />
        <Checkbox
          label={t("reviewMissingSourcesOnly")}
          checked={filters.missing_sources_only}
          onChange={(event) => onFiltersChange({ ...filters, missing_sources_only: event.currentTarget.checked })}
        />
        <Checkbox
          label={t("reviewContractFailuresOnly")}
          checked={filters.contract_failures_only}
          onChange={(event) => onFiltersChange({ ...filters, contract_failures_only: event.currentTarget.checked })}
        />
      </Group>
      <ScrollArea h={720}>
        <Stack gap="xs">
          {records.map((record) => (
            <Paper
              key={record.question_id}
              withBorder
              p="sm"
              shadow={record.question_id === selectedQuestionId ? "sm" : undefined}
              className={record.question_id === selectedQuestionId ? "project-card-active" : ""}
              onClick={() => onSelectQuestion(record.question_id)}
              style={{ cursor: "pointer" }}
            >
              <Stack gap={6}>
                <Group justify="space-between" align="flex-start">
                  <Text fw={600} size="sm">
                    {record.question_id}
                  </Text>
                  <Badge variant="light" color={record.status === "gold_locked" ? "green" : record.status === "auto_lock_candidate" ? "teal" : "gray"}>
                    {record.status}
                  </Badge>
                </Group>
                <Text size="sm" lineClamp={2}>
                  {record.question}
                </Text>
                <Group gap="xs" wrap="wrap">
                  <Badge size="xs" variant="outline">
                    {record.answer_type}
                  </Badge>
                  {record.primary_route && (
                    <Badge size="xs" variant="outline">
                      {record.primary_route}
                    </Badge>
                  )}
                </Group>
                <QuestionSignalsBar flags={record.disagreement_flags} status={record.status} />
              </Stack>
            </Paper>
          ))}
          {!records.length && (
            <Paper withBorder p="md">
              <Text size="sm" c="dimmed">
                {t("reviewListEmpty")}
              </Text>
            </Paper>
          )}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
