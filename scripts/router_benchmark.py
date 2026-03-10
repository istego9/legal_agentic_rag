#!/usr/bin/env python3
"""Benchmark runtime routing against the public taxonomy dataset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.public_question_taxonomy import (  # noqa: E402
    DEFAULT_PUBLIC_DATASET_PATH,
    DEFAULT_TAXONOMY_PATH,
    PRIMARY_ROUTES,
    load_and_validate_public_taxonomy,
)
from services.runtime.router import resolve_route  # noqa: E402


DEFAULT_MARKDOWN_OUTPUT_PATH = ROOT / "reports" / "router_benchmark_summary.md"
DEFAULT_JSON_OUTPUT_PATH = ROOT / "reports" / "router_benchmark_results.json"


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def map_runtime_route_to_primary_route(
    runtime_route: str,
    *,
    answer_type: str,
    question: str,
) -> str:
    normalized_route = str(runtime_route or "").strip()
    normalized_answer_type = str(answer_type or "").strip().lower()
    normalized_question = str(question or "").strip().lower()

    if normalized_route == "cross_case_compare":
        return "case_cross_compare"
    if normalized_route == "cross_law_compare":
        return "cross_law_compare"
    if normalized_route == "history_lineage":
        return "law_relation_or_history"
    if normalized_route == "no_answer":
        return "negative_or_unanswerable"
    if normalized_route == "single_case_extraction":
        if normalized_answer_type in {"name", "names"}:
            return "case_entity_lookup"
        return "case_outcome_or_value"
    if normalized_route == "article_lookup":
        if any(token in normalized_question for token in ("article", "section", "clause", "paragraph", "schedule")):
            return "law_article_lookup"
        return "law_scope_or_definition"
    return "negative_or_unanswerable"


def _empty_confusion_matrix() -> Dict[str, Dict[str, int]]:
    return {
        expected: {predicted: 0 for predicted in PRIMARY_ROUTES}
        for expected in PRIMARY_ROUTES
    }


def _compute_per_route_metrics(confusion_matrix: Mapping[str, Mapping[str, int]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for route in PRIMARY_ROUTES:
        true_positive = int(confusion_matrix.get(route, {}).get(route, 0))
        false_positive = sum(
            int(confusion_matrix.get(other, {}).get(route, 0))
            for other in PRIMARY_ROUTES
            if other != route
        )
        false_negative = sum(
            int(confusion_matrix.get(route, {}).get(other, 0))
            for other in PRIMARY_ROUTES
            if other != route
        )
        support = sum(int(confusion_matrix.get(route, {}).get(other, 0)) for other in PRIMARY_ROUTES)
        predicted_count = sum(int(confusion_matrix.get(other, {}).get(route, 0)) for other in PRIMARY_ROUTES)
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2.0 * precision * recall, precision + recall)
        rows.append(
            {
                "primary_route": route,
                "support": support,
                "predicted": predicted_count,
                "tp": true_positive,
                "fp": false_positive,
                "fn": false_negative,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
    return rows


def render_mismatch_lines(mismatches: Sequence[Mapping[str, Any]]) -> List[str]:
    lines: List[str] = []
    for row in mismatches:
        question_id = str(row.get("question_id", "")).strip()
        expected = str(row.get("expected_primary_route", "")).strip()
        predicted = str(row.get("predicted_primary_route", "")).strip()
        runtime_route = str(row.get("runtime_route", "")).strip()
        question = str(row.get("question", "")).strip()
        lines.append(
            f"- [{question_id}] expected={expected} predicted={predicted} runtime={runtime_route} :: {question}"
        )
    return lines


def render_markdown_summary(results: Mapping[str, Any]) -> str:
    per_route_metrics = list(results.get("per_route_metrics", []))
    confusion_matrix = dict(results.get("confusion_matrix", {}))
    mismatch_lines = render_mismatch_lines(results.get("mismatches", []))

    lines: List[str] = [
        "# Router Benchmark Summary",
        "",
        f"- generated_at_utc: `{results.get('generated_at_utc', '')}`",
        f"- public_dataset_path: `{results.get('public_dataset_path', '')}`",
        f"- taxonomy_path: `{results.get('taxonomy_path', '')}`",
        "- benchmark_target: `services.runtime.router.resolve_route`",
        "- benchmark_mapping: `scripts.router_benchmark.map_runtime_route_to_primary_route`",
        f"- total_questions: `{results.get('total_questions', 0)}`",
        f"- correct_predictions: `{results.get('correct_predictions', 0)}`",
        f"- overall_accuracy: `{float(results.get('overall_accuracy', 0.0)):.4f}`",
        "",
        "## Per-Route Precision/Recall/F1",
        "",
        "| primary_route | support | predicted | precision | recall | f1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in per_route_metrics:
        lines.append(
            "| "
            f"{row['primary_route']} | {row['support']} | {row['predicted']} | "
            f"{row['precision']:.4f} | {row['recall']:.4f} | {row['f1']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Confusion Matrix",
            "",
            "| expected \\\\ predicted | " + " | ".join(PRIMARY_ROUTES) + " |",
            "| " + " | ".join(["---"] + ["---:" for _ in PRIMARY_ROUTES]) + " |",
        ]
    )
    for expected in PRIMARY_ROUTES:
        row = confusion_matrix.get(expected, {})
        values = [str(int(row.get(predicted, 0))) for predicted in PRIMARY_ROUTES]
        lines.append(f"| {expected} | " + " | ".join(values) + " |")

    lines.extend(["", f"## Mismatches ({len(mismatch_lines)})", ""])
    if not mismatch_lines:
        lines.append("- none")
    else:
        lines.extend(mismatch_lines)
    lines.append("")
    return "\n".join(lines)


def run_router_benchmark(
    *,
    public_dataset_path: Path = DEFAULT_PUBLIC_DATASET_PATH,
    taxonomy_path: Path = DEFAULT_TAXONOMY_PATH,
) -> Dict[str, Any]:
    public_questions, taxonomy_rows, coverage_errors = load_and_validate_public_taxonomy(
        public_dataset_path=public_dataset_path,
        taxonomy_path=taxonomy_path,
    )
    if coverage_errors:
        details = "\n".join(f"- {item}" for item in coverage_errors)
        raise ValueError(f"taxonomy coverage validation failed:\n{details}")

    taxonomy_by_id = {row.question_id: row for row in taxonomy_rows}
    confusion_matrix = _empty_confusion_matrix()
    mismatches: List[Dict[str, Any]] = []
    correct_predictions = 0

    for question in public_questions:
        question_id = question["id"]
        question_text = question["question"]
        answer_type = question["answer_type"]
        taxonomy_row = taxonomy_by_id[question_id]

        runtime_route = resolve_route(
            {
                "id": question_id,
                "question": question_text,
                "answer_type": answer_type,
            }
        )
        predicted_primary_route = map_runtime_route_to_primary_route(
            runtime_route,
            answer_type=answer_type,
            question=question_text,
        )
        expected_primary_route = taxonomy_row.primary_route

        if expected_primary_route not in confusion_matrix:
            raise ValueError(f"unexpected expected route: {expected_primary_route!r}")
        if predicted_primary_route not in confusion_matrix[expected_primary_route]:
            raise ValueError(f"unexpected predicted route: {predicted_primary_route!r}")

        confusion_matrix[expected_primary_route][predicted_primary_route] += 1
        if expected_primary_route == predicted_primary_route:
            correct_predictions += 1
        else:
            mismatches.append(
                {
                    "question_id": question_id,
                    "question": question_text,
                    "answer_type_expected": answer_type,
                    "expected_primary_route": expected_primary_route,
                    "predicted_primary_route": predicted_primary_route,
                    "runtime_route": runtime_route,
                    "taxonomy_notes": taxonomy_row.notes,
                }
            )

    total_questions = len(public_questions)
    per_route_metrics = _compute_per_route_metrics(confusion_matrix)
    overall_accuracy = _safe_divide(correct_predictions, total_questions)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "public_dataset_path": str(public_dataset_path),
        "taxonomy_path": str(taxonomy_path),
        "total_questions": total_questions,
        "correct_predictions": correct_predictions,
        "overall_accuracy": overall_accuracy,
        "per_route_metrics": per_route_metrics,
        "confusion_matrix": confusion_matrix,
        "mismatches": mismatches,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-dataset",
        type=Path,
        default=DEFAULT_PUBLIC_DATASET_PATH,
        help="Path to public_dataset.json",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=DEFAULT_TAXONOMY_PATH,
        help="Path to taxonomy JSONL",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT_PATH,
        help="Path to markdown summary report",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT_PATH,
        help="Path to JSON benchmark artifact",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    results = run_router_benchmark(
        public_dataset_path=args.public_dataset,
        taxonomy_path=args.taxonomy,
    )
    markdown = render_markdown_summary(results)
    _write_markdown(args.markdown_output, markdown)
    _write_json(args.json_output, results)
    print(
        "[ok] router benchmark finished: "
        f"accuracy={results['overall_accuracy']:.4f} "
        f"({results['correct_predictions']}/{results['total_questions']}), "
        f"mismatches={len(results['mismatches'])}; "
        f"markdown={args.markdown_output} json={args.json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
