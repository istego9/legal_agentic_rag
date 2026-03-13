#!/usr/bin/env python3
"""Regenerate the tracked truth index for the rules-first chunk/proposition pilot."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.artifacts import artifact_path  # noqa: E402


TRUTH_INDEX_DIR = ROOT / "reports" / "corpus_investigation" / "2026-03-12-version-lineage-rca"
TRUTH_INDEX_JSON = TRUTH_INDEX_DIR / "chunk_processing_pilot_truth_index.json"
TRUTH_INDEX_MD = TRUTH_INDEX_DIR / "chunk_processing_pilot_truth_index.md"
AUDIT_MEMO_MD = TRUTH_INDEX_DIR / "chunk_processing_pilot_v1_local_audit_memo.md"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_truth_index_payload() -> Dict[str, Any]:
    canonical_roots = [
        artifact_path("competition_runs", "pilots", "chunk_processing_pilot_v1"),
        artifact_path("competition_runs", "pilots", "chunk_processing_pilot_v1_run2"),
    ]
    latest_root = canonical_roots[-1]
    gate = _load_json(latest_root / "fixture_gate_report.json")
    retrieval = _load_json(latest_root / "retrieval_quality_report.json")
    expanded = _load_json(latest_root / "expanded_frozen_query_report.json")
    direct_answer = _load_json(latest_root / "direct_answer_eligibility_report.json")
    provenance = _load_json(latest_root / "provenance_coverage_report.json")
    real_corpus = _load_json(latest_root / "real_corpus_fixture_report.json")
    shadow_root = artifact_path("competition_runs", "pilots", "chunk_processing_shadow_subset_v1")
    shadow_subset = _load_json(shadow_root / "shadow_subset_report.json")
    shadow_delta = _load_json(shadow_root / "shadow_delta_report.json")

    superseded_tracked_paths = [
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/direct_answer_report.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/processing_results_export.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/processing_rules_export.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/provenance_coverage_report.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/retrieval_quality_report.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/semantic_assertion_quality_report.md",
        "reports/competition_runs/pilots/chunk_processing_pilot_v1/structural_chunk_quality_report.md",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_external_audit_export/README.md",
    ]

    return {
        "truth_index_version": "chunk_processing_pilot_truth_index_v1",
        "program_label": "rules-first chunk/proposition pilot",
        "canonical_artifact_roots": [str(path) for path in canonical_roots],
        "latest_confirmation_run_root": str(latest_root),
        "shadow_subset_root": str(shadow_root),
        "summary_metrics": {
            "structural_gate_passed": bool((gate.get("gates", {}) or {}).get("structural", {}).get("passed")),
            "semantic_gate_passed": bool((gate.get("gates", {}) or {}).get("semantic", {}).get("passed")),
            "retrieval_gate_passed": bool((gate.get("gates", {}) or {}).get("retrieval", {}).get("passed")),
            "direct_answer_gate_passed": bool((gate.get("gates", {}) or {}).get("direct_answer", {}).get("passed")),
            "retrieval_top3_expected_hit_ratio": retrieval.get("top3_expected_hit_ratio"),
            "expanded_frozen_query_count": expanded.get("query_count"),
            "expanded_frozen_query_pass_ratio": expanded.get("pass_ratio"),
            "direct_answer_precision_on_eligible": direct_answer.get("precision_on_eligible"),
            "provenance_missing_counts": {
                "document_fields": provenance.get("document_field_missing_count"),
                "assertions": provenance.get("assertion_missing_count"),
                "projections": provenance.get("projection_missing_count"),
                "direct_answers": provenance.get("direct_answer_missing_count"),
            },
            "real_corpus_fixture_count": real_corpus.get("fixture_count"),
            "real_corpus_fixture_pass_ratio": real_corpus.get("pass_ratio"),
            "shadow_subset_item_count": shadow_subset.get("item_count"),
            "shadow_improved_assertion_count": shadow_delta.get("improved_assertion_count"),
        },
        "superseded_tracked_paths": superseded_tracked_paths,
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_truth_index_markdown(payload: Dict[str, Any]) -> str:
    metrics = payload["summary_metrics"]
    lines = [
        "# Rules-First Chunk/Proposition Pilot Truth Index",
        "",
        "This tracked index is the public source of truth for where current pilot artifacts live.",
        "Generated outputs remain canonical in `.artifacts`; tracked `reports/` snapshots are historical unless this file says otherwise.",
        "",
        "## Canonical Artifact Roots",
        "",
    ]
    for path in payload["canonical_artifact_roots"]:
        lines.append(f"- `{path}`")
    lines.extend(
        [
            f"- shadow subset: `{payload['shadow_subset_root']}`",
            "",
            "## Current Canonical Metrics",
            "",
            f"- structural gate passed: `{metrics['structural_gate_passed']}`",
            f"- semantic gate passed: `{metrics['semantic_gate_passed']}`",
            f"- retrieval gate passed: `{metrics['retrieval_gate_passed']}`",
            f"- direct-answer gate passed: `{metrics['direct_answer_gate_passed']}`",
            f"- retrieval top-3 expected hit ratio: `{metrics['retrieval_top3_expected_hit_ratio']}`",
            f"- expanded frozen query count: `{metrics['expanded_frozen_query_count']}`",
            f"- expanded frozen query pass ratio: `{metrics['expanded_frozen_query_pass_ratio']}`",
            f"- direct-answer precision on eligible: `{metrics['direct_answer_precision_on_eligible']}`",
            f"- real-corpus fixture count: `{metrics['real_corpus_fixture_count']}`",
            f"- real-corpus fixture pass ratio: `{metrics['real_corpus_fixture_pass_ratio']}`",
            f"- shadow subset item count: `{metrics['shadow_subset_item_count']}`",
            f"- shadow improved assertion count: `{metrics['shadow_improved_assertion_count']}`",
            "",
            "## Superseded Tracked Paths",
            "",
            "The following tracked reports are historical snapshots and are superseded by the canonical artifact roots above:",
            "",
        ]
    )
    for path in payload["superseded_tracked_paths"]:
        lines.append(f"- `{path}`")
    lines.append("")
    return "\n".join(lines)


def _build_local_audit_memo(payload: Dict[str, Any]) -> str:
    metrics = payload["summary_metrics"]
    return "\n".join(
        [
            "# Chunk Processing Pilot Local Audit Memo",
            "",
            "Current framing: `rules-first chunk/proposition pilot`.",
            "",
            "## Current Truth",
            "",
            f"- canonical confirmation roots: `{payload['canonical_artifact_roots'][0]}` and `{payload['canonical_artifact_roots'][1]}`",
            f"- latest confirmation root: `{payload['latest_confirmation_run_root']}`",
            f"- shadow subset root: `{payload['shadow_subset_root']}`",
            "",
            "## Metrics",
            "",
            f"- structural gate passed: `{metrics['structural_gate_passed']}`",
            f"- semantic gate passed: `{metrics['semantic_gate_passed']}`",
            f"- retrieval gate passed: `{metrics['retrieval_gate_passed']}`",
            f"- direct-answer gate passed: `{metrics['direct_answer_gate_passed']}`",
            f"- expanded frozen query pass ratio: `{metrics['expanded_frozen_query_pass_ratio']}`",
            f"- real-corpus fixture pass ratio: `{metrics['real_corpus_fixture_pass_ratio']}`",
            f"- provenance missing (document/assertion/projection/direct-answer): `{metrics['provenance_missing_counts']['document_fields']}/{metrics['provenance_missing_counts']['assertions']}/{metrics['provenance_missing_counts']['projections']}/{metrics['provenance_missing_counts']['direct_answers']}`",
            "",
            "## Repo Hygiene",
            "",
            "Tracked generated pilot markdown/json under `reports/competition_runs/pilots/chunk_processing_pilot_v1/` are historical and superseded.",
            "Current truth lives in `.artifacts` and is indexed by `chunk_processing_pilot_truth_index.md`.",
            "",
        ]
    )


def main() -> int:
    payload = build_truth_index_payload()
    _write_json(TRUTH_INDEX_JSON, payload)
    _write_md(TRUTH_INDEX_MD, _build_truth_index_markdown(payload))
    _write_md(AUDIT_MEMO_MD, _build_local_audit_memo(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
