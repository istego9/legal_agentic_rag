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
from packages.router.benchmark_mapping import (  # noqa: E402
    BENCHMARK_ROUTE_NORMALIZATION_VERSION,
    UNMAPPED_TAXONOMY_ROUTE,
    map_raw_route_to_taxonomy,
    normalize_runtime_route_for_taxonomy,
    validate_benchmark_mapping,
)
from services.runtime.router import resolve_route  # noqa: E402


DEFAULT_MARKDOWN_OUTPUT_PATH = ROOT / "reports" / "router_benchmark_summary.md"
DEFAULT_JSON_OUTPUT_PATH = ROOT / "reports" / "router_benchmark_results.json"


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _normalized_predicted_route_labels() -> List[str]:
    return [*PRIMARY_ROUTES, UNMAPPED_TAXONOMY_ROUTE]


def _empty_confusion_matrix() -> Dict[str, Dict[str, int]]:
    predicted_labels = _normalized_predicted_route_labels()
    return {
        expected: {predicted: 0 for predicted in predicted_labels}
        for expected in PRIMARY_ROUTES
    }


def _compute_per_route_metrics(confusion_matrix: Mapping[str, Mapping[str, int]]) -> List[Dict[str, Any]]:
    predicted_labels = _normalized_predicted_route_labels()
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
            for other in predicted_labels
            if other != route
        )
        support = sum(int(confusion_matrix.get(route, {}).get(other, 0)) for other in predicted_labels)
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


def compute_macro_f1(per_route_metrics: Sequence[Mapping[str, Any]]) -> float:
    if not per_route_metrics:
        return 0.0
    total = sum(float(row.get("f1", 0.0)) for row in per_route_metrics)
    return _safe_divide(total, float(len(per_route_metrics)))


def compute_top_confusion_pairs(
    confusion_matrix: Mapping[str, Mapping[str, int]],
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    predicted_labels = _normalized_predicted_route_labels()
    pairs: List[Dict[str, Any]] = []
    for expected in PRIMARY_ROUTES:
        row = confusion_matrix.get(expected, {})
        for predicted in predicted_labels:
            if expected == predicted:
                continue
            count = int(row.get(predicted, 0))
            if count <= 0:
                continue
            pairs.append(
                {
                    "expected_primary_route": expected,
                    "predicted_primary_route": predicted,
                    "count": count,
                }
            )
    pairs.sort(
        key=lambda item: (
            -int(item["count"]),
            str(item["expected_primary_route"]),
            str(item["predicted_primary_route"]),
        )
    )
    return pairs[: max(0, int(limit))]


def detect_dead_routes(per_route_metrics: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    dead: List[Dict[str, Any]] = []
    for row in per_route_metrics:
        support = int(row.get("support", 0))
        predicted = int(row.get("predicted", 0))
        if support > 0 and predicted == 0:
            dead.append(
                {
                    "primary_route": str(row.get("primary_route", "")),
                    "support": support,
                    "predicted": predicted,
                }
            )
    return dead


def _count_values(values: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in values:
        key = str(item or "").strip() or "unknown"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda entry: (-entry[1], entry[0])))


def render_mismatch_lines(mismatches: Sequence[Mapping[str, Any]]) -> List[str]:
    lines: List[str] = []
    for row in mismatches:
        question_id = str(row.get("question_id", "")).strip()
        expected = str(row.get("expected_primary_route", "")).strip()
        raw_mapped = str(row.get("raw_predicted_route", "")).strip()
        predicted = str(row.get("normalized_predicted_route", row.get("predicted_primary_route", ""))).strip()
        raw_runtime_route = str(row.get("raw_runtime_route", row.get("runtime_route", ""))).strip()
        normalization_source = str(row.get("normalization_source", "")).strip()
        question = str(row.get("question", "")).strip()
        lines.append(
            f"- [{question_id}] expected={expected} raw_mapped={raw_mapped} normalized={predicted} "
            f"raw_runtime={raw_runtime_route} source={normalization_source} :: {question}"
        )
    return lines


def render_markdown_summary(results: Mapping[str, Any]) -> str:
    per_route_metrics = list(results.get("per_route_metrics", []))
    confusion_matrix = dict(results.get("confusion_matrix", {}))
    raw_runtime_route_counts = dict(results.get("raw_runtime_route_counts", {}))
    normalized_taxonomy_route_counts = dict(results.get("normalized_taxonomy_route_counts", {}))
    top_confusion_pairs = list(results.get("top_confusion_pairs", []))
    dead_routes = list(results.get("dead_routes", []))
    mismatch_lines = render_mismatch_lines(results.get("mismatches", []))

    lines: List[str] = [
        "# Router Benchmark Summary",
        "",
        f"- generated_at_utc: `{results.get('generated_at_utc', '')}`",
        f"- public_dataset_path: `{results.get('public_dataset_path', '')}`",
        f"- taxonomy_path: `{results.get('taxonomy_path', '')}`",
        "- benchmark_target: `services.runtime.router.resolve_route`",
        "- benchmark_mapping: `packages.router.benchmark_mapping.normalize_runtime_route_for_taxonomy`",
        f"- normalization_model_version: `{results.get('normalization_model_version', '')}`",
        f"- total_questions: `{results.get('total_questions', 0)}`",
        f"- raw_route_correct_predictions: `{results.get('raw_route_correct_predictions', 0)}`",
        f"- normalized_route_correct_predictions: `{results.get('normalized_route_correct_predictions', 0)}`",
        f"- raw_route_accuracy: `{float(results.get('raw_route_accuracy', 0.0)):.4f}`",
        f"- normalized_route_accuracy: `{float(results.get('normalized_route_accuracy', 0.0)):.4f}`",
        f"- normalized_macro_f1: `{float(results.get('normalized_macro_f1', 0.0)):.4f}`",
        "",
        "## Normalized Per-Route Precision/Recall/F1",
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

    lines.extend(["", "## Predicted Count By Raw Runtime Route", ""])
    lines.append("| raw_runtime_route | predicted_count |")
    lines.append("| --- | ---: |")
    for route_name, count in raw_runtime_route_counts.items():
        lines.append(f"| {route_name} | {int(count)} |")

    lines.extend(["", "## Predicted Count By Normalized Taxonomy Route", ""])
    lines.append("| normalized_taxonomy_route | predicted_count |")
    lines.append("| --- | ---: |")
    for route_name in _normalized_predicted_route_labels():
        lines.append(f"| {route_name} | {int(normalized_taxonomy_route_counts.get(route_name, 0))} |")

    lines.extend(
        [
            "",
            "## Confusion Matrix",
            "",
            "| expected \\\\ predicted | " + " | ".join(_normalized_predicted_route_labels()) + " |",
            "| " + " | ".join(["---"] + ["---:" for _ in _normalized_predicted_route_labels()]) + " |",
        ]
    )
    for expected in PRIMARY_ROUTES:
        row = confusion_matrix.get(expected, {})
        values = [str(int(row.get(predicted, 0))) for predicted in _normalized_predicted_route_labels()]
        lines.append(f"| {expected} | " + " | ".join(values) + " |")

    lines.extend(["", "## Top Confusion Pairs", ""])
    if not top_confusion_pairs:
        lines.append("- none")
    else:
        for pair in top_confusion_pairs:
            lines.append(
                "- "
                f"{pair['expected_primary_route']} -> {pair['predicted_primary_route']}: "
                f"{pair['count']}"
            )

    lines.extend(["", "## Dead Routes", ""])
    if not dead_routes:
        lines.append("- none")
    else:
        for row in dead_routes:
            lines.append(f"- {row['primary_route']} (support={row['support']}, predicted={row['predicted']})")

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
    mapping_errors = validate_benchmark_mapping()
    if mapping_errors:
        details = "\n".join(f"- {item}" for item in mapping_errors)
        raise ValueError(f"benchmark route normalization mapping invalid:\n{details}")

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
    raw_route_correct_predictions = 0
    normalized_route_correct_predictions = 0
    raw_runtime_routes: List[str] = []
    raw_predicted_routes: List[str] = []
    normalized_predicted_routes: List[str] = []

    for question in public_questions:
        question_id = question["id"]
        question_text = question["question"]
        taxonomy_row = taxonomy_by_id[question_id]

        runtime_route_output = resolve_route(
            {
                "id": question_id,
                "question": question_text,
                "answer_type": question["answer_type"],
            }
        )
        runtime_route = str(runtime_route_output or "").strip()
        runtime_metadata = None
        if isinstance(runtime_route_output, dict):
            runtime_route = str(
                runtime_route_output.get("route_name")
                or runtime_route_output.get("route")
                or runtime_route_output.get("raw_runtime_route")
                or ""
            ).strip()
            metadata_candidate = runtime_route_output.get("route_metadata")
            if isinstance(metadata_candidate, dict):
                runtime_metadata = metadata_candidate

        raw_predicted_route = map_raw_route_to_taxonomy(runtime_route)
        normalization_decision = normalize_runtime_route_for_taxonomy(runtime_route, runtime_metadata=runtime_metadata)
        raw_runtime_route = normalization_decision.raw_runtime_route
        normalization_source = normalization_decision.normalization_source
        normalized_predicted_route = normalization_decision.normalized_taxonomy_route
        expected_primary_route = taxonomy_row.primary_route

        if expected_primary_route not in confusion_matrix:
            raise ValueError(f"unexpected expected route: {expected_primary_route!r}")
        if normalized_predicted_route not in confusion_matrix[expected_primary_route]:
            raise ValueError(f"unexpected normalized predicted route: {normalized_predicted_route!r}")

        confusion_matrix[expected_primary_route][normalized_predicted_route] += 1
        raw_runtime_routes.append(raw_runtime_route)
        raw_predicted_routes.append(raw_predicted_route)
        normalized_predicted_routes.append(normalized_predicted_route)

        if expected_primary_route == raw_predicted_route:
            raw_route_correct_predictions += 1
        if expected_primary_route == normalized_predicted_route:
            normalized_route_correct_predictions += 1
        else:
            mismatches.append(
                {
                    "question_id": question_id,
                    "question": question_text,
                    "answer_type_expected": question["answer_type"],
                    "expected_primary_route": expected_primary_route,
                    "raw_runtime_route": raw_runtime_route,
                    "raw_predicted_route": raw_predicted_route,
                    "normalized_predicted_route": normalized_predicted_route,
                    "normalization_source": normalization_source,
                    "runtime_taxonomy_subroute": normalization_decision.runtime_taxonomy_subroute,
                    "taxonomy_notes": taxonomy_row.notes,
                }
            )

    total_questions = len(public_questions)
    per_route_metrics = _compute_per_route_metrics(confusion_matrix)
    raw_route_accuracy = _safe_divide(raw_route_correct_predictions, total_questions)
    normalized_route_accuracy = _safe_divide(normalized_route_correct_predictions, total_questions)
    normalized_macro_f1 = compute_macro_f1(per_route_metrics)
    raw_runtime_route_counts = _count_values(raw_runtime_routes)
    normalized_taxonomy_route_counts = _count_values(normalized_predicted_routes)
    raw_predicted_route_counts = _count_values(raw_predicted_routes)
    top_confusion_pairs = compute_top_confusion_pairs(confusion_matrix)
    dead_routes = detect_dead_routes(per_route_metrics)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "public_dataset_path": str(public_dataset_path),
        "taxonomy_path": str(taxonomy_path),
        "normalization_model_version": BENCHMARK_ROUTE_NORMALIZATION_VERSION,
        "total_questions": total_questions,
        "raw_route_correct_predictions": raw_route_correct_predictions,
        "normalized_route_correct_predictions": normalized_route_correct_predictions,
        "raw_route_accuracy": raw_route_accuracy,
        "normalized_route_accuracy": normalized_route_accuracy,
        "overall_accuracy": normalized_route_accuracy,
        "normalized_macro_f1": normalized_macro_f1,
        "macro_f1": normalized_macro_f1,
        "per_route_metrics": per_route_metrics,
        "raw_runtime_route_counts": raw_runtime_route_counts,
        "raw_predicted_route_counts": raw_predicted_route_counts,
        "normalized_taxonomy_route_counts": normalized_taxonomy_route_counts,
        "top_confusion_pairs": top_confusion_pairs,
        "dead_routes": dead_routes,
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
        f"raw_accuracy={results['raw_route_accuracy']:.4f}, "
        f"normalized_accuracy={results['normalized_route_accuracy']:.4f} "
        f"({results['normalized_route_correct_predictions']}/{results['total_questions']}), "
        f"mismatches={len(results['mismatches'])}; "
        f"markdown={args.markdown_output} json={args.json_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
