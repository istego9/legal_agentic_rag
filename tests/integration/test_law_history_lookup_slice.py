from __future__ import annotations

import copy
from pathlib import Path
import sys
from uuid import uuid4

import pytest
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


@pytest.fixture(autouse=True)
def _isolate_store_state() -> None:
    state = _snapshot_store_state()
    try:
        yield
    finally:
        _restore_store_state(state)


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
    doc_type: str,
    text: str,
    retrieval_text: str,
    paragraph_overrides: dict | None = None,
    chunk_overrides: dict | None = None,
    document_overrides: dict | None = None,
) -> None:
    page_id = f"{chunk_id}-page"
    document_id = f"{chunk_id}-doc"
    pdf_id = chunk_id.replace("_chunk", "")
    source_page_id = f"{pdf_id}_0"

    document_payload = {
        "document_id": document_id,
        "project_id": project_id,
        "pdf_id": pdf_id,
        "canonical_doc_id": f"{pdf_id}-v1",
        "content_hash": "a" * 64,
        "doc_type": doc_type,
        "title": "History Test Law",
        "page_count": 1,
        "status": "parsed",
    }
    if document_overrides:
        document_payload.update(document_overrides)
    store.documents[document_id] = document_payload

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
        "law_title": "History Test Law",
        "law_number": "1",
        "law_year": 2020,
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


def test_law_history_amended_by_and_enactment_date_e2e() -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_history_candidate(
        project_id,
        chunk_id="hist_amended_by_chunk",
        doc_type="law",
        text="DIFC Law No. 3 of 2018 was amended by DIFC Law No. 5 of 2022.",
        retrieval_text="law no 3 of 2018 amended by law no 5 of 2022",
        chunk_overrides={
            "law_title": "DIFC Law No. 3 of 2018",
            "law_number": "3",
            "law_year": 2018,
            "amended_by_doc_ids": ["DIFC Law No. 5 of 2022"],
            "edge_types": ["enabled_by"],
        },
    )
    _seed_history_candidate(
        project_id,
        chunk_id="hist_enacted_on_chunk",
        doc_type="enactment_notice",
        text="The Employment Law Amendment Law was enacted on 7 March 2024.",
        retrieval_text="employment law amendment law enacted on 7 march 2024",
        paragraph_overrides={"dates": ["7 March 2024"]},
        chunk_overrides={"enactment_date": "7 March 2024", "dates": ["7 March 2024"], "notice_number": "2"},
    )
    client = TestClient(app)

    amended_by_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-amended-by",
                "question": "Which law was DIFC Law No. 3 of 2018 amended by?",
                "answer_type": "name",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert amended_by_response.status_code == 200
    amended_by_payload = amended_by_response.json()
    assert amended_by_payload["route_name"] == "history_lineage"
    assert amended_by_payload["answer"] == "DIFC Law No 5 Of 2022"
    assert amended_by_payload["abstained"] is False
    assert amended_by_payload["telemetry"]["search_profile"] == "history_lineage_graph_v1"
    assert amended_by_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == "amended_by"
    assert amended_by_payload["debug"]["solver_trace"]["solver_version"] == "law_history_deterministic_solver_v1"
    assert amended_by_payload["debug"]["evidence_selection_trace"]["used_source_page_ids"]

    enacted_on_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-enacted-date",
                "question": "On what date was the Employment Law Amendment Law enacted?",
                "answer_type": "date",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert enacted_on_response.status_code == 200
    enacted_on_payload = enacted_on_response.json()
    assert enacted_on_payload["answer"] == "2024-03-07"
    assert enacted_on_payload["answer_normalized"] == "2024-03-07"
    assert enacted_on_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == "enacted_on"
    assert enacted_on_payload["debug"]["retrieval_stage_trace"]["profile_id"] == "history_lineage_graph_v1"


def test_law_history_commencement_and_notice_mediated_partial_commencement_e2e() -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_history_candidate(
        project_id,
        chunk_id="hist_commencement_chunk",
        doc_type="enactment_notice",
        text="Commencement Notice No. 3 of 2020 provides that the law came into force on 1 January 2021.",
        retrieval_text="commencement notice no 3 of 2020 came into force on 1 january 2021",
        paragraph_overrides={"dates": ["1 January 2021"]},
        chunk_overrides={
            "notice_number": "3",
            "notice_year": 2020,
            "commencement_date": "1 January 2021",
            "dates": ["1 January 2021"],
            "doc_type": "enactment_notice",
        },
    )
    _seed_history_candidate(
        project_id,
        chunk_id="hist_partial_notice_chunk",
        doc_type="enactment_notice",
        text=(
            "Commencement Notice No. 4 of 2021 brought only Articles 1 to 3 into force; "
            "remaining provisions commenced later by another notice."
        ),
        retrieval_text="commencement notice no 4 of 2021 only articles 1 to 3 into force",
        chunk_overrides={"notice_number": "4", "notice_year": 2021, "commencement_date": "1 February 2021"},
    )
    client = TestClient(app)

    commencement_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-commencement-date",
                "question": "When did this law come into force under Commencement Notice No. 3 of 2020?",
                "answer_type": "date",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert commencement_response.status_code == 200
    commencement_payload = commencement_response.json()
    assert commencement_payload["answer"] == "2021-01-01"
    assert commencement_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] in {
        "commenced_on",
        "notice_mediated_commencement",
    }

    partial_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-partial-commencement",
                "question": "Did Commencement Notice No. 4 of 2021 commence only part of the law?",
                "answer_type": "free_text",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert partial_response.status_code == 200
    partial_payload = partial_response.json()
    assert "only Articles 1 to 3" in str(partial_payload["answer"])
    assert partial_payload["debug"]["law_history_lookup_resolution"]["is_notice_mediated"] is True
    assert partial_payload["debug"]["legal_context_flags"]["is_notice_mediated"] is True


def test_law_history_current_vs_previous_version_retrieval_and_answering() -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_history_candidate(
        project_id,
        chunk_id="hist_prev_version_chunk",
        doc_type="law",
        text="Operating Law previous version sequence is 2 (Law No. 6 of 2019).",
        retrieval_text="operating law previous version sequence 2 law no 6 of 2019",
        chunk_overrides={
            "law_number": "6",
            "law_year": 2019,
            "version_sequence": 2,
            "is_current_version": False,
        },
    )
    _seed_history_candidate(
        project_id,
        chunk_id="hist_current_version_chunk",
        doc_type="law",
        text="Operating Law current version sequence is 3 (Law No. 8 of 2022).",
        retrieval_text="operating law current version sequence 3 law no 8 of 2022 latest",
        chunk_overrides={
            "law_number": "8",
            "law_year": 2022,
            "version_sequence": 3,
            "is_current_version": True,
        },
    )
    client = TestClient(app)

    current_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-current-version",
                "question": "What is the latest DIFC law number for the Operating Law?",
                "answer_type": "number",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert current_response.status_code == 200
    current_payload = current_response.json()
    assert current_payload["answer"] == 8
    assert current_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == "current_version"

    previous_response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "hist-previous-version",
                "question": "What is the previous version sequence number for the Operating Law?",
                "answer_type": "number",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert previous_response.status_code == 200
    previous_payload = previous_response.json()
    assert previous_payload["answer"] == 2
    assert previous_payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == "previous_version"


@pytest.mark.parametrize(
    ("question_text", "expected_relation", "expected_flag"),
    [
        (
            "Does DIFC law apply by default as governing law in the DIFC?",
            "default_difc_application",
            "is_governing_law_question",
        ),
        (
            "Do parties need to opt in to DIFC Courts jurisdiction?",
            "jurisdiction_opt_in",
            "is_jurisdiction_question",
        ),
    ],
)
def test_law_history_difc_default_application_vs_jurisdiction_distinction(
    question_text: str,
    expected_relation: str,
    expected_flag: str,
) -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_history_candidate(
        project_id,
        chunk_id=f"hist_difc_{expected_relation}_chunk",
        doc_type="law",
        text=(
            "DIFC law applies by default as governing law unless parties choose another law. "
            "DIFC Courts jurisdiction applies only where parties opt in by agreement."
        ),
        retrieval_text=(
            "difc law applies by default governing law difc courts jurisdiction only where parties opt in by agreement"
        ),
        chunk_overrides={"edge_types": ["refers_to"]},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": f"hist-difc-{expected_relation}",
                "question": question_text,
                "answer_type": "free_text",
                "route_hint": "history_lineage",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["route_name"] == "history_lineage"
    assert payload["abstained"] is False
    assert payload["debug"]["law_history_lookup_resolution"]["relation_kind"] == expected_relation
    assert payload["debug"]["legal_context_flags"][expected_flag] is True
    assert payload["debug"]["retrieval_profile_id"] == "history_lineage_graph_v1"
