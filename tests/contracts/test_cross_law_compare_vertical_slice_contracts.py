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
from services.runtime.cross_law_compare_lookup import resolve_cross_law_compare_intent  # noqa: E402


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


def test_cross_law_compare_resolution_parses_pair_dimension_operator_and_temporal_focus() -> None:
    intent = resolve_cross_law_compare_intent(
        "Was DIFC Law No. 1 of 2018 enacted earlier than DIFC Law No. 2 of 2020?"
    )

    assert intent["resolver_version"] == "cross_law_compare_resolution_v1"
    assert intent["left_instrument_identifier"] == "law_no_1_of_2018"
    assert intent["right_instrument_identifier"] == "law_no_2_of_2020"
    assert intent["instrument_identifiers"][:2] == ["law_no_1_of_2018", "law_no_2_of_2020"]
    assert "enactment_date" in intent["compare_dimensions"]
    assert intent["compare_operator"] == "earlier_than"
    assert intent["temporal_focus"] == "historical"
    assert intent["structural_resolution_required"] is False
    assert float(intent["resolution_confidence"]) >= 0.5


def test_cross_law_compare_resolution_detects_schedule_and_authority_dimensions() -> None:
    intent = resolve_cross_law_compare_intent(
        "Do both DIFC Law No. 3 of 2019 and DIFC Regulation No. 1 of 2020 contain a schedule and have the same administering authority?"
    )

    assert "schedule_presence" in intent["compare_dimensions"]
    assert "administering_authority" in intent["compare_dimensions"]
    assert intent["compare_operator"] == "same_or_common"
    assert intent["instrument_types"] == ["law", "regulation"]


def test_cross_law_compare_page_level_source_formatting_is_preserved() -> None:
    page_ref = qa_router._to_page_ref(
        {
            "paragraph": {
                "paragraph_id": "cross-para-1",
                "page_id": "cross-page-1",
                "document_id": "cross-doc-1",
                "text": "DIFC Law No. 1 of 2018 commenced on 1 January 2019.",
                "article_refs": [],
            },
            "page": {
                "page_id": "cross-page-1",
                "source_page_id": "crosslaw_5",
            },
            "chunk_projection": {"entity_names": [], "exact_terms": []},
            "score": 0.88,
            "exact_identifier_hit": True,
            "lineage_signal": True,
            "compare_instrument_identifier": "law_no_1_of_2018",
        },
        "proj-cross-1",
        used=True,
        page_index_base=0,
    )
    response = QueryResponse(
        question_id="q-cross-page-ref",
        answer=True,
        answer_normalized="true",
        answer_type="boolean",
        confidence=0.9,
        route_name="cross_law_compare",
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
            route_name="cross_law_compare",
            search_profile="cross_law_compare_matrix_v1",
            telemetry_complete=True,
            trace_id="trace-cross-page-ref",
        ),
        debug=None,
    ).model_dump(mode="json")

    source = response["sources"][0]
    assert source["source_page_id"] == "crosslaw_5"
    assert source["pdf_id"] == "crosslaw"
    assert source["page_num"] == 5
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


def test_cross_law_compare_no_silent_fallback_when_resolution_missing(monkeypatch) -> None:
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
            "project_id": "proj-cross-no-fallback",
            "question": {
                "id": "q-cross-no-silent-fallback",
                "question": "Compare these laws.",
                "answer_type": "free_text",
                "route_hint": "cross_law_compare",
            },
            "runtime_policy": _runtime_policy(return_debug_trace=True),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["abstained"] is True
    assert payload["sources"] == []
    assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "cross_law_compare"
    assert payload["debug"]["retrieval_stage_trace"]["retrieval_skipped_reason"] == "cross_law_compare_resolution_missing"
    assert payload["debug"]["no_silent_fallback"]["cross_law_resolution_blocked"] is True
    assert payload["debug"]["abstain_reason"] == "cross_law_compare_resolution_missing"
    assert llm_called["value"] is False


def test_cross_law_compare_abstains_cleanly_when_resolved_but_evidence_missing() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": "proj-cross-no-evidence",
            "question": {
                "id": "q-cross-no-evidence",
                "question": "Was DIFC Law No. 1 of 2018 enacted earlier than DIFC Law No. 2 of 2020?",
                "answer_type": "boolean",
                "route_hint": "cross_law_compare",
            },
            "runtime_policy": _runtime_policy(return_debug_trace=True),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["abstained"] is True
    assert payload["sources"] == []
    assert payload["debug"]["no_silent_fallback"]["cross_law_resolution_blocked"] is False
    assert payload["debug"]["abstain_reason"] == "no_corpus_support"
