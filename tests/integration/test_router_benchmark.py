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
    assert "overall_accuracy" in payload
    assert isinstance(payload["mismatches"], list)
    assert "# Router Benchmark Summary" in markdown
    assert "## Confusion Matrix" in markdown
    assert "## Mismatches (" in markdown


def test_router_benchmark_mismatch_rendering_format() -> None:
    module = _load_module()
    lines = module.render_mismatch_lines(
        [
            {
                "question_id": "q-1",
                "expected_primary_route": "case_cross_compare",
                "predicted_primary_route": "case_outcome_or_value",
                "runtime_route": "single_case_extraction",
                "question": "Which case was decided earlier: A or B?",
            }
        ]
    )

    assert len(lines) == 1
    assert re.fullmatch(
        r"- \[q-1\] expected=case_cross_compare predicted=case_outcome_or_value runtime=single_case_extraction :: .+",
        lines[0],
    )

