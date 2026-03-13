from __future__ import annotations

import json
from pathlib import Path

from scripts.regenerate_chunk_processing_truth_index import build_truth_index_payload


ROOT = Path(__file__).resolve().parents[2]
TRUTH_INDEX_JSON = ROOT / "reports" / "corpus_investigation" / "2026-03-12-version-lineage-rca" / "chunk_processing_pilot_truth_index.json"


def test_truth_index_payload_points_to_canonical_roots() -> None:
    payload = build_truth_index_payload()
    canonical_roots = [Path(path) for path in payload["canonical_artifact_roots"]]
    assert len(canonical_roots) == 2
    for root in canonical_roots:
        assert root.exists()
        assert (root / "fixture_gate_report.json").exists()
        assert (root / "expanded_frozen_query_report.json").exists()
    shadow_root = Path(payload["shadow_subset_root"])
    assert shadow_root.exists()
    assert (shadow_root / "shadow_subset_report.json").exists()
    assert (shadow_root / "shadow_delta_report.json").exists()


def test_tracked_truth_index_file_has_superseded_paths() -> None:
    payload = json.loads(TRUTH_INDEX_JSON.read_text(encoding="utf-8"))
    assert payload["program_label"] == "rules-first chunk/proposition pilot"
    assert len(payload["superseded_tracked_paths"]) >= 3
    for rel_path in payload["superseded_tracked_paths"]:
        assert (ROOT / rel_path).exists()
