from __future__ import annotations

from scripts.run_chunk_semantic_shadow_subset import _build_shadow_delta_report


def test_shadow_delta_report_contains_required_comparison_columns() -> None:
    report = _build_shadow_delta_report(
        {
            "items": [
                {
                    "item_id": "employment_article_11_chunk_family",
                    "shadow_kind": "real_chunk_family",
                    "rules_first": {
                        "assertion_count": 0,
                        "provenance_complete": True,
                        "has_conditions_or_exceptions": False,
                        "has_money": False,
                        "has_interest": False,
                        "query_results": [{"action_match": False}],
                    },
                    "llm_assisted": {
                        "assertion_count": 3,
                        "provenance_complete": True,
                        "has_conditions_or_exceptions": True,
                        "has_money": False,
                        "has_interest": False,
                        "query_results": [{"action_match": True}],
                    },
                }
            ]
        }
    )

    assert report["report_version"] == "chunk_processing_shadow_delta_report_v1"
    assert report["item_count"] == 1
    item = report["items"][0]
    assert "rules_first_assertion_count" in item
    assert "llm_assisted_assertion_count" in item
    assert "rules_first_provenance_complete" in item
    assert "llm_assisted_provenance_complete" in item
    assert report["condition_improvement_count"] == 1
