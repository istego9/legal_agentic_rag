from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "chunk_processing_pilot_v1.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_expanded_query_contract_has_required_coverage() -> None:
    fixture = _load_fixture()
    expanded = fixture["expanded_queries"]
    assert 20 <= len(expanded) <= 25

    category_counts: dict[str, int] = {}
    for item in expanded:
        category = str(item["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
        assert item["question_id"]
        assert item["question"]
        assert item["answer_type"]
        assert item["expected_action"] in {"answer", "abstain"}
        assert item["expected_source_family"]
        assert isinstance(item["source_reference"], dict)
        assert isinstance(item["direct_answer_expected"], dict)

    assert category_counts["law_article_history"] >= 8
    assert category_counts["compare"] >= 4
    assert category_counts["case_order_costs_deadline"] >= 4
    assert category_counts["adversarial_no_answer"] >= 2

    coverage_kinds = {str(item.get("coverage_kind", "")) for item in expanded}
    assert "regulation_related" in coverage_kinds
    assert "commencement_style" in coverage_kinds


def test_real_corpus_checks_and_synthetic_fixtures_are_explicitly_classified() -> None:
    fixture = _load_fixture()

    real_corpus_checks = fixture["real_corpus_checks"]
    assert len(real_corpus_checks) >= 3
    assert {item["fixture_classification"] for item in real_corpus_checks} == {"real_corpus_fixture"}
    assert any(item["coverage_kind"] == "public_adversarial_no_answer" for item in real_corpus_checks)

    semantic_gate_fixtures = fixture["semantic_gate_fixtures"]
    assert {item["fixture_classification"] for item in semantic_gate_fixtures} == {"synthetic_guardrail_fixture"}

    shadow_subset = fixture["shadow_subset"]
    assert any(item["shadow_kind"] == "synthetic_fixture" for item in shadow_subset)
    assert any(item["shadow_kind"] == "real_public_question" for item in shadow_subset)
