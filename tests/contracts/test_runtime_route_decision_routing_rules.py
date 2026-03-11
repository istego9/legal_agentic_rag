from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime.router import resolve_route_decision  # noqa: E402


def _decision(question: str, answer_type: str = "free_text"):
    return resolve_route_decision(
        {
            "id": "test-q",
            "question": question,
            "answer_type": answer_type,
        }
    )


def test_case_cross_compare_detection_for_common_party_question() -> None:
    decision = _decision(
        "Do cases CA 004/2025 and SCT 295/2025 involve any of the same legal entities or individuals as parties?",
        answer_type="boolean",
    )
    assert decision.raw_route == "cross_case_compare"
    assert decision.normalized_taxonomy_route == "case_cross_compare"
    assert decision.route_signals["has_case_cross_compare_signal"] is True


def test_case_cross_compare_detection_for_between_without_case_keyword() -> None:
    decision = _decision(
        "Between ARB 034/2025 and SCT 295/2025, which was issued first?",
        answer_type="name",
    )
    assert decision.raw_route == "cross_case_compare"
    assert decision.normalized_taxonomy_route == "case_cross_compare"


def test_cross_law_compare_detection_for_multi_law_question() -> None:
    decision = _decision(
        "Was the Employment Law enacted in the same year as the Intellectual Property Law?",
        answer_type="boolean",
    )
    assert decision.raw_route == "cross_law_compare"
    assert decision.normalized_taxonomy_route == "cross_law_compare"
    assert decision.route_signals["has_law_cross_compare_signal"] is True


def test_cross_law_compare_precedence_over_history_lineage() -> None:
    decision = _decision(
        "Was the Strata Title Law Amendment Law enacted on the same day as the Financial Collateral Regulations came into force?",
        answer_type="boolean",
    )
    assert decision.raw_route == "cross_law_compare"
    assert decision.normalized_taxonomy_route == "cross_law_compare"


def test_negative_or_unanswerable_detection_for_jury_question() -> None:
    decision = _decision(
        "What did the jury decide in case ENF 053/2025?",
    )
    assert decision.raw_route == "no_answer"
    assert decision.normalized_taxonomy_route == "negative_or_unanswerable"
    assert decision.route_signals["has_strong_negative_signal"] is True


def test_cross_case_precedence_over_negative_signal() -> None:
    decision = _decision(
        "Did cases ENF 053/2025 and CFI 057/2025 have the same jury decision?",
        answer_type="boolean",
    )
    assert decision.raw_route == "cross_case_compare"
    assert decision.normalized_taxonomy_route == "case_cross_compare"
