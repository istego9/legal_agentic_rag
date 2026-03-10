from __future__ import annotations

import copy
import io
import sys
from pathlib import Path
import zipfile
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import (  # noqa: E402
    DocumentManifest,
    PageRef,
    ParagraphChunk,
    QueryRequest,
    QueryResponse,
    RuntimePolicy,
    SHARED_CONTRACT_REGISTRY,
    SHARED_CONTRACT_REGISTRY_VERSION,
    SubmissionAnswer,
    export_used_source_page_ids,
)
from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from packages.contracts.corpus_scope import SHARED_CORPUS_PROJECT_ID  # noqa: E402


def _snapshot_corpus_state() -> dict:
    return {
        "documents": copy.deepcopy(store.documents),
        "document_bases": copy.deepcopy(store.document_bases),
        "law_documents": copy.deepcopy(store.law_documents),
        "regulation_documents": copy.deepcopy(store.regulation_documents),
        "enactment_notice_documents": copy.deepcopy(store.enactment_notice_documents),
        "case_documents": copy.deepcopy(store.case_documents),
        "pages": copy.deepcopy(store.pages),
        "paragraphs": copy.deepcopy(store.paragraphs),
        "chunk_bases": copy.deepcopy(store.chunk_bases),
        "law_chunk_facets": copy.deepcopy(store.law_chunk_facets),
        "regulation_chunk_facets": copy.deepcopy(store.regulation_chunk_facets),
        "enactment_notice_chunk_facets": copy.deepcopy(store.enactment_notice_chunk_facets),
        "case_chunk_facets": copy.deepcopy(store.case_chunk_facets),
        "relation_edges": copy.deepcopy(store.relation_edges),
        "chunk_search_documents": copy.deepcopy(store.chunk_search_documents),
    }


def _restore_corpus_state(state: dict) -> None:
    store.documents = state["documents"]
    store.document_bases = state["document_bases"]
    store.law_documents = state["law_documents"]
    store.regulation_documents = state["regulation_documents"]
    store.enactment_notice_documents = state["enactment_notice_documents"]
    store.case_documents = state["case_documents"]
    store.pages = state["pages"]
    store.paragraphs = state["paragraphs"]
    store.chunk_bases = state["chunk_bases"]
    store.law_chunk_facets = state["law_chunk_facets"]
    store.regulation_chunk_facets = state["regulation_chunk_facets"]
    store.enactment_notice_chunk_facets = state["enactment_notice_chunk_facets"]
    store.case_chunk_facets = state["case_chunk_facets"]
    store.relation_edges = state["relation_edges"]
    store.chunk_search_documents = state["chunk_search_documents"]


def test_document_manifest_legacy_payload_is_valid() -> None:
    payload = {
        "document_id": "7c81680c-1792-4a84-9f53-12612c908f72",
        "project_id": "b5f8dc17-df66-4af4-8fcf-15f9a18f4dc4",
        "pdf_id": "sample_pdf",
        "canonical_doc_id": "sample_pdf-v1",
        "content_hash": "f" * 64,
        "doc_type": "law",
        "page_count": 1,
        "status": "parsed",
    }
    parsed = DocumentManifest(**payload)
    assert parsed.document_id == payload["document_id"]
    assert parsed.doc_type == "law"


def test_paragraph_chunk_legacy_payload_is_valid() -> None:
    payload = {
        "paragraph_id": "para-1",
        "page_id": "page-1",
        "document_id": "doc-1",
        "paragraph_index": 0,
        "heading_path": ["law"],
        "text": "The employer shall provide written agreement.",
        "paragraph_class": "article_clause",
    }
    parsed = ParagraphChunk(**payload)
    assert parsed.paragraph_id == "para-1"
    assert parsed.text.startswith("The employer")


def test_shared_contract_registry_covers_frozen_boundary_surfaces() -> None:
    registry = SHARED_CONTRACT_REGISTRY
    assert registry.registry_version == SHARED_CONTRACT_REGISTRY_VERSION
    contract_names = [item.contract_name for item in registry.contracts]
    assert contract_names == [
        "PageRef",
        "Telemetry",
        "RuntimePolicy",
        "QueryRequest",
        "QueryResponse",
        "SubmissionAnswer",
    ]
    assert all(item.owner == "control-plane" for item in registry.contracts)
    assert "source_page_id=pdf_id_page" in registry.frozen_invariants
    assert "submission_export_sources_are_page_ids" in registry.frozen_invariants

    by_name = {item.contract_name: item for item in registry.contracts}
    assert by_name["PageRef"].schema_version == "page_ref.v1"
    assert "submission_export" in by_name["PageRef"].consumers
    assert by_name["QueryResponse"].schema_version == "query_response.v1"
    assert "storage" in by_name["QueryResponse"].consumers


def test_core_boundary_contract_shapes_remain_frozen() -> None:
    page_ref_schema = PageRef.model_json_schema()
    assert page_ref_schema["properties"]["source_page_id"]["pattern"] == r"^[A-Za-z0-9._-]+_[0-9]+$"

    runtime_policy_schema = RuntimePolicy.model_json_schema()
    assert "scoring_policy_version" in runtime_policy_schema["required"]
    assert runtime_policy_schema["properties"]["page_index_base_export"]["enum"] == [0, 1]

    query_request_schema = QueryRequest.model_json_schema()
    assert set(query_request_schema["required"]) == {"project_id", "question", "runtime_policy"}

    query_response_schema = QueryResponse.model_json_schema()
    assert "sources" in query_response_schema["required"]
    assert "telemetry" in query_response_schema["required"]

    submission_schema = SubmissionAnswer.model_json_schema()
    assert submission_schema["properties"]["sources"]["items"]["type"] == "string"


def test_submission_export_source_mapping_is_contract_safe() -> None:
    sources = [
        PageRef(
            project_id="p",
            document_id="doc",
            pdf_id="doc",
            page_num=0,
            page_index_base=0,
            source_page_id="doc_0",
            used=True,
            evidence_role="primary",
            score=0.9,
        ),
        PageRef(
            project_id="p",
            document_id="doc",
            pdf_id="doc",
            page_num=0,
            page_index_base=0,
            source_page_id="doc_0",
            used=True,
            evidence_role="primary",
            score=0.8,
        ),
        PageRef(
            project_id="p",
            document_id="doc",
            pdf_id="doc",
            page_num=1,
            page_index_base=0,
            source_page_id="doc_1",
            used=False,
            evidence_role="supporting",
            score=0.7,
        ),
    ]
    assert export_used_source_page_ids(sources) == ["doc_0"]


def test_corpus_search_rejects_invalid_filter_enum() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/corpus/search",
        json={
            "project_id": "b5f8dc17-df66-4af4-8fcf-15f9a18f4dc4",
            "query": "employment",
            "search_profile": "default",
            "top_k": 10,
            "filters": {"doc_type": "invalid_type"},
        },
    )
    assert response.status_code == 422


def test_corpus_search_filters_using_chunk_projection() -> None:
    state = _snapshot_corpus_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        store.documents.clear()
        store.pages.clear()
        store.paragraphs.clear()
        store.chunk_search_documents.clear()

        store.documents["doc-law"] = {
            "document_id": "doc-law",
            "project_id": "p-1",
            "pdf_id": "employment_law",
            "canonical_doc_id": "employment_law-v1",
            "content_hash": "a" * 64,
            "doc_type": "law",
            "page_count": 1,
            "status": "parsed",
        }
        store.pages["page-law-0"] = {
            "page_id": "page-law-0",
            "document_id": "doc-law",
            "project_id": "p-1",
            "source_page_id": "employment_law_0",
            "page_num": 0,
            "text": "Article 14 Employment Contract",
        }
        store.paragraphs["chunk-law-1"] = {
            "paragraph_id": "chunk-law-1",
            "page_id": "page-law-0",
            "document_id": "doc-law",
            "project_id": "p-1",
            "paragraph_index": 0,
            "heading_path": ["law"],
            "text": "Article 14 The employer shall provide a written employment contract.",
            "paragraph_class": "article_clause",
        }
        store.chunk_search_documents["chunk-law-1"] = {
            "chunk_id": "chunk-law-1",
            "document_id": "doc-law",
            "pdf_id": "employment_law",
            "page_id": "page-law-0",
            "page_number": 0,
            "doc_type": "law",
            "title_normalized": "employment law",
            "short_title": "Employment Law",
            "status": "in_force",
            "is_current_version": True,
            "effective_start_date": "2019-08-28",
            "effective_end_date": None,
            "heading_path": ["Part 3", "Article 14"],
            "section_kind": "operative_provision",
            "text_clean": "The employer shall provide a written employment contract.",
            "retrieval_text": "Employment Law article 14 employer written contract",
            "entity_names": ["Employer", "Employee"],
            "article_refs": ["article 14"],
            "dates": [],
            "money_values": [],
            "exact_terms": ["employment contract"],
            "search_keywords": ["employer", "contract"],
            "version_lineage_id": "employment_law-v1",
            "canonical_concept_id": "employment_law:14",
            "historical_relation_type": "original",
            "law_number": "2",
            "law_year": 2019,
            "article_number": "14",
            "section_ref": "14",
            "edge_types": ["refers_to"],
        }

        client = TestClient(app)
        response = client.post(
            "/v1/corpus/search",
            json={
                "project_id": "p-1",
                "query": "written contract",
                "search_profile": "default",
                "top_k": 10,
                "filters": {"doc_type": "law", "law_number": "2", "article_number": "14"},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["paragraph_id"] == "chunk-law-1"
        assert item["source_page_id"] == "employment_law_0"
        assert item["chunk_projection"]["doc_type"] == "law"
        assert item["chunk_projection"]["law_number"] == "2"
    finally:
        _restore_corpus_state(state)


def _make_zip_with_named_pdf(path: Path, *, member_name: str) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, b"%PDF-1.4 minimal fake bytes")
    path.write_bytes(payload.getvalue())


def test_import_extracts_granular_effective_end_date(tmp_path: Path) -> None:
    state = _snapshot_corpus_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        store.documents.clear()
        store.pages.clear()
        store.paragraphs.clear()
        store.chunk_search_documents.clear()

        project_id = str(uuid4())
        zip_path = tmp_path / "one-doc.zip"
        _make_zip_with_named_pdf(
            zip_path,
            member_name="law_effective_from_2019-01-01_until_2020-12-31.pdf",
        )

        client = TestClient(app)
        imported = client.post(
            "/v1/corpus/import-zip",
            json={
                "project_id": project_id,
                "blob_url": str(zip_path),
                "parse_policy": "balanced",
                "dedupe_enabled": True,
            },
        )
        assert imported.status_code == 202

        listed = client.get("/v1/corpus/documents")
        assert listed.status_code == 200
        items = [row for row in listed.json()["items"] if row.get("project_id") == SHARED_CORPUS_PROJECT_ID]
        assert len(items) == 1
        doc = items[0]
        assert doc["effective_start_date"] == "2019-01-01"
        assert doc["effective_end_date"] == "2020-12-31"
        assert doc["is_current_version"] is False

        search = client.post(
            "/v1/corpus/search",
            json={
                "project_id": project_id,
                "query": "placeholder",
                "search_profile": "default",
                "top_k": 10,
                "filters": {"is_current_version": False},
            },
        )
        assert search.status_code == 200
        payload = search.json()
        assert len(payload["items"]) >= 1
        assert payload["items"][0]["chunk_projection"]["effective_end_date"] == "2020-12-31"
        assert payload["items"][0]["chunk_projection"]["is_current_version"] is False
    finally:
        _restore_corpus_state(state)
