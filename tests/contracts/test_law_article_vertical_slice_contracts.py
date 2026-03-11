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
from services.runtime.solvers import normalize_answer  # noqa: E402


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
