#!/usr/bin/env python3
"""Build triage artifacts for the Public100 baseline run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Tuple

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.artifacts import artifact_path  # noqa: E402
from packages.router.benchmark_mapping import (  # noqa: E402
    RAW_ROUTE_ALIAS_TO_TAXONOMY,
    RAW_ROUTE_TO_SUBROUTE_NORMALIZATION,
    normalize_runtime_route_for_taxonomy,
)
from packages.router.heuristics import choose_route_decision  # noqa: E402


TRIAGE_QUEUE_VERSION = "public100_triage_queue.v1"
FAILURE_TAXONOMY_VERSION = "public100_failure_taxonomy.v1"
TRIAGE_SUMMARY_VERSION = "public100_triage_summary.v1"
DEFAULT_BASELINE_ROOT = artifact_path("competition_runs") / "public100_baseline"
DEFAULT_QUESTIONS_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "questions.json"
TRUTH_INDEX_DIR = ROOT / "reports" / "corpus_investigation" / "2026-03-12-version-lineage-rca"

REQUIRED_BUCKETS: Tuple[str, ...] = (
    "route_error",
    "retrieval_error",
    "wrong_sources",
    "answerable_vs_abstain_conflict",
    "history_or_version_conflict",
    "compare_dimension_conflict",
    "case_identity_conflict",
    "contract_or_telemetry_error",
)

BUCKET_DESCRIPTIONS: Dict[str, str] = {
    "route_error": "Runtime route is missing, unknown, or mismatched against the current question intent profile.",
    "retrieval_error": "Expected-answer question has no retrieved evidence pages or an obviously weak retrieval trace.",
    "wrong_sources": "Retrieved sources exist but appear inconsistent with the expected document family or evidence shape.",
    "answerable_vs_abstain_conflict": "Question appears answerable under the current question intent profile, but baseline output abstained.",
    "history_or_version_conflict": "History/version-sensitive question abstained or lacks retrieval support.",
    "compare_dimension_conflict": "Cross-document compare question abstained or lacks retrieval support.",
    "case_identity_conflict": "Case-focused question abstained or lacks evidence needed to resolve case identity/value/date fields.",
    "contract_or_telemetry_error": "Question hit a contract, runtime, or telemetry completeness problem.",
}

BUCKET_WEIGHTS: Dict[str, int] = {
    "contract_or_telemetry_error": 100,
    "route_error": 90,
    "wrong_sources": 85,
    "retrieval_error": 80,
    "answerable_vs_abstain_conflict": 70,
    "compare_dimension_conflict": 65,
    "history_or_version_conflict": 60,
    "case_identity_conflict": 55,
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        payload = json.loads(raw)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_questions(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"questions payload must be a list: {path}")
    out: Dict[str, Dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("id", "")).strip()
        if not qid:
            continue
        out[qid] = row
    return out


def _load_submission_answers(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = _read_json(path)
    answers = payload.get("answers", []) if isinstance(payload, dict) else []
    out: Dict[str, Dict[str, Any]] = {}
    for row in answers:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("question_id", "")).strip()
        if not qid:
            continue
        out[qid] = row
    return out


def _severity_label(score: int) -> str:
    if score >= 140:
        return "critical"
    if score >= 100:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


def _triage_status(score: int, expected_negative: bool) -> str:
    if expected_negative and score == 0:
        return "expected_negative"
    if score >= 100:
        return "review_high"
    if score > 0:
        return "review"
    return "monitor"


def _retrieved_pages(answer_row: Mapping[str, Any]) -> List[str]:
    telemetry = answer_row.get("telemetry", {})
    if not isinstance(telemetry, Mapping):
        return []
    retrieval = telemetry.get("retrieval", {})
    if not isinstance(retrieval, Mapping):
        return []
    values = retrieval.get("retrieved_chunk_pages", [])
    return [str(item).strip() for item in values if str(item).strip()]


def _question_profile(question_row: Mapping[str, Any]) -> Dict[str, Any]:
    decision = choose_route_decision(question_row)
    return {
        "raw_route": decision.raw_route,
        "normalized_taxonomy_route": decision.normalized_taxonomy_route,
        "taxonomy_subroute": decision.taxonomy_subroute,
        "document_scope_guess": decision.document_scope_guess,
        "temporal_sensitivity_guess": decision.temporal_sensitivity_guess,
        "target_doc_types_guess": list(decision.target_doc_types_guess or []),
        "matched_rules": list(decision.matched_rules or []),
        "confidence": float(decision.confidence or 0.0),
    }


def _acceptable_taxonomy_routes_for_raw_route(raw_route: str) -> set[str]:
    route = str(raw_route or "").strip()
    allowed: set[str] = set()
    alias = RAW_ROUTE_ALIAS_TO_TAXONOMY.get(route)
    if alias:
        allowed.add(alias)
    for candidate in RAW_ROUTE_TO_SUBROUTE_NORMALIZATION.get(route, {}).values():
        if candidate:
            allowed.add(str(candidate))
    return allowed


def _classify_buckets(
    *,
    question_row: Mapping[str, Any],
    status_row: Mapping[str, Any],
    answer_row: Mapping[str, Any],
) -> List[str]:
    buckets: List[str] = []
    question_profile = _question_profile(question_row)
    route_name = str(status_row.get("route_name", "")).strip()
    normalized_runtime = normalize_runtime_route_for_taxonomy(route_name)
    expected_negative = question_profile["normalized_taxonomy_route"] == "negative_or_unanswerable"
    retrieved_pages = _retrieved_pages(answer_row)
    contract = status_row.get("validation", {}) if isinstance(status_row.get("validation"), Mapping) else {}

    if not route_name or route_name == "unknown":
        buckets.append("route_error")
    else:
        acceptable_routes = _acceptable_taxonomy_routes_for_raw_route(route_name)
        expected_route = str(question_profile.get("normalized_taxonomy_route") or "").strip()
        if acceptable_routes and expected_route and expected_route not in acceptable_routes:
            buckets.append("route_error")

    if not bool(status_row.get("success", False)):
        buckets.append("contract_or_telemetry_error")
    if not bool(contract.get("competition_contract_valid", True)):
        buckets.append("contract_or_telemetry_error")

    telemetry = answer_row.get("telemetry", {})
    if not isinstance(telemetry, Mapping) or not str(telemetry.get("model_name", "")).strip():
        buckets.append("contract_or_telemetry_error")

    if not expected_negative and not retrieved_pages:
        buckets.append("retrieval_error")

    if not expected_negative and bool(status_row.get("abstained", False)):
        buckets.append("answerable_vs_abstain_conflict")

    temporal = str(question_profile.get("temporal_sensitivity_guess") or "").strip()
    if temporal == "historical_version" and (bool(status_row.get("abstained", False)) or not retrieved_pages):
        buckets.append("history_or_version_conflict")

    scope = str(question_profile.get("document_scope_guess") or "").strip()
    if scope == "cross_doc" and (bool(status_row.get("abstained", False)) or len(retrieved_pages) < 2):
        buckets.append("compare_dimension_conflict")

    target_doc_types = set(question_profile.get("target_doc_types_guess") or [])
    if "case" in target_doc_types and route_name in {"single_case_extraction", "cross_case_compare"}:
        if bool(status_row.get("abstained", False)) or not retrieved_pages:
            buckets.append("case_identity_conflict")

    if expected_negative and retrieved_pages and bool(status_row.get("abstained", False)):
        buckets.append("wrong_sources")

    deduped: List[str] = []
    for bucket in buckets:
        if bucket not in deduped:
            deduped.append(bucket)
    return deduped


def build_triage_rows(
    *,
    questions_by_id: Mapping[str, Dict[str, Any]],
    status_rows: Iterable[Mapping[str, Any]],
    answers_by_id: Mapping[str, Dict[str, Any]],
    run_id: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for status_row in status_rows:
        question_id = str(status_row.get("question_id", "")).strip()
        question_row = questions_by_id.get(question_id, {})
        answer_row = answers_by_id.get(question_id, {})
        question_profile = _question_profile(question_row) if question_row else {
            "raw_route": "",
            "normalized_taxonomy_route": "",
            "taxonomy_subroute": "",
            "document_scope_guess": "",
            "temporal_sensitivity_guess": "",
            "target_doc_types_guess": [],
            "matched_rules": [],
            "confidence": 0.0,
        }
        retrieved_pages = _retrieved_pages(answer_row)
        buckets = _classify_buckets(question_row=question_row, status_row=status_row, answer_row=answer_row)
        severity_score = sum(BUCKET_WEIGHTS.get(bucket, 0) for bucket in buckets)
        if str(question_profile.get("document_scope_guess") or "").strip() == "cross_doc":
            severity_score += 5
        if str(status_row.get("answer_type", "")).strip() in {"name", "names", "date", "number"}:
            severity_score += 5 if buckets else 0
        severity_label = _severity_label(severity_score)
        expected_negative = question_profile["normalized_taxonomy_route"] == "negative_or_unanswerable"
        triage_status = _triage_status(severity_score, expected_negative)
        rows.append(
            {
                "triage_version": TRIAGE_QUEUE_VERSION,
                "run_id": run_id,
                "question_id": question_id,
                "question": str(question_row.get("question", "")).strip(),
                "answer_type": str(status_row.get("answer_type", question_row.get("answer_type", ""))).strip(),
                "route_name": str(status_row.get("route_name", "")).strip(),
                "question_profile": question_profile,
                "success": bool(status_row.get("success", False)),
                "abstained": bool(status_row.get("abstained", False)),
                "answer_is_null": bool(status_row.get("answer_is_null", False)),
                "retrieved_page_count": len(retrieved_pages),
                "retrieved_pages": retrieved_pages,
                "failure_buckets": buckets,
                "severity_score": severity_score,
                "severity_label": severity_label,
                "triage_status": triage_status,
                "review_status_recommended": "needs_review" if severity_score > 0 else "accepted",
                "review_console_ref": {"run_id": run_id, "question_id": question_id},
                "validation": dict(status_row.get("validation", {}) or {}),
                "error": str(status_row.get("error", "")).strip(),
            }
        )
    rows.sort(
        key=lambda item: (
            -int(item.get("severity_score", 0)),
            str(item.get("route_name", "")),
            str(item.get("question_id", "")),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["review_priority_rank"] = index
        row["top20_worst"] = index <= 20
    return rows


def build_failure_taxonomy(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    row_list = list(rows)
    counts = Counter()
    examples: Dict[str, List[str]] = {bucket: [] for bucket in REQUIRED_BUCKETS}
    for row in row_list:
        for bucket in row.get("failure_buckets", []):
            counts[bucket] += 1
            if len(examples[bucket]) < 10:
                examples[bucket].append(str(row.get("question_id", "")))
    return {
        "taxonomy_version": FAILURE_TAXONOMY_VERSION,
        "total_questions": len(row_list),
        "counts_by_bucket": {bucket: int(counts.get(bucket, 0)) for bucket in REQUIRED_BUCKETS},
        "bucket_definitions": {
            bucket: {
                "description": BUCKET_DESCRIPTIONS[bucket],
                "count": int(counts.get(bucket, 0)),
                "sample_question_ids": examples[bucket],
            }
            for bucket in REQUIRED_BUCKETS
        },
    }


def render_summary(
    *,
    artifact_root: Path,
    run_id: str,
    rows: List[Mapping[str, Any]],
    taxonomy: Mapping[str, Any],
) -> str:
    status_counts = Counter(str(row.get("triage_status", "")) for row in rows)
    high_priority_count = sum(1 for row in rows if str(row.get("severity_label", "")) in {"high", "critical"})
    top_buckets = sorted(
        ((bucket, int(count)) for bucket, count in taxonomy.get("counts_by_bucket", {}).items() if int(count) > 0),
        key=lambda item: (-item[1], item[0]),
    )[:5]
    lines = [
        "# Public100 Baseline Triage Summary",
        "",
        f"- triage_version: `{TRIAGE_SUMMARY_VERSION}`",
        f"- run_id: `{run_id}`",
        f"- artifact_root: `{artifact_root}`",
        "",
        "## Counts",
        "",
        f"- total_questions: `{len(rows)}`",
        f"- high_priority_review_count: `{high_priority_count}`",
        f"- triage_status_counts: `{dict(sorted(status_counts.items()))}`",
        "",
        "## Top 5 Buckets",
        "",
    ]
    for bucket, count in top_buckets:
        lines.append(f"- `{bucket}`: `{count}`")
    lines.extend(["", "## Top 20 Worst Questions", ""])
    for row in rows[:20]:
        question = str(row.get("question", "")).strip().replace("\n", " ")
        if len(question) > 140:
            question = question[:137] + "..."
        lines.append(
            f"- `{row.get('review_priority_rank')}` `{row.get('question_id')}` "
            f"`{row.get('severity_label')}` score=`{row.get('severity_score')}` "
            f"route=`{row.get('route_name')}` buckets=`{', '.join(row.get('failure_buckets', [])) or 'none'}` "
            f"- {question}"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This triage layer is baseline-specific and does not change runtime behavior.",
            "- Queue rows are keyed by `run_id` and `question_id` so they can be joined back to review-console records later.",
            "- The current question source of truth is `datasets/official_fetch_2026-03-11/questions.json`; triage profiling is derived from current question text and runtime route heuristics.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dict(row), ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _tracked_truth_payload(artifact_root: Path, rows: List[Mapping[str, Any]], taxonomy: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    counts = Counter(str(row.get("triage_status", "")) for row in rows)
    high_priority_count = sum(1 for row in rows if str(row.get("severity_label", "")) in {"high", "critical"})
    top_buckets = sorted(
        ((bucket, int(count)) for bucket, count in taxonomy.get("counts_by_bucket", {}).items() if int(count) > 0),
        key=lambda item: (-item[1], item[0]),
    )[:5]
    markdown = [
        "# Public100 Baseline Triage Truth Index",
        "",
        f"- artifact_root: `{artifact_root}`",
        f"- total_questions: `{len(rows)}`",
        f"- high_priority_review_count: `{high_priority_count}`",
        f"- triage_status_counts: `{dict(sorted(counts.items()))}`",
        "",
        "## Canonical Artifacts",
        "",
        f"- triage_summary: `{artifact_root / 'triage_summary.md'}`",
        f"- triage_queue: `{artifact_root / 'triage_queue.jsonl'}`",
        f"- failure_taxonomy: `{artifact_root / 'failure_taxonomy.json'}`",
        "",
        "## Top 5 Buckets",
        "",
    ]
    for bucket, count in top_buckets:
        markdown.append(f"- `{bucket}`: `{count}`")
    markdown.append("")
    json_payload = {
        "truth_index_version": "public100_baseline_triage_truth_index.v1",
        "artifact_root": str(artifact_root),
        "total_questions": len(rows),
        "high_priority_review_count": high_priority_count,
        "triage_status_counts": dict(sorted(counts.items())),
        "top_5_buckets": [{"bucket": bucket, "count": count} for bucket, count in top_buckets],
        "artifacts": {
            "triage_summary_path": str(artifact_root / "triage_summary.md"),
            "triage_queue_path": str(artifact_root / "triage_queue.jsonl"),
            "failure_taxonomy_path": str(artifact_root / "failure_taxonomy.json"),
        },
    }
    return "\n".join(markdown) + "\n", json_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build triage artifacts for the Public100 baseline run")
    parser.add_argument("--artifact-root", default=str(DEFAULT_BASELINE_ROOT))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--tracked-truth", dest="tracked_truth", action="store_true", default=True)
    parser.add_argument("--no-tracked-truth", dest="tracked_truth", action="store_false")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact_root = Path(args.artifact_root).resolve()
    questions_path = Path(args.questions).resolve()
    run_manifest = _read_json(artifact_root / "run_manifest.json")
    question_status = _read_jsonl(artifact_root / "question_status.jsonl")
    submission_answers = _load_submission_answers(artifact_root / "submission.json")
    questions_by_id = _load_questions(questions_path)

    run_id = str(run_manifest.get("run_id", "")).strip()
    if not run_id:
        raise SystemExit("run_manifest.json missing run_id")

    triage_rows = build_triage_rows(
        questions_by_id=questions_by_id,
        status_rows=question_status,
        answers_by_id=submission_answers,
        run_id=run_id,
    )
    failure_taxonomy = build_failure_taxonomy(triage_rows)
    triage_summary = render_summary(
        artifact_root=artifact_root,
        run_id=run_id,
        rows=triage_rows,
        taxonomy=failure_taxonomy,
    )

    triage_summary_path = artifact_root / "triage_summary.md"
    triage_queue_path = artifact_root / "triage_queue.jsonl"
    failure_taxonomy_path = artifact_root / "failure_taxonomy.json"

    triage_summary_path.write_text(triage_summary, encoding="utf-8")
    _write_jsonl(triage_queue_path, triage_rows)
    _write_json(failure_taxonomy_path, failure_taxonomy)

    if args.tracked_truth:
        tracked_md, tracked_json = _tracked_truth_payload(artifact_root, triage_rows, failure_taxonomy)
        (TRUTH_INDEX_DIR / "public100_baseline_triage_truth_index.md").write_text(tracked_md, encoding="utf-8")
        _write_json(TRUTH_INDEX_DIR / "public100_baseline_triage_truth_index.json", tracked_json)

    print(
        json.dumps(
            {
                "status": "completed",
                "run_id": run_id,
                "artifact_root": str(artifact_root),
                "triage_summary_path": str(triage_summary_path),
                "triage_queue_path": str(triage_queue_path),
                "failure_taxonomy_path": str(failure_taxonomy_path),
                "high_priority_review_count": sum(
                    1 for row in triage_rows if str(row.get("severity_label", "")) in {"high", "critical"}
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
