from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_chunk_semantic_shadow_subset import (  # noqa: E402
    MANIFEST_PATH,
    REPO_DELIVERABLE_DIR,
    _build_shadow_delta_report,
    _summary_results_payload,
)


def test_shadow_delta_report_contains_required_comparison_columns() -> None:
    report = _build_shadow_delta_report(
        {
            "items": [
                {
                    "comparison": {
                        "item_id": "employment_article11_no_waiver",
                        "evaluation_bucket": "law_condition_negation",
                        "source_kind": "real_chunk",
                        "assertion_count_delta": 1,
                        "condition_preserved": True,
                        "exception_preserved": True,
                        "polarity_preserved": True,
                        "money_amount_extracted": True,
                        "deadline_extracted": True,
                        "interest_extracted": False,
                        "unsupported_or_abstain_behavior": None,
                        "provenance_complete": True,
                    }
                }
            ]
        }
    )

    assert report["report_version"] == "chunk_processing_shadow_delta_report_v2"
    assert report["item_count"] == 1
    item = report["items"][0]
    assert "assertion_count_delta" in item
    assert "condition_preserved" in item
    assert "exception_preserved" in item
    assert "polarity_preserved" in item
    assert "money_amount_extracted" in item
    assert "deadline_extracted" in item
    assert "interest_extracted" in item
    assert "unsupported_or_abstain_behavior" in item
    assert "provenance_complete" in item
    summary = _summary_results_payload(report)
    assert summary["recommendation"] == "remain_experimental"


def test_shadow_manifest_exists_and_covers_required_buckets() -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == "chunk_semantics_shadow_subset_v1"
    items = payload["items"]
    assert 10 <= len(items) <= 15
    buckets = {str(item.get("evaluation_bucket", "")) for item in items}
    assert "law_condition_negation" in buckets or "law_invalidity" in buckets
    assert "history_notice" in buckets
    assert "regulation" in buckets
    assert "case_order_costs" in buckets
    assert "adversarial_no_answer" in buckets
    for item in items:
        assert str(item.get("doc_id", "")).strip()
        assert str(item.get("page_id", "")).strip()
        assert str(item.get("chunk_id", "")).strip()
        assert str(item.get("doc_type", "")).strip()
        assert str(item.get("section_kind", "")).strip()
        assert str(item.get("reason_for_selection", "")).strip()


def test_repo_deliverable_dir_matches_step6_contract() -> None:
    assert REPO_DELIVERABLE_DIR == ROOT / "reports" / "chunk_semantics"
