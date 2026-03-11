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


def _seed_candidate(
    project_id: str,
    *,
    chunk_id: str,
    text: str,
    article_number: str,
    answer_type: str,
    answer_value: str,
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
        "doc_type": "law",
        "title": "Operating Law",
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
    paragraph = {
        "paragraph_id": chunk_id,
        "page_id": page_id,
        "document_id": document_id,
        "project_id": project_id,
        "paragraph_index": 0,
        "heading_path": ["law"],
        "text": text,
        "paragraph_class": "article_clause",
        "entities": [answer_value] if answer_type in {"name", "names"} else [],
        "article_refs": [article_number],
        "law_refs": ["Operating Law"],
        "case_refs": [],
        "dates": [answer_value] if answer_type == "date" else [],
        "money_mentions": [answer_value] if answer_type == "number" else [],
    }
    store.paragraphs[chunk_id] = paragraph
    store.chunk_search_documents[chunk_id] = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "pdf_id": pdf_id,
        "page_id": page_id,
        "page_number": 0,
        "doc_type": "law",
        "text_clean": text,
        "retrieval_text": f"operating law article {article_number} {text}",
        "article_number": article_number,
        "article_refs": [article_number],
        "section_ref": article_number,
        "law_title": "Operating Law",
        "law_number": "7",
        "law_year": 2018,
        "entity_names": [answer_value] if answer_type in {"name", "names"} else [],
        "dates": [answer_value] if answer_type == "date" else [],
        "money_values": [answer_value] if answer_type == "number" else [],
        "exact_terms": [f"article {article_number}", "operating law"],
        "search_keywords": ["operating law", f"article {article_number}"],
        "edge_types": [],
    }


def test_law_article_lookup_strict_contracts_and_telemetry_are_complete() -> None:
    state = _snapshot_store_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        project_id = str(uuid4())
        client = TestClient(app)

        seed_rows = [
            {
                "question_id": "strict-boolean",
                "question": "According to Article 8(1) of the Operating Law 2018, is operating without registration permitted?",
                "answer_type": "boolean",
                "chunk_id": "strict_boolean_chunk",
                "text": "No person may operate or conduct business in the DIFC without registration.",
                "article_number": "8",
                "answer_value": "No",
            },
            {
                "question_id": "strict-number",
                "question": "According to Article 10(3) of the Operating Law 2018, how many days does a Registered Person have to change its name?",
                "answer_type": "number",
                "chunk_id": "strict_number_chunk",
                "text": "A Registered Person has 30 days to change its name.",
                "article_number": "10",
                "answer_value": "30",
            },
            {
                "question_id": "strict-free-text",
                "question": "According to Article 16(1) of the Operating Law 2018, what document must be filed for licence renewal?",
                "answer_type": "free_text",
                "chunk_id": "strict_free_text_chunk",
                "text": "Every Registered Person must file an annual return at the same time as licence renewal.",
                "article_number": "16",
                "answer_value": "annual return",
            },
        ]

        responses: list[QueryResponse] = []
        for row in seed_rows:
            _seed_candidate(
                project_id,
                chunk_id=row["chunk_id"],
                text=row["text"],
                article_number=row["article_number"],
                answer_type=row["answer_type"],
                answer_value=row["answer_value"],
            )
            result = client.post(
                "/v1/qa/ask",
                json={
                    "project_id": project_id,
                    "question": {
                        "id": row["question_id"],
                        "question": row["question"],
                        "answer_type": row["answer_type"],
                        "route_hint": "article_lookup",
                    },
                    "runtime_policy": _runtime_policy(),
                },
            )
            assert result.status_code == 200
            payload = result.json()
            responses.append(QueryResponse.model_validate(payload))

            assert payload["abstained"] is False
            assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "law_article_lookup"
            assert payload["debug"]["retrieval_profile_id"] == "article_lookup_recall_v2"
            assert payload["debug"]["telemetry_shadow"]["gen_ai"]["profile_id"] == "article_lookup_recall_v2"
            assert payload["debug"]["evidence_selection_trace"]["used_source_page_ids"]

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
