from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import QueryResponse, Telemetry  # noqa: E402
from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.routers import qa as qa_router  # noqa: E402
from services.runtime.law_article_lookup import resolve_law_article_lookup_intent  # noqa: E402
from services.runtime.solvers import normalize_answer, solve_deterministic  # noqa: E402


def _runtime_policy(*, return_debug_trace: bool) -> dict:
    return {
        "use_llm": True,
        "max_candidate_pages": 8,
        "max_context_paragraphs": 8,
        "page_index_base_export": 0,
        "scoring_policy_version": "contest_v2026_public_rules_v1",
        "allow_dense_fallback": False,
        "return_debug_trace": return_debug_trace,
    }


def test_law_article_resolution_extracts_law_article_and_subarticle() -> None:
    intent = resolve_law_article_lookup_intent(
        "According to Article 14(2)(b) of the General Partnership Law 2004, how many years apply?"
    )

    assert intent["resolver_version"] == "law_article_lookup_resolution_v1"
    assert intent["law_identifier"] == "general_partnership_law_2004"
    assert intent["article_identifier"] == "14"
    assert intent["subarticle_identifier"] == "2.b"
    assert intent["law_year"] == "2004"
    assert intent["resolved_doc_type_guess"] == "law"
    assert intent["provision_lookup_confidence"] >= 0.8


def test_law_article_resolution_parses_section_clause_and_law_number_year() -> None:
    intent = resolve_law_article_lookup_intent(
        "Under Section 5(1) and Clause (c) of DIFC Regulation No. 3 of 2020, what is required?"
    )

    assert intent["section_identifier"] == "5"
    assert intent["clause_identifier"] == "c"
    assert intent["law_number"] == "3"
    assert intent["law_year"] == "2020"
    assert intent["resolved_doc_type_guess"] == "regulation"
    assert intent["requires_structural_lookup"] is True


def test_structural_match_recovers_article_hit_from_chunk_text_when_projection_lacks_anchor() -> None:
    intent = resolve_law_article_lookup_intent("What is stated in article 1?")
    hits = qa_router._structural_match(
        qa_router._question_structure("What is stated in article 1?", lookup_intent=intent),
        {
            "paragraph": {"text": "Article 1 placeholder"},
            "chunk_projection": {"text_clean": "Article 1 placeholder"},
        },
    )

    assert hits["article"] is True


def test_answer_normalization_contract_covers_free_text_and_typed_values() -> None:
    normalized_boolean, normalized_boolean_text = normalize_answer(" YES ", "boolean")
    normalized_number, normalized_number_text = normalize_answer("AED 12,500.00", "number")
    normalized_date, normalized_date_text = normalize_answer("7 March 2024", "date")
    normalized_free_text, normalized_free_text_text = normalize_answer("  this   is   stable  ", "free_text")

    assert normalized_boolean is True
    assert normalized_boolean_text == "true"
    assert normalized_number == 12500
    assert normalized_number_text == "12500"
    assert normalized_date == "2024-03-07"
    assert normalized_date_text == "2024-03-07"
    assert normalized_free_text == "this is stable"
    assert normalized_free_text_text == "this is stable"


def test_page_level_source_formatting_is_preserved_in_query_response() -> None:
    page_ref = qa_router._to_page_ref(
        {
            "paragraph": {
                "paragraph_id": "para-1",
                "page_id": "page-1",
                "document_id": "doc-1",
                "text": "Article 12 text",
                "article_refs": ["12"],
            },
            "page": {
                "page_id": "page-1",
                "source_page_id": "law_7",
            },
            "chunk_projection": {"entity_names": [], "exact_terms": []},
            "score": 0.9,
            "exact_identifier_hit": True,
            "lineage_signal": False,
        },
        "proj-1",
        used=True,
        page_index_base=0,
    )
    response = QueryResponse(
        question_id="q-page-ref",
        answer="answer",
        answer_normalized="answer",
        answer_type="free_text",
        confidence=0.9,
        route_name="article_lookup",
        abstained=False,
        sources=[page_ref],
        telemetry=Telemetry(
            request_started_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
            first_token_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
            completed_at=datetime(2026, 3, 11, tzinfo=timezone.utc),
            ttft_ms=5,
            total_response_ms=10,
            time_per_output_token_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            model_name="deterministic-router",
            route_name="article_lookup",
            search_profile="article_lookup_recall_v2",
            telemetry_complete=True,
            trace_id="trace-page-ref",
        ),
        debug=None,
    ).model_dump(mode="json")

    source = response["sources"][0]
    assert source["source_page_id"] == "law_7"
    assert source["pdf_id"] == "law"
    assert source["page_num"] == 7
    assert set(source.keys()) == {
        "project_id",
        "document_id",
        "pdf_id",
        "page_num",
        "page_index_base",
        "source_page_id",
        "used",
        "evidence_role",
        "score",
    }


def test_no_silent_fallback_blocks_unresolved_law_article_lookup(monkeypatch) -> None:
    client = TestClient(app)
    llm_called = {"value": False}

    async def _unexpected_llm_call(*args, **kwargs):  # type: ignore[no-untyped-def]
        llm_called["value"] = True
        return "should-not-be-used", {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(qa_router.llm_client, "complete_chat", _unexpected_llm_call)
    monkeypatch.setattr(qa_router.llm_client.config, "endpoint", "https://example.invalid")
    monkeypatch.setattr(qa_router.llm_client.config, "api_key", "token")
    monkeypatch.setattr(qa_router.llm_client.config, "deployment", "gpt-test")

    response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": "proj-no-fallback",
            "question": {
                "id": "q-no-silent-fallback",
                "question": "Under article, what obligations apply?",
                "answer_type": "free_text",
                "route_hint": "article_lookup",
            },
            "runtime_policy": _runtime_policy(return_debug_trace=True),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["route_name"] == "article_lookup"
    assert payload["abstained"] is True
    assert payload["sources"] == []
    assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "law_article_lookup"
    assert payload["debug"]["law_article_lookup_resolution"]["provision_lookup_confidence"] < 0.5
    assert payload["debug"]["retrieval_stage_trace"]["retrieval_skipped_reason"] == "law_article_resolution_missing"
    assert payload["debug"]["no_silent_fallback"]["article_resolution_blocked"] is True
    assert payload["debug"]["abstain_reason"] == "law_article_resolution_missing"
    assert llm_called["value"] is False


def test_article_lookup_number_solver_prefers_stronger_structural_match() -> None:
    question = {
        "question": "Under Article 14(1) of the Employment Law 2019, how many days does an Employer have to provide a written Employment Contract?",
        "answer_type": "number",
    }
    candidates = [
        {
            "paragraph": {"text": "11. No waiver Nothing in this Law precludes ..."},
            "page": {"source_page_id": "employment_10"},
            "chunk_projection": {"text_clean": "11. No waiver Nothing in this Law precludes ..."},
            "score": 2.4,
            "retrieval_debug": {
                "structure_hits": {
                    "article": True,
                    "law_title": False,
                    "law_number": False,
                    "law_year": False,
                    "doc_type": True,
                }
            },
        },
        {
            "paragraph": {"text": "14. Right to a written contract ... within seven (7) days of commencement."},
            "page": {"source_page_id": "employment_5"},
            "chunk_projection": {"text_clean": "14. Right to a written contract ... within seven (7) days of commencement."},
            "score": 2.3,
            "retrieval_debug": {
                "structure_hits": {
                    "article": True,
                    "law_title": True,
                    "law_number": False,
                    "law_year": True,
                    "doc_type": True,
                }
            },
        },
    ]

    result = solve_deterministic(question, "article_lookup", candidates)
    assert result.abstained is False
    assert result.answer == 7


def test_article_lookup_free_text_abstains_when_overlap_is_too_low() -> None:
    question = {
        "question": "What plea bargain is described in the Employment Law 2019?",
        "answer_type": "free_text",
    }
    candidates = [
        {
            "paragraph": {"text": "11. No waiver"},
            "page": {"source_page_id": "employment_10"},
            "chunk_projection": {"text_clean": "11. No waiver"},
            "score": 0.45,
            "exact_identifier_hit": False,
            "retrieval_debug": {"structure_hits": {}},
        }
    ]

    result = solve_deterministic(question, "article_lookup", candidates)
    assert result.abstained is True
    assert result.trace["path"] == "free_text_abstain_low_overlap"


def test_article_lookup_free_text_allows_structural_article_extract_with_low_overlap() -> None:
    question = {
        "question": "What is stated in article 1?",
        "answer_type": "free_text",
    }
    candidates = [
        {
            "paragraph": {"text": "1. Application This Law applies in the DIFC."},
            "page": {"source_page_id": "employment_1"},
            "chunk_projection": {"text_clean": "1. Application This Law applies in the DIFC."},
            "score": 1.2,
            "exact_identifier_hit": False,
            "retrieval_debug": {"structure_hits": {"article": True, "doc_type": True}},
        }
    ]

    result = solve_deterministic(question, "article_lookup", candidates)
    assert result.abstained is False
    assert result.trace["path"] == "free_text_article_structural_extract"


def test_short_free_text_query_uses_top_extract_without_forcing_abstain() -> None:
    question = {
        "question": "sample",
        "answer_type": "free_text",
    }
    candidates = [
        {
            "paragraph": {"text": "Sample clause text"},
            "page": {"source_page_id": "sample_0"},
            "chunk_projection": {"text_clean": "Sample clause text"},
            "score": 0.9,
            "exact_identifier_hit": False,
            "retrieval_debug": {"structure_hits": {}},
        }
    ]

    result = solve_deterministic(question, "default", candidates)
    assert result.abstained is False
    assert result.trace["path"] == "free_text_short_query_extract"


def test_article_lookup_same_year_compare_does_not_collapse_to_single_page() -> None:
    question = {
        "question": "Was the Employment Law enacted in the same year as the Intellectual Property Law?",
        "answer_type": "boolean",
    }
    candidates = [
        {
            "paragraph": {"text": "Employment Law No. 2 of 2019 was enacted on 28 August 2019."},
            "page": {"source_page_id": "employment_1"},
            "chunk_projection": {
                "text_clean": "Employment Law No. 2 of 2019 was enacted on 28 August 2019.",
                "law_year": 2019,
                "dates": ["2019-08-28"],
            },
            "score": 1.5,
            "retrieval_debug": {"structure_hits": {"article": True, "law_title": True, "law_year": True, "doc_type": True}},
        },
        {
            "paragraph": {"text": "Intellectual Property Law No. 4 of 2019 was enacted on 10 September 2019."},
            "page": {"source_page_id": "ip_1"},
            "chunk_projection": {
                "text_clean": "Intellectual Property Law No. 4 of 2019 was enacted on 10 September 2019.",
                "law_year": 2019,
                "dates": ["2019-09-10"],
            },
            "score": 1.4,
            "retrieval_debug": {"structure_hits": {"article": True, "law_title": True, "law_year": True, "doc_type": True}},
        },
    ]

    result = solve_deterministic(question, "article_lookup", candidates)
    assert result.abstained is False
    assert result.answer is True
    assert result.trace["path"] == "boolean_same_year"
