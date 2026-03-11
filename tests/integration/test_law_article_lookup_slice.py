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


def _seed_article_candidate(
    project_id: str,
    *,
    chunk_id: str,
    doc_type: str,
    text: str,
    retrieval_text: str,
    article_number: str,
    law_title: str,
    law_number: str,
    law_year: int,
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
        "title": law_title,
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
        "paragraph_class": "article_clause",
        "entities": [],
        "article_refs": [article_number],
        "law_refs": [law_title],
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
        "article_number": article_number,
        "article_refs": [article_number],
        "section_ref": article_number,
        "law_title": law_title,
        "law_number": law_number,
        "law_year": law_year,
        "entity_names": [],
        "dates": [],
        "money_values": [],
        "exact_terms": [f"article {article_number}", f"law no {law_number} of {law_year}"],
        "search_keywords": [law_title, f"article {article_number}"],
        "edge_types": [],
    }
    if chunk_overrides:
        chunk_payload.update(chunk_overrides)
    store.chunk_search_documents[chunk_id] = chunk_payload


@pytest.mark.parametrize(
    (
        "question_id",
        "question_text",
        "answer_type",
        "seed_kwargs",
        "expected_answer",
        "expected_answer_normalized",
    ),
    [
        (
            "q-law-boolean",
            "Under Article 17(b) of the General Partnership Law 2004, can a person become a Partner without the consent of all existing Partners?",
            "boolean",
            {
                "chunk_id": "gp_boolean_chunk",
                "doc_type": "law",
                "text": "A person cannot become a Partner without consent of all existing Partners unless otherwise agreed.",
                "retrieval_text": "general partnership law article 17 consent partner",
                "article_number": "17",
                "law_title": "General Partnership Law",
                "law_number": "3",
                "law_year": 2004,
            },
            False,
            "false",
        ),
        (
            "q-law-number",
            "According to Article 19(4) of the General Partnership Law 2004, how many months after the financial year must the accounts be prepared and approved?",
            "number",
            {
                "chunk_id": "gp_number_chunk",
                "doc_type": "law",
                "text": "Accounts must be prepared and approved within 6 months after the end of the financial year.",
                "retrieval_text": "general partnership law article 19 accounts 6 months",
                "article_number": "19",
                "law_title": "General Partnership Law",
                "law_number": "3",
                "law_year": 2004,
            },
            6,
            "6",
        ),
        (
            "q-law-date",
            "According to Article 9 of the Operating Law 2018, what is the commencement date of the licence term?",
            "date",
            {
                "chunk_id": "operating_date_chunk",
                "doc_type": "law",
                "text": "The licence term commences on 7 March 2024.",
                "retrieval_text": "operating law article 9 commencement date 7 March 2024",
                "article_number": "9",
                "law_title": "Operating Law",
                "law_number": "7",
                "law_year": 2018,
                "paragraph_overrides": {"dates": ["7 March 2024"]},
                "chunk_overrides": {"dates": ["7 March 2024"], "commencement_date": "7 March 2024"},
            },
            "2024-03-07",
            "2024-03-07",
        ),
        (
            "q-law-name",
            "Under Article 12 of the Real Property Law 2018, what is the term for the office created as a corporation sole?",
            "name",
            {
                "chunk_id": "real_property_name_chunk",
                "doc_type": "law",
                "text": "Article 12 states that the office is the Registrar of Real Property.",
                "retrieval_text": "real property law article 12 registrar of real property",
                "article_number": "12",
                "law_title": "Real Property Law",
                "law_number": "10",
                "law_year": 2018,
                "paragraph_overrides": {"entities": ["Registrar of Real Property"]},
                "chunk_overrides": {"entity_names": ["Registrar of Real Property"]},
            },
            "Registrar Of Real Property",
            "Registrar Of Real Property",
        ),
        (
            "q-law-free-text",
            "According to Article 17(1) of the Strata Title Law DIFC Law No. 5 of 2007, what type of resolution is required for disposal of common property?",
            "free_text",
            {
                "chunk_id": "strata_free_text_chunk",
                "doc_type": "law",
                "text": "A special resolution of the Body Corporate is required for disposal of Common Property.",
                "retrieval_text": "strata title law article 17 special resolution common property",
                "article_number": "17",
                "law_title": "Strata Title Law",
                "law_number": "5",
                "law_year": 2007,
            },
            "A special resolution of the Body Corporate is required for disposal of Common Property.",
            "A special resolution of the Body Corporate is required for disposal of Common Property.",
        ),
    ],
)
def test_law_article_lookup_vertical_slice_e2e(
    question_id: str,
    question_text: str,
    answer_type: str,
    seed_kwargs: dict,
    expected_answer: object,
    expected_answer_normalized: str,
) -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_article_candidate(project_id, **seed_kwargs)
    client = TestClient(app)

    response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": question_id,
                "question": question_text,
                "answer_type": answer_type,
                "route_hint": "article_lookup",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["route_name"] == "article_lookup"
    assert payload["telemetry"]["search_profile"] == "article_lookup_recall_v2"
    assert payload["debug"]["route_decision"]["normalized_taxonomy_route"] == "law_article_lookup"
    assert payload["debug"]["law_article_lookup_resolution"]["article_identifier"] is not None
    assert payload["debug"]["retrieval_profile_id"] == "article_lookup_recall_v2"
    assert payload["debug"]["retrieval_stage_trace"]["route_name"] == "article_lookup"
    assert payload["debug"]["evidence_selection_trace"]["used_source_page_ids"]
    assert payload["abstained"] is False
    assert payload["answer"] == expected_answer
    assert payload["answer_normalized"] == expected_answer_normalized

    used_sources = [row for row in payload["sources"] if row["used"]]
    assert used_sources
    assert all("_" in row["source_page_id"] for row in used_sources)
    assert payload["debug"]["answer_normalization_trace"]["normalization_applied"] in {True, False}


def test_law_article_lookup_tricky_law_number_year_resolution() -> None:
    project_id = str(uuid4())
    store.feature_flags["canonical_chunk_model_v1"] = True
    _seed_article_candidate(
        project_id,
        chunk_id="strata_tricky_chunk",
        doc_type="law",
        text="Ownership of the Common Property is held by the Body Corporate in trust for Owners.",
        retrieval_text="strata title law article 15 body corporate trust owners",
        article_number="15",
        law_title="Strata Title Law",
        law_number="5",
        law_year=2007,
        paragraph_overrides={"entities": ["Body Corporate"]},
        chunk_overrides={"entity_names": ["Body Corporate"]},
    )
    client = TestClient(app)

    response = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "q-tricky-law-id",
                "question": "Under Article 15(1) of the Strata Title Law DIFC Law No. 5 of 2007, what entity holds ownership of the Common Property in trust for the Owners?",
                "answer_type": "name",
                "route_hint": "article_lookup",
            },
            "runtime_policy": _runtime_policy(),
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["abstained"] is False
    assert payload["answer"] == "Body Corporate"
    assert payload["debug"]["law_article_lookup_resolution"]["law_number"] == "5"
    assert payload["debug"]["law_article_lookup_resolution"]["law_year"] == "2007"
    assert payload["debug"]["law_article_lookup_resolution"]["subarticle_identifier"] == "1"
    assert payload["debug"]["law_article_lookup_resolution"]["provision_lookup_confidence"] >= 0.8
