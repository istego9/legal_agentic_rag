from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime.proposition_layer import proposition_match_features, try_direct_answer  # noqa: E402


def _candidate() -> dict:
    return {
        "paragraph": {"paragraph_id": "para-1"},
        "chunk_projection": {
            "semantic_query_terms": ["employee", "waive", "rights", "written agreement", "article 11"],
            "semantic_assertions": [
                {
                    "assertion_id": "assertion-1",
                    "subject_text": "Employee",
                    "relation_type": "may_waive",
                    "object_text": "rights under this Law by written agreement",
                    "modality": "permission",
                    "condition_text": "subject to Article 66(13); legal advice or court mediation",
                    "exception_text": "",
                    "citation_refs": ["Article 11(2)(b)"],
                    "confidence": 0.91,
                    "dense_paraphrase": "An employee may waive rights under the law in a written agreement if Article 66(13) and legal-advice-or-mediation conditions are met.",
                    "polarity": "affirmative",
                    "evidence": {
                        "source_page_ids": ["employment_10"],
                        "page_numbers_0": [10],
                        "page_numbers_1": [11],
                        "char_start": 120,
                        "char_end": 320,
                    },
                    "direct_answer": {
                        "eligible": True,
                        "answer_type": "boolean",
                        "boolean_value": True,
                        "number_value": None,
                        "date_value": None,
                        "text_value": None,
                    },
                }
            ],
        },
    }


def _case_candidate() -> dict:
    return {
        "exact_identifier_hit": True,
        "paragraph": {
            "paragraph_id": "case-para-1",
            "document_id": "case-doc-1",
            "text": "The Applicant shall pay USD 155,879.50 within 14 days, failing which interest shall accrue at 9% per annum.",
        },
        "chunk_projection": {
            "court_name": "Court Of Appeal",
            "money_values": ["USD 155,879.50"],
            "semantic_query_terms": ["costs", "14 days", "9% interest"],
            "semantic_assertions": [
                {
                    "assertion_id": "case-assert-1",
                    "subject_text": "Applicant",
                    "relation_type": "ordered_to_pay",
                    "object_text": "USD 155,879.50 within 14 days",
                    "modality": "obligation",
                    "citation_refs": ["CA 004/2025"],
                    "dense_paraphrase": "Applicant must pay USD 155,879.50 within 14 days; interest accrues at 9% per annum if unpaid.",
                    "evidence": {
                        "source_page_ids": ["ca004_3"],
                        "page_numbers_0": [3],
                        "page_numbers_1": [4],
                    },
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                }
            ],
        },
    }


def test_proposition_match_features_detects_overlap() -> None:
    features = proposition_match_features(
        question_text="Can an employee waive rights under this law by written agreement?",
        question_structure={"article_refs": [], "case_numbers": []},
        candidate=_candidate(),
    )
    assert features["semantic_boost"] > 0
    assert features["semantic_terms_hit_count"] >= 2
    assert features["top_proposition"]["relation_type"] == "may_waive"


def test_direct_answer_returns_boolean_hint_for_lookup_question() -> None:
    result = try_direct_answer(
        question_text="Can an employee waive rights under this law by written agreement?",
        answer_type="boolean",
        route_name="article_lookup",
        candidates=[_candidate()],
    )
    assert result is not None
    assert result["answer"] is True
    assert result["trace"]["direct_answer_used"] is True
    assert result["trace"]["top_proposition"]["evidence"]["source_page_ids"] == ["employment_10"]


def test_direct_answer_abstains_when_top_assertion_has_conditions() -> None:
    candidate = _candidate()
    candidate["chunk_projection"]["semantic_assertions"][0]["conditions"] = [
        "written agreement with employer",
        "subject to Article 66(13)",
    ]
    result = try_direct_answer(
        question_text="Can an employee waive rights under this law by written agreement?",
        answer_type="boolean",
        route_name="article_lookup",
        candidates=[candidate],
    )
    assert result is None


def test_direct_answer_abstains_when_competing_propositions_are_too_close() -> None:
    first = _candidate()
    second = _candidate()
    second["chunk_projection"]["semantic_assertions"][0]["relation_type"] = "is_void"
    second["chunk_projection"]["semantic_assertions"][0]["modality"] = "prohibition"
    second["chunk_projection"]["semantic_assertions"][0]["object_text"] = "employee waiver of rights under this Law is void in all circumstances"
    second["chunk_projection"]["semantic_assertions"][0]["dense_paraphrase"] = "An employee waiver of rights under this Law is void in all circumstances."
    result = try_direct_answer(
        question_text="Can an employee waive rights under this law?",
        answer_type="boolean",
        route_name="article_lookup",
        candidates=[first, second],
    )
    assert result is None


def test_direct_answer_extracts_number_from_case_candidate_text() -> None:
    result = try_direct_answer(
        question_text="In CA 004/2025, if the costs are not paid within fourteen days, at what annual rate does interest accrue?",
        answer_type="number",
        route_name="single_case_extraction",
        candidates=[_case_candidate()],
    )
    assert result is not None
    assert result["answer"] == 9
    assert result["trace"]["path"] == "deterministic_percent_pattern"


def test_direct_answer_extracts_cost_amount_from_case_candidate_text() -> None:
    result = try_direct_answer(
        question_text="In Coinmena, what total sum must the Applicant pay as the Costs Award?",
        answer_type="number",
        route_name="single_case_extraction",
        candidates=[_case_candidate()],
    )
    assert result is not None
    assert result["answer"] == 155879.5
    assert result["trace"]["path"] == "deterministic_money_pattern"


def test_direct_answer_extracts_court_name_from_case_projection() -> None:
    result = try_direct_answer(
        question_text="Which court issued the order in CA 004/2025?",
        answer_type="name",
        route_name="single_case_extraction",
        candidates=[_case_candidate()],
    )
    assert result is not None
    assert result["answer"] == "Court Of Appeal"
    assert result["trace"]["path"] == "deterministic_court_name"


def test_direct_answer_extracts_suffix_currency_amount() -> None:
    candidate = _case_candidate()
    candidate["paragraph"]["text"] = "The Respondent shall pay 10,000 AED within 7 days."
    candidate["chunk_projection"]["money_values"] = ["10,000 AED"]
    candidate["chunk_projection"]["semantic_assertions"][0]["object_text"] = "10,000 AED within 7 days"
    candidate["chunk_projection"]["semantic_assertions"][0]["dense_paraphrase"] = "The respondent must pay 10,000 AED within 7 days."
    result = try_direct_answer(
        question_text="What amount must the Respondent pay?",
        answer_type="number",
        route_name="single_case_extraction",
        candidates=[candidate],
    )
    assert result is not None
    assert result["answer"] == 10000
    assert result["trace"]["path"] == "deterministic_money_pattern"


def test_direct_answer_does_not_support_free_text_shortcuts() -> None:
    result = try_direct_answer(
        question_text="Explain the operative effect of Article 11.",
        answer_type="free_text",
        route_name="article_lookup",
        candidates=[_candidate()],
    )
    assert result is None
