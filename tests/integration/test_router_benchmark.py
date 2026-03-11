from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "router_benchmark.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("router_benchmark", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_router_benchmark_script_smoke(tmp_path: Path) -> None:
    module = _load_module()
    markdown_output = tmp_path / "router_benchmark_summary.md"
    json_output = tmp_path / "router_benchmark_results.json"

    rc = module.main(
        [
            "--markdown-output",
            str(markdown_output),
            "--json-output",
            str(json_output),
        ]
    )

    assert rc == 0
    assert markdown_output.exists()
    assert json_output.exists()

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["total_questions"] == 100
    assert "raw_route_accuracy" in payload
    assert "normalized_route_accuracy" in payload
    assert "normalized_macro_f1" in payload
    assert "raw_runtime_route_counts" in payload
    assert "raw_predicted_route_counts" in payload
    assert "normalized_taxonomy_route_counts" in payload
    assert "top_confusion_pairs" in payload
    assert "dead_routes" in payload
    assert "per_route_metrics" in payload
    assert isinstance(payload["mismatches"], list)
    assert isinstance(payload["top_confusion_pairs"], list)
    assert isinstance(payload["dead_routes"], list)
    support_total = sum(int(row["support"]) for row in payload["per_route_metrics"])
    raw_total = sum(int(count) for count in payload["raw_runtime_route_counts"].values())
    normalized_total = sum(int(count) for count in payload["normalized_taxonomy_route_counts"].values())
    assert support_total == payload["total_questions"]
    assert raw_total == payload["total_questions"]
    assert normalized_total == payload["total_questions"]
    assert "__unmapped__" in payload["normalized_taxonomy_route_counts"]
    assert "# Router Benchmark Summary" in markdown
    assert "- raw_route_accuracy:" in markdown
    assert "- normalized_route_accuracy:" in markdown
    assert "- normalized_macro_f1:" in markdown
    assert "## Predicted Count By Raw Runtime Route" in markdown
    assert "## Predicted Count By Normalized Taxonomy Route" in markdown
    assert "## Top Confusion Pairs" in markdown
    assert "## Dead Routes" in markdown
    assert "## Confusion Matrix" in markdown
    assert "## Mismatches (" in markdown


def test_router_benchmark_mismatch_rendering_format() -> None:
    module = _load_module()
    lines = module.render_mismatch_lines(
        [
            {
                "question_id": "q-1",
                "expected_primary_route": "case_cross_compare",
                "raw_predicted_route": "__unmapped__",
                "normalized_predicted_route": "__unmapped__",
                "raw_runtime_route": "single_case_extraction",
                "normalization_source": "raw_unmapped",
                "question": "Which case was decided earlier: A or B?",
            }
        ]
    )

    assert len(lines) == 1
    assert re.fullmatch(
        r"- \[q-1\] expected=case_cross_compare raw_mapped=__unmapped__ normalized=__unmapped__ "
        r"raw_runtime=single_case_extraction source=raw_unmapped :: .+",
        lines[0],
    )


def test_router_benchmark_dead_route_detection() -> None:
    module = _load_module()
    dead_routes = module.detect_dead_routes(
        [
            {"primary_route": "case_cross_compare", "support": 17, "predicted": 0},
            {"primary_route": "law_article_lookup", "support": 31, "predicted": 33},
            {"primary_route": "negative_or_unanswerable", "support": 4, "predicted": 0},
        ]
    )
    assert dead_routes == [
        {"primary_route": "case_cross_compare", "support": 17, "predicted": 0},
        {"primary_route": "negative_or_unanswerable", "support": 4, "predicted": 0},
    ]
