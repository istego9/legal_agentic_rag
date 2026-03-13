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
from services.runtime.law_history_lookup import (  # noqa: E402
    resolve_law_history_lookup_intent,
    solve_law_history_deterministic,
)
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


def test_law_history_resolution_parses_relation_and_identifiers() -> None:
    intent = resolve_law_history_lookup_intent("Which law was amended by DIFC Law No. 2 of 2022?")
    assert intent["resolver_version"] == "law_history_lookup_resolution_v1"
    assert intent["relation_kind"] == "amended_by"
    assert intent["target_law_number"] == "2"
    assert intent["target_law_year"] == "2022"
    assert intent["requires_structural_resolution"] is False
    assert intent["resolution_confidence"] >= 0.5


def test_law_history_resolution_distinguishes_jurisdiction_vs_governing_law() -> None:
    jurisdiction_intent = resolve_law_history_lookup_intent(
        "Do parties need to opt in to DIFC Courts jurisdiction for disputes?"
    )
    governing_law_intent = resolve_law_history_lookup_intent(
        "Does DIFC law apply by default as the governing law?"
    )

    assert jurisdiction_intent["relation_kind"] == "jurisdiction_opt_in"
    assert jurisdiction_intent["is_jurisdiction_question"] is True
    assert jurisdiction_intent["is_governing_law_question"] is False

    assert governing_law_intent["relation_kind"] == "default_difc_application"
    assert governing_law_intent["is_governing_law_question"] is True


def test_law_history_resolution_classifies_notice_mediated_commencement() -> None:
    intent = resolve_law_history_lookup_intent(
        "What date specified in Commencement Notice No. 3 of 2020 brought the law into force?"
    )

    assert intent["relation_kind"] == "notice_mediated_commencement"
    assert intent["is_notice_mediated"] is True
    assert intent["target_notice_number"] == "3"
    assert intent["target_notice_year"] == "2020"


def test_law_history_answer_normalization_typed_first_for_date() -> None:
    question = {
        "question": "On what date was the Employment Law Amendment Law enacted?",
        "answer_type": "date",
    }
    candidates = [
        {
            "paragraph": {
                "paragraph_id": "hist-date-para",
                "text": "The Employment Law Amendment Law was enacted on 7 March 2024.",
                "dates": ["7 March 2024"],
            },
            "chunk_projection": {
                "doc_type": "enactment_notice",
                "enactment_date": "7 March 2024",
                "text_clean": "The Employment Law Amendment Law was enacted on 7 March 2024.",
            },
            "score": 0.9,
        }
    ]

    result = solve_law_history_deterministic(question, "history_lineage", candidates)
    normalized_answer, normalized_text = normalize_answer(result.answer, "date")
    assert result.abstained is False
    assert normalized_answer == "2024-03-07"
    assert normalized_text == "2024-03-07"


def test_history_page_level_source_formatting_is_preserved_in_query_response() -> None:
    page_ref = qa_router._to_page_ref(
        {
            "paragraph": {
                "paragraph_id": "hist-para-1",
                "page_id": "hist-page-1",
                "document_id": "hist-doc-1",
                "text": "The law was repealed by Law No. 4 of 2021.",
                "article_refs": [],
            },
            "page": {
                "page_id": "hist-page-1",
                "source_page_id": "history_4",
            },
            "chunk_projection": {"entity_names": [], "exact_terms": []},
            "score": 0.82,
            "exact_identifier_hit": True,
            "lineage_signal": True,
        },
        "proj-history-1",
        used=True,
        page_index_base=0,
    )
    response = QueryResponse(
        question_id="q-history-page-ref",
        answer="Law No. 4 of 2021",
        answer_normalized="Law No. 4 of 2021",
        answer_type="name",
        confidence=0.9,
        route_name="history_lineage",
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
            route_name="history_lineage",
            search_profile="history_lineage_graph_v1",
            telemetry_complete=True,
            trace_id="trace-history-page-ref",
        ),
        debug=None,
    ).model_dump(mode="json")

    source = response["sources"][0]
    assert source["source_page_id"] == "history_4"
    assert source["pdf_id"] == "history"
    assert source["page_num"] == 4
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


def test_no_silent_fallback_blocks_unresolved_law_history_lookup(monkeypatch) -> None:
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
            "project_id": "proj-history-no-fallback",
            "question": {
                "id": "q-history-no-silent-fallback",
                "question": "When was it repealed?",
                "answer_type": "free_text",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(return_debug_trace=True),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["route_name"] == "history_lineage"
    assert payload["abstained"] is True
    assert payload["sources"] == []
    assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "law_relation_or_history"
    assert payload["debug"]["law_history_lookup_resolution"]["requires_structural_resolution"] is True
    assert payload["debug"]["retrieval_stage_trace"]["retrieval_skipped_reason"] == "law_history_resolution_missing"
    assert payload["debug"]["no_silent_fallback"]["history_resolution_blocked"] is True
    assert payload["debug"]["abstain_reason"] == "law_history_resolution_missing"
    assert llm_called["value"] is False


def test_history_effective_from_solver_scopes_dates_to_new_accounts() -> None:
    question = {
        "question": "Under Article 6 of the Common Reporting Standard Law 2018, what is the effective date for due diligence requirements for New Accounts?",
        "answer_type": "date",
    }
    candidates = [
        {
            "paragraph": {
                "text": "The effective date is 31 December 2016 for Pre-existing Accounts and 1 January 2017 for New Accounts.",
                "dates": ["31 December 2016", "1 January 2017"],
            },
            "chunk_projection": {
                "text_clean": "The effective date is 31 December 2016 for Pre-existing Accounts and 1 January 2017 for New Accounts.",
                "effective_start_date": None,
            },
            "score": 0.91,
        }
    ]
    intent = resolve_law_history_lookup_intent(question["question"])

    result = solve_law_history_deterministic(question, "history_lineage", candidates, history_intent=intent)
    normalized_answer, normalized_text = normalize_answer(result.answer, "date")
    assert result.abstained is False
    assert normalized_answer == "2017-01-01"
    assert normalized_text == "2017-01-01"
