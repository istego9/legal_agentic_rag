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
            "id": "law-family-test",
            "question": question,
            "answer_type": answer_type,
        }
    )


def test_article_lookup_is_not_swallowed_by_cross_law_compare() -> None:
    decision = _decision(
        "According to Article 17(1) of the Strata Title Law, what type of resolution is required?",
        answer_type="free_text",
    )
    assert decision.raw_route == "article_lookup"
    assert decision.normalized_taxonomy_route == "law_article_lookup"


def test_history_lineage_is_not_swallowed_by_cross_law_compare() -> None:
    decision = _decision(
        "Which laws were amended by DIFC Law No. 2 of 2022?",
        answer_type="free_text",
    )
    assert decision.raw_route == "history_lineage"
    assert decision.normalized_taxonomy_route == "law_relation_or_history"


def test_history_enactment_cue_is_not_swallowed_by_article_lookup() -> None:
    decision = _decision(
        "On what date was Article 5 of DIFC Law No. 3 of 2018 enacted?",
        answer_type="date",
    )
    assert decision.raw_route == "history_lineage"
    assert decision.normalized_taxonomy_route == "law_relation_or_history"


def test_history_supersession_cue_is_not_swallowed_by_article_lookup() -> None:
    decision = _decision(
        "Was Article 7 of DIFC Law No. 1 of 2005 superseded by a later law?",
        answer_type="boolean",
    )
    assert decision.raw_route == "history_lineage"
    assert decision.normalized_taxonomy_route == "law_relation_or_history"


def test_true_multi_law_compare_stays_cross_law_compare() -> None:
    decision = _decision(
        "Was the Employment Law enacted in the same year as the Intellectual Property Law?",
        answer_type="boolean",
    )
    assert decision.raw_route == "cross_law_compare"
    assert decision.normalized_taxonomy_route == "cross_law_compare"


def test_law_scope_or_definition_route_remains_live() -> None:
    decision = _decision(
        "What is the law number of the Data Protection Law?",
        answer_type="name",
    )
    assert decision.raw_route == "article_lookup"
    assert decision.normalized_taxonomy_route == "law_scope_or_definition"


def test_plural_law_filter_query_routes_to_cross_law_compare() -> None:
    decision = _decision(
        "Which laws mention interpretative provisions in their schedules?",
        answer_type="free_text",
    )
    assert decision.raw_route == "cross_law_compare"
    assert decision.normalized_taxonomy_route == "cross_law_compare"
