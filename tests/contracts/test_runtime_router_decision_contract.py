from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.public_question_taxonomy import PRIMARY_ROUTES  # noqa: E402
from packages.router.heuristics import ROUTE_DECISION_VERSION  # noqa: E402
from services.runtime.router import resolve_route, resolve_route_decision  # noqa: E402


def test_resolve_route_decision_contract_shape() -> None:
    decision = resolve_route_decision(
        {
            "id": "q-article",
            "question": "According to Article 10 of the Employment Law 2019, how many months are allowed?",
            "answer_type": "number",
        }
    )

    assert isinstance(decision.raw_route, str)
    assert decision.raw_route
    assert decision.decision_version == ROUTE_DECISION_VERSION
    assert isinstance(decision.route_signals, dict)
    assert decision.route_signals
    assert all(isinstance(key, str) for key in decision.route_signals)
    assert all(isinstance(value, bool) for value in decision.route_signals.values())
    assert isinstance(decision.target_doc_types_guess, list)
    assert decision.target_doc_types_guess
    assert all(isinstance(item, str) for item in decision.target_doc_types_guess)
    assert decision.document_scope_guess in {"single_doc", "cross_doc", None}
    assert decision.temporal_sensitivity_guess in {"none", "current_version", "historical_version", None}
    assert isinstance(decision.matched_rules, list)
    assert decision.matched_rules
    assert all(isinstance(item, str) for item in decision.matched_rules)
    assert isinstance(decision.confidence, float)
    if decision.taxonomy_subroute is not None:
        assert decision.taxonomy_subroute in PRIMARY_ROUTES
    if decision.normalized_taxonomy_route is not None:
        assert decision.normalized_taxonomy_route in PRIMARY_ROUTES


def test_resolve_route_is_backward_compatible_wrapper() -> None:
    questions = [
        {
            "id": "q-case",
            "question": "Who were the claimants in case CFI 010/2024?",
            "answer_type": "names",
        },
        {
            "id": "q-history",
            "question": "What is the amendment history of Law No. 1 of 2025?",
            "answer_type": "free_text",
        },
        {
            "id": "q-compare",
            "question": "Compare case CFI 010/2024 versus CA 004/2025.",
            "answer_type": "free_text",
        },
    ]

    for question in questions:
        assert resolve_route(question) == resolve_route_decision(question).raw_route


def test_resolve_route_decision_exposes_core_signals() -> None:
    decision = resolve_route_decision(
        {
            "id": "q-signals",
            "question": (
                "Compare case CFI 010/2024 versus ENF 053/2025, including article history and jury mentions."
            ),
            "answer_type": "free_text",
        }
    )

    assert decision.route_signals["has_compare_signal"] is True
    assert decision.route_signals["has_case_signal"] is True
    assert decision.route_signals["has_article_signal"] is True
    assert decision.route_signals["has_history_signal"] is True
    assert decision.route_signals["has_negative_signal"] is True
