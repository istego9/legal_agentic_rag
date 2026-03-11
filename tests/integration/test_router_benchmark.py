from __future__ import annotations

from dataclasses import dataclass
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
    assert all(
        route_name in {
            "case_entity_lookup",
            "case_outcome_or_value",
            "case_cross_compare",
            "law_article_lookup",
            "law_relation_or_history",
            "law_scope_or_definition",
            "cross_law_compare",
            "negative_or_unanswerable",
            "__unmapped__",
        }
        for route_name in payload["normalized_taxonomy_route_counts"]
    )
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
    assert "- benchmark_target: `services.runtime.router.resolve_route_decision`" in markdown


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


def test_router_benchmark_consumes_explicit_runtime_metadata(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    dataset_path = tmp_path / "public_dataset.json"
    taxonomy_path = tmp_path / "taxonomy.jsonl"

    dataset_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-1",
                    "question": "According to Article 10, what is required?",
                    "answer_type": "free_text",
                },
                {
                    "id": "q-2",
                    "question": "Summarize the ruling in case CFI 010/2024.",
                    "answer_type": "free_text",
                },
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    taxonomy_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "q-1",
                        "question": "According to Article 10, what is required?",
                        "answer_type_expected": "free_text",
                        "primary_route": "law_article_lookup",
                        "document_scope": "single_doc",
                        "target_doc_types": ["law"],
                        "evidence_topology": "single_page",
                        "temporal_sensitivity": "current_version",
                        "answerability_risk": "low",
                        "notes": "unit test row",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "question_id": "q-2",
                        "question": "Summarize the ruling in case CFI 010/2024.",
                        "answer_type_expected": "free_text",
                        "primary_route": "case_outcome_or_value",
                        "document_scope": "single_doc",
                        "target_doc_types": ["case"],
                        "evidence_topology": "single_page",
                        "temporal_sensitivity": "none",
                        "answerability_risk": "low",
                        "notes": "unit test row",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    @dataclass(frozen=True)
    class FakeDecision:
        raw_route: str
        taxonomy_subroute: str | None
        normalized_taxonomy_route: str | None
        route_signals: dict[str, bool]
        target_doc_types_guess: list[str]
        document_scope_guess: str | None
        temporal_sensitivity_guess: str | None
        matched_rules: list[str]
        confidence: float
        decision_version: str

    def fake_resolve_route_decision(question: dict[str, object]) -> FakeDecision:
        question_id = str(question.get("id", ""))
        if question_id == "q-1":
            return FakeDecision(
                raw_route="article_lookup",
                taxonomy_subroute=None,
                normalized_taxonomy_route="law_article_lookup",
                route_signals={"has_article_signal": True},
                target_doc_types_guess=["law"],
                document_scope_guess="single_doc",
                temporal_sensitivity_guess="current_version",
                matched_rules=["unit-test-explicit-route"],
                confidence=0.99,
                decision_version="route_decision.test",
            )
        return FakeDecision(
            raw_route="single_case_extraction",
            taxonomy_subroute="case_outcome_or_value",
            normalized_taxonomy_route=None,
            route_signals={"has_case_signal": True},
            target_doc_types_guess=["case"],
            document_scope_guess="single_doc",
            temporal_sensitivity_guess="none",
            matched_rules=["unit-test-explicit-subroute"],
            confidence=0.95,
            decision_version="route_decision.test",
        )

    monkeypatch.setattr(module, "resolve_route_decision", fake_resolve_route_decision)
    results = module.run_router_benchmark(
        public_dataset_path=dataset_path,
        taxonomy_path=taxonomy_path,
    )

    assert results["total_questions"] == 2
    assert results["raw_route_correct_predictions"] == 0
    assert results["normalized_route_correct_predictions"] == 2
    assert results["raw_route_accuracy"] == 0.0
    assert results["normalized_route_accuracy"] == 1.0
    assert results["normalized_taxonomy_route_counts"]["law_article_lookup"] == 1
    assert results["normalized_taxonomy_route_counts"]["case_outcome_or_value"] == 1
    assert results["mismatches"] == []


def test_router_benchmark_delta_report_shape() -> None:
    delta_path = ROOT / "reports" / "router_benchmark_delta.md"
    assert delta_path.exists()
    content = delta_path.read_text(encoding="utf-8")

    assert "# Router Benchmark Delta" in content
    assert "## Metrics" in content
    assert "raw_route_accuracy" in content
    assert "normalized_route_accuracy" in content
    assert "normalized_macro_f1" in content
    assert "## Dead Routes" in content
    assert "## Top Confusion Pairs (After)" in content
