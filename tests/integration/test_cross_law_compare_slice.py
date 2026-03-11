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

from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.state import store  # noqa: E402


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


def _seed_cross_candidate(
    project_id: str,
    *,
    chunk_id: str,
    doc_type: str,
    text: str,
    retrieval_text: str,
    title: str,
    law_number: str | None = None,
    law_year: int | None = None,
    notice_number: str | None = None,
    notice_year: int | None = None,
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
        "title": title,
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
        "law_refs": [title],
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
        "law_title": title,
        "title": title,
        "citation_title": title,
        "law_number": law_number,
        "law_year": law_year,
        "notice_number": notice_number,
        "notice_year": notice_year,
        "entity_names": [],
        "article_refs": [],
        "dates": [],
        "money_values": [],
        "exact_terms": [title, f"law no {law_number} of {law_year}" if law_number and law_year else title],
        "search_keywords": [title],
        "edge_types": [],
    }
    if chunk_overrides:
        chunk_payload.update(chunk_overrides)
    store.chunk_search_documents[chunk_id] = chunk_payload


def _seed_law_pair(project_id: str) -> None:
    _seed_cross_candidate(
        project_id,
        chunk_id="cross_law_1_chunk",
        doc_type="law",
        title="DIFC Law No. 1 of 2018 (General Partnership Law)",
        text="DIFC Law No. 1 of 2018 was enacted on 1 January 2018 and includes Schedule 1.",
        retrieval_text="difc law no 1 of 2018 enacted on 1 january 2018 schedule 1 administering authority difc authority",
        law_number="1",
        law_year=2018,
        paragraph_overrides={"dates": ["1 January 2018"]},
        chunk_overrides={
            "enactment_date": "1 January 2018",
            "administering_authority": "DIFC Authority",
            "schedule_number": "1",
            "dates": ["1 January 2018"],
            "text_clean": (
                "In this Law, partner means a person admitted as partner. "
                "The scope of this Law applies to partnerships established in the DIFC."
            ),
        },
    )
    _seed_cross_candidate(
        project_id,
        chunk_id="cross_law_2_chunk",
        doc_type="law",
        title="DIFC Law No. 2 of 2020 (Operating Law)",
        text="DIFC Law No. 2 of 2020 was enacted on 1 February 2020 and includes Schedule 2.",
        retrieval_text="difc law no 2 of 2020 enacted on 1 february 2020 schedule 2 administering authority difc authority",
        law_number="2",
        law_year=2020,
        paragraph_overrides={"dates": ["1 February 2020"]},
        chunk_overrides={
            "enactment_date": "1 February 2020",
            "administering_authority": "DIFC Authority",
            "schedule_number": "2",
            "dates": ["1 February 2020"],
            "text_clean": (
                "In this Law, operator means a registered person. "
                "The scope of this Law applies to operating licences in the DIFC."
            ),
        },
    )


def test_cross_law_compare_enactment_earlier_later_e2e() -> None:
    state = _snapshot_store_state()
    try:
        project_id = str(uuid4())
        store.feature_flags["canonical_chunk_model_v1"] = True
        _seed_law_pair(project_id)
        client = TestClient(app)

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-earlier",
                    "question": "Was DIFC Law No. 1 of 2018 enacted earlier than DIFC Law No. 2 of 2020?",
                    "answer_type": "boolean",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert response.status_code == 200
        payload = response.json()

        assert payload["route_name"] == "cross_law_compare"
        assert payload["abstained"] is False
        assert payload["answer"] is True
        assert payload["telemetry"]["search_profile"] == "cross_law_compare_matrix_v1"
        assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "cross_law_compare"
        assert payload["debug"]["cross_law_compare_resolution"]["compare_operator"] == "earlier_than"
        assert payload["debug"]["evidence_selection_trace"]["compare_coverage_complete"] is True
        assert payload["debug"]["evidence_selection_trace"]["used_source_page_ids"]
    finally:
        _restore_store_state(state)


def test_cross_law_compare_commencement_notice_mediated_e2e() -> None:
    state = _snapshot_store_state()
    try:
        project_id = str(uuid4())
        store.feature_flags["canonical_chunk_model_v1"] = True
        _seed_law_pair(project_id)
        store.chunk_search_documents["cross_law_1_chunk"]["commencement_date"] = "1 January 2021"
        store.chunk_search_documents["cross_law_2_chunk"]["commencement_date"] = "1 January 2021"
        store.chunk_search_documents["cross_law_1_chunk"]["dates"] = ["1 January 2021"]
        store.chunk_search_documents["cross_law_2_chunk"]["dates"] = ["1 January 2021"]
        store.paragraphs["cross_law_1_chunk"]["dates"] = ["1 January 2021"]
        store.paragraphs["cross_law_2_chunk"]["dates"] = ["1 January 2021"]
        _seed_cross_candidate(
            project_id,
            chunk_id="cross_notice_1_chunk",
            doc_type="enactment_notice",
            title="Commencement Notice No. 11 of 2019",
            text="Commencement Notice No. 11 of 2019 states DIFC Law No. 1 of 2018 came into force on 1 January 2021.",
            retrieval_text="commencement notice no 11 of 2019 difc law no 1 of 2018 came into force on 1 january 2021",
            law_number="1",
            law_year=2018,
            notice_number="11",
            notice_year=2019,
            paragraph_overrides={"dates": ["1 January 2021"]},
            chunk_overrides={"commencement_date": "1 January 2021", "dates": ["1 January 2021"]},
        )
        _seed_cross_candidate(
            project_id,
            chunk_id="cross_notice_2_chunk",
            doc_type="enactment_notice",
            title="Commencement Notice No. 12 of 2020",
            text="Commencement Notice No. 12 of 2020 states DIFC Law No. 2 of 2020 came into force on 1 January 2021.",
            retrieval_text="commencement notice no 12 of 2020 difc law no 2 of 2020 came into force on 1 january 2021",
            law_number="2",
            law_year=2020,
            notice_number="12",
            notice_year=2020,
            paragraph_overrides={"dates": ["1 January 2021"]},
            chunk_overrides={"commencement_date": "1 January 2021", "dates": ["1 January 2021"]},
        )
        client = TestClient(app)

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-commencement",
                    "question": "Did DIFC Law No. 1 of 2018 and DIFC Law No. 2 of 2020 come into force on the same date?",
                    "answer_type": "boolean",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert response.status_code == 200
        payload = response.json()

        assert payload["abstained"] is False
        assert payload["answer"] is True
        assert "commencement_date" in payload["debug"]["cross_law_compare_resolution"]["compare_dimensions"]
        assert payload["debug"]["retrieval_stage_trace"]["cross_law_compare_notice_expansion_requested"] is True
        assert any(
            "cross_law_notice_expansion" in item.get("pass", "")
            for item in payload["debug"]["retrieval_stage_trace"]["cross_law_compare_passes"]
        )
        assert payload["debug"]["solver_trace"]["cross_law_compare_dimension_trace"]
    finally:
        _restore_store_state(state)


def test_cross_law_compare_administering_authority_and_schedule_presence_e2e() -> None:
    state = _snapshot_store_state()
    try:
        project_id = str(uuid4())
        store.feature_flags["canonical_chunk_model_v1"] = True
        _seed_law_pair(project_id)
        client = TestClient(app)

        authority_response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-authority",
                    "question": "Do DIFC Law No. 1 of 2018 and DIFC Law No. 2 of 2020 have the same administering authority?",
                    "answer_type": "boolean",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert authority_response.status_code == 200
        authority_payload = authority_response.json()
        assert authority_payload["abstained"] is False
        assert authority_payload["answer"] is True
        assert "administering_authority" in authority_payload["debug"]["cross_law_compare_resolution"]["compare_dimensions"]

        schedule_response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-schedule",
                    "question": "Do both DIFC Law No. 1 of 2018 and DIFC Law No. 2 of 2020 contain a schedule?",
                    "answer_type": "boolean",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert schedule_response.status_code == 200
        schedule_payload = schedule_response.json()
        assert schedule_payload["abstained"] is False
        assert schedule_payload["answer"] is True
        assert "schedule_presence" in schedule_payload["debug"]["cross_law_compare_resolution"]["compare_dimensions"]
    finally:
        _restore_store_state(state)


def test_cross_law_compare_title_and_definition_scope_e2e() -> None:
    state = _snapshot_store_state()
    try:
        project_id = str(uuid4())
        store.feature_flags["canonical_chunk_model_v1"] = True
        _seed_law_pair(project_id)
        client = TestClient(app)

        title_response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-title",
                    "question": "Compare the full titles of DIFC Law No. 1 of 2018 and DIFC Law No. 2 of 2020.",
                    "answer_type": "free_text",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert title_response.status_code == 200
        title_payload = title_response.json()
        assert title_payload["abstained"] is False
        assert "General Partnership Law" in str(title_payload["answer"])
        assert "Operating Law" in str(title_payload["answer"])
        assert "title_full" in title_payload["debug"]["cross_law_compare_resolution"]["compare_dimensions"]

        definition_response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-definition",
                    "question": "Compare the definition and scope wording in DIFC Law No. 1 of 2018 versus DIFC Law No. 2 of 2020.",
                    "answer_type": "free_text",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert definition_response.status_code == 200
        definition_payload = definition_response.json()
        assert definition_payload["abstained"] is False
        assert isinstance(definition_payload["answer"], str)
        assert len(str(definition_payload["answer"])) > 20
        assert "definition_or_scope" in definition_payload["debug"]["cross_law_compare_resolution"]["compare_dimensions"]
    finally:
        _restore_store_state(state)


def test_cross_law_compare_unresolved_structure_abstains() -> None:
    state = _snapshot_store_state()
    try:
        project_id = str(uuid4())
        store.feature_flags["canonical_chunk_model_v1"] = True
        client = TestClient(app)

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "cross-law-unresolved",
                    "question": "Compare these laws.",
                    "answer_type": "free_text",
                    "route_hint": "cross_law_compare",
                },
                "runtime_policy": _runtime_policy(),
            },
        )
        assert response.status_code == 200
        payload = response.json()

        assert payload["abstained"] is True
        assert payload["sources"] == []
        assert payload["debug"]["retrieval_stage_trace"]["retrieval_skipped_reason"] == "cross_law_compare_resolution_missing"
        assert payload["debug"]["no_silent_fallback"]["cross_law_resolution_blocked"] is True
        assert payload["debug"]["abstain_reason"] == "cross_law_compare_resolution_missing"
    finally:
        _restore_store_state(state)
