from __future__ import annotations

import copy
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import QueryResponse  # noqa: E402
from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from packages.scorers.contracts import (  # noqa: E402
    evaluate_query_response_contract,
    source_page_id_issues,
    submission_contract_preflight,
)


def _snapshot_store_state() -> dict:
    return copy.deepcopy(store.__dict__)


def _restore_store_state(state: dict) -> None:
    for key, value in state.items():
        setattr(store, key, value)


def _runtime_policy() -> dict:
    return {
        "use_llm": False,
        "max_candidate_pages": 8,
        "max_context_paragraphs": 8,
        "page_index_base_export": 0,
        "scoring_policy_version": "contest_v2026_public_rules_strict",
        "allow_dense_fallback": False,
        "return_debug_trace": True,
    }


def _seed_history_candidate(
    project_id: str,
    *,
    chunk_id: str,
    text: str,
    retrieval_text: str,
    doc_type: str,
    paragraph_overrides: dict | None = None,
    chunk_overrides: dict | None = None,
) -> None:
    page_id = f"{chunk_id}-page"
    document_id = f"{chunk_id}-doc"
    pdf_id = chunk_id.replace("_chunk", "")
    source_page_id = f"{pdf_id}_0"

    store.documents[document_id] = {
        "document_id": document_id,
        "project_id": project_id,
        "pdf_id": pdf_id,
        "canonical_doc_id": f"{pdf_id}-v1",
        "content_hash": "a" * 64,
        "doc_type": doc_type,
        "title": "History Strict Law",
        "page_count": 1,
        "status": "parsed",
    }
    store.pages[page_id] = {
        "page_id": page_id,
        "document_id": document_id,
        "project_id": project_id,
        "source_page_id": source_page_id,
        "page_num": 0,
        "text": text,
    }
    paragraph_payload = {
        "paragraph_id": chunk_id,
        "page_id": page_id,
        "document_id": document_id,
        "project_id": project_id,
        "paragraph_index": 0,
        "heading_path": [doc_type],
        "text": text,
        "paragraph_class": "body",
        "entities": [],
        "article_refs": [],
        "law_refs": [],
        "case_refs": [],
        "dates": [],
        "money_mentions": [],
    }
    if paragraph_overrides:
        paragraph_payload.update(paragraph_overrides)
    store.paragraphs[chunk_id] = paragraph_payload

    chunk_payload = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "pdf_id": pdf_id,
        "page_id": page_id,
        "page_number": 0,
        "doc_type": doc_type,
        "text_clean": text,
        "retrieval_text": retrieval_text,
        "entity_names": [],
        "article_refs": [],
        "dates": [],
        "money_values": [],
        "exact_terms": [],
        "search_keywords": [],
        "edge_types": [],
    }
    if chunk_overrides:
        chunk_payload.update(chunk_overrides)
    store.chunk_search_documents[chunk_id] = chunk_payload


def test_law_history_lookup_strict_contracts_telemetry_and_no_answer_behavior() -> None:
    state = _snapshot_store_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        project_id = str(uuid4())
        client = TestClient(app)

        _seed_history_candidate(
            project_id,
            chunk_id="strict_history_date_chunk",
            doc_type="enactment_notice",
            text="The Employment Law Amendment Law was enacted on 7 March 2024.",
            retrieval_text="employment law amendment law enacted on 7 march 2024",
            paragraph_overrides={"dates": ["7 March 2024"]},
            chunk_overrides={"enactment_date": "7 March 2024", "dates": ["7 March 2024"], "notice_number": "2"},
        )

        answered = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "strict-history-date",
                    "question": "On what date was the Employment Law Amendment Law enacted?",
                    "answer_type": "date",
                    "route_hint": "history_lineage",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert answered.status_code == 200
        answered_payload = answered.json()
        assert answered_payload["abstained"] is False
        assert answered_payload["answer"] == "2024-03-07"
        assert answered_payload["debug"]["retrieval_profile_id"] == "history_lineage_graph_v1"
        assert answered_payload["debug"]["telemetry_shadow"]["gen_ai"]["profile_id"] == "history_lineage_graph_v1"
        assert answered_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == "enacted_on"
        assert answered_payload["debug"]["evidence_selection_trace"]["used_source_page_ids"]

        abstained = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "strict-history-abstain",
                    "question": "When was it repealed?",
                    "answer_type": "free_text",
                    "route_hint": "history_lineage",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert abstained.status_code == 200
        abstained_payload = abstained.json()
        assert abstained_payload["abstained"] is True
        assert abstained_payload["sources"] == []
        assert abstained_payload["debug"]["abstain_reason"] == "law_history_resolution_missing"
        assert abstained_payload["debug"]["no_silent_fallback"]["history_resolution_blocked"] is True
        assert abstained_payload["debug"]["evidence_selection_trace"]["used_source_page_ids"] == []

        responses = [
            QueryResponse.model_validate(answered_payload),
            QueryResponse.model_validate(abstained_payload),
        ]
        for response in responses:
            contract = evaluate_query_response_contract(
                answer=response.answer,
                answer_type=response.answer_type,
                abstained=response.abstained,
                confidence=float(response.confidence),
                sources=response.sources,
                telemetry=response.telemetry,
            )
            assert contract["competition_contract_valid"] is True
            assert contract["blocking_failures"] == []
            assert contract["answer_schema_valid"] is True
            assert contract["source_page_id_valid"] is True
            assert contract["telemetry_contract_valid"] is True
            assert source_page_id_issues(response.sources) == []

        preflight = submission_contract_preflight(
            responses,
            strict_contract_mode=True,
        )
        assert preflight["strict_contract_mode"] is True
        assert preflight["blocking_failed"] is False
        assert preflight["invalid_prediction_count"] == 0
        assert preflight["competition_contract_pass_rate"] == 1.0
        assert preflight["blocking_contract_failure_histogram"] == {}
    finally:
        _restore_store_state(state)

