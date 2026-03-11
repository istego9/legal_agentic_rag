import { t } from "../i18n";
import type { ReviewCandidate, ReviewEvidenceRef } from "./types";

export const reviewCandidateOrder = ["system", "strong_model", "challenger", "mini_check"] as const;

export function reviewCandidateSlots(candidates: ReviewCandidate[]): Array<ReviewCandidate | null> {
  return reviewCandidateOrder.map((kind) => candidates.find((candidate) => candidate.candidate_kind === kind) ?? null);
}

export function reviewAnswerPreview(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

export function reviewSourcesSummary(sources: ReviewEvidenceRef[]): string {
  if (!sources.length) {
    return t("reviewNotAvailable");
  }
  const first = sources[0];
  const pages = Array.from(new Set(sources.map((source) => source.page_number + 1))).join(", ");
  return `${first.doc_title || first.doc_id} / ${pages}`;
}

export function reviewSourceLabel(source: ReviewEvidenceRef): string {
  return `${source.doc_title || source.doc_id} · p.${source.page_number + 1}`;
}
