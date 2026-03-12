from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.main import app  # noqa: E402
from legal_rag_api import corpus_pg  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.routers import qa as qa_router  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from services.runtime.router import resolve_retrieval_profile  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_store_state():
    snapshot = {
        "documents": copy.deepcopy(store.documents),
        "pages": copy.deepcopy(store.pages),
        "paragraphs": copy.deepcopy(store.paragraphs),
        "chunk_search_documents": copy.deepcopy(store.chunk_search_documents),
        "relation_edges": copy.deepcopy(store.relation_edges),
        "ontology_registry_entries": copy.deepcopy(store.ontology_registry_entries),
        "chunk_ontology_assertions": copy.deepcopy(store.chunk_ontology_assertions),
        "document_ontology_views": copy.deepcopy(store.document_ontology_views),
        "corpus_enrichment_jobs": copy.deepcopy(store.corpus_enrichment_jobs),
    }
    try:
        yield
    finally:
        store.documents = snapshot["documents"]
        store.pages = snapshot["pages"]
        store.paragraphs = snapshot["paragraphs"]
        store.chunk_search_documents = snapshot["chunk_search_documents"]
        store.relation_edges = snapshot["relation_edges"]
        store.ontology_registry_entries = snapshot["ontology_registry_entries"]
        store.chunk_ontology_assertions = snapshot["chunk_ontology_assertions"]
        store.document_ontology_views = snapshot["document_ontology_views"]
        store.corpus_enrichment_jobs = snapshot["corpus_enrichment_jobs"]


def test_current_corpus_snapshot_reads_pg_projection_and_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    store.chunk_search_documents["store-only"] = {"chunk_id": "store-only", "document_id": "doc-store"}
    store.relation_edges["store-edge"] = {"edge_id": "store-edge"}

    monkeypatch.setattr(corpus_router.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_documents",
        lambda project_id=None, include_processing=False: [{"document_id": "doc-1", "project_id": "proj-1"}],
    )
    monkeypatch.setattr(corpus_router.corpus_pg, "list_pages", lambda project_id=None: [{"page_id": "page-1", "project_id": "proj-1"}])
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_paragraphs",
        lambda project_id=None: [{"paragraph_id": "para-1", "project_id": "proj-1", "document_id": "doc-1"}],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_chunk_search_documents",
        lambda project_id=None: [{"chunk_id": "para-1", "document_id": "doc-1", "search_keywords": ["pg-only"]}],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_relation_edges",
        lambda project_id=None: [{"edge_id": "edge-1", "source_object_id": "para-1"}],
    )
    monkeypatch.setattr(corpus_router.corpus_pg, "list_ontology_registry_entries", lambda: [{"entry_id": "entry-1"}])

    snapshot = corpus_router._current_corpus_snapshot("proj-1")

    assert snapshot["chunk_search_documents"] == [{"chunk_id": "para-1", "document_id": "doc-1", "search_keywords": ["pg-only"]}]
    assert snapshot["relation_edges"] == [{"edge_id": "edge-1", "source_object_id": "para-1"}]


def test_pg_candidate_building_uses_pg_search_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    store.chunk_search_documents["store-para"] = {
        "chunk_id": "store-para",
        "document_id": "store-doc",
        "retrieval_text": "store result should not be used",
    }

    pg_candidates = [
        {
            "paragraph": {
                "paragraph_id": "pg-para",
                "page_id": "pg-page",
                "document_id": "pg-doc",
                "project_id": "proj-1",
                "text": "PG projection result",
            },
            "page": {
                "page_id": "pg-page",
                "project_id": "proj-1",
                "source_page_id": "pg_0",
            },
            "chunk_projection": {
                "chunk_id": "pg-para",
                "document_id": "pg-doc",
                "retrieval_text": "pg projection result",
            },
            "score": 0.93,
        }
    ]

    monkeypatch.setattr(qa_router.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(
        qa_router.corpus_pg,
        "search_candidates",
        lambda project_id, query, top_k: pg_candidates,
    )

    candidates, stage_trace = qa_router._build_candidates(
        "projection query",
        "proj-1",
        5,
        route_name="article_lookup",
        answer_type="free_text",
        retrieval_profile=resolve_retrieval_profile("article_lookup", 5),
    )

    assert candidates[0]["paragraph"]["paragraph_id"] == "pg-para"
    assert candidates[0]["score"] == 0.93
    assert candidates[0]["retrieval_debug"]["stage"] == "lexical_projected"
    assert stage_trace["trace_version"] == "retrieval_stage_trace_v1"


def test_pg_search_endpoint_uses_pg_projection_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_search(project_id: str, query: str, top_k: int, filters: dict | None = None) -> list[dict]:
        captured["project_id"] = project_id
        captured["query"] = query
        captured["top_k"] = top_k
        captured["filters"] = filters
        return [
            {
                "paragraph_id": "para-1",
                "page_id": "page-1",
                "score": 0.88,
                "snippet": "Employer shall provide a contract",
                "source_page_id": "law_0",
                "pdf_id": "law",
                "page_num": 0,
                "document_id": "doc-1",
                "chunk_projection": {
                    "chunk_id": "para-1",
                    "document_id": "doc-1",
                    "edge_types": ["refers_to"],
                    "doc_type": "law",
                },
            }
        ]

    monkeypatch.setattr(corpus_router.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(corpus_router.corpus_pg, "search", fake_search)

    client = TestClient(app)
    response = client.post(
        "/v1/corpus/search",
        json={
            "project_id": "proj-1",
            "query": "employer contract",
            "search_profile": "default",
            "top_k": 5,
            "filters": {"doc_type": "law", "edge_type": "refers_to"},
        },
    )

    assert response.status_code == 200
    assert captured["project_id"] == "proj-1"
    assert captured["filters"] == {"doc_type": "law", "edge_type": "refers_to"}
    assert response.json()["items"][0]["chunk_projection"]["chunk_id"] == "para-1"


def test_pg_retry_route_persists_merged_projection_state(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted: dict[str, object] = {}

    monkeypatch.setattr(corpus_router.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_enrichment_jobs",
        lambda project_id=None, limit=20: [
            {
                "job_id": "job-1",
                "project_id": "proj-1",
                "import_job_id": "import-1",
                "status": "completed",
            }
        ],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_documents",
        lambda project_id=None, include_processing=False: [{"document_id": "doc-1", "project_id": "proj-1", "processing": {}}],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_pages",
        lambda project_id=None: [{"page_id": "page-1", "project_id": "proj-1", "document_id": "doc-1", "source_page_id": "law_0"}],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_paragraphs",
        lambda project_id=None: [
            {
                "paragraph_id": "para-1",
                "page_id": "page-1",
                "document_id": "doc-1",
                "project_id": "proj-1",
                "paragraph_index": 0,
                "text": "Employer shall provide a contract.",
                "paragraph_class": "article_clause",
            }
        ],
    )
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "list_chunk_search_documents",
        lambda project_id=None: [
            {
                "chunk_id": "para-1",
                "document_id": "doc-1",
                "page_id": "page-1",
                "retrieval_text": "employer contract",
                "text_clean": "Employer shall provide a contract.",
                "search_keywords": [],
                "edge_types": [],
            }
        ],
    )
    monkeypatch.setattr(corpus_router.corpus_pg, "list_relation_edges", lambda project_id=None: [])
    monkeypatch.setattr(corpus_router.corpus_pg, "list_ontology_registry_entries", lambda: [])
    monkeypatch.setattr(
        corpus_router,
        "retry_agentic_corpus_enrichment",
        lambda **kwargs: {
            "job": {"job_id": "job-2", "project_id": "proj-1", "import_job_id": "import-1", "status": "completed"},
            "registry_entries": [],
            "chunk_assertions": [],
            "document_views": [],
            "updated_documents": {
                "doc-1": {"document_id": "doc-1", "project_id": "proj-1", "processing": {"agentic_enrichment": {"status": "completed"}}}
            },
            "updated_paragraphs": {
                "para-1": {
                    "paragraph_id": "para-1",
                    "page_id": "page-1",
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "paragraph_index": 0,
                    "text": "Employer shall provide a contract.",
                    "paragraph_class": "article_clause",
                }
            },
            "updated_chunk_projections": {
                "para-1": {
                    "chunk_id": "para-1",
                    "document_id": "doc-1",
                    "page_id": "page-1",
                    "retrieval_text": "employer contract active",
                    "text_clean": "Employer shall provide a contract.",
                    "search_keywords": ["requires"],
                    "edge_types": ["refers_to"],
                }
            },
            "projected_relation_edges": [
                {
                    "edge_id": "edge-1",
                    "source_object_type": "chunk",
                    "source_object_id": "para-1",
                    "target_object_type": "document",
                    "target_object_id": "Law No. 10",
                    "edge_type": "refers_to",
                }
            ],
        },
    )
    monkeypatch.setattr(corpus_router, "_persist_enrichment_artifacts", lambda enrichment: None)
    monkeypatch.setattr(
        corpus_router.corpus_pg,
        "persist_ingest_result",
        lambda result: persisted.setdefault("result", copy.deepcopy(result)),
    )

    client = TestClient(app)
    response = client.post(
        "/v1/corpus/enrichment-jobs/job-1/retry",
        json={"target_type": "chunk", "target_ids": ["para-1"]},
    )

    assert response.status_code == 200
    merged = persisted["result"]
    assert isinstance(merged, dict)
    merged_dict = merged
    assert merged_dict["chunk_search_documents"][0]["search_keywords"] == ["requires"]
    assert merged_dict["relation_edges"][0]["edge_id"] == "edge-1"


def test_pg_persist_ingest_result_paragraph_insert_matches_placeholder_count(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[tuple[str, tuple[object, ...] | None]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query: str, params=None):
            executed.append((query, tuple(params) if params is not None else None))
            if "INSERT INTO corpus_paragraphs" in query:
                assert query.count("%s") == len(params)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self, row_factory=None):
            return FakeCursor()

    monkeypatch.setattr(corpus_pg, "ensure_schema", lambda: None)
    monkeypatch.setattr(corpus_pg, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(corpus_pg, "Json", lambda payload: payload)

    corpus_pg.persist_ingest_result(
        {
            "documents": [
                {
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "pdf_id": "law",
                    "canonical_doc_id": "law-v1",
                    "content_hash": "a" * 64,
                    "doc_type": "law",
                    "page_count": 1,
                    "status": "parsed",
                    "processing": {},
                }
            ],
            "pages": [
                {
                    "page_id": "page-1",
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "pdf_id": "law",
                    "source_page_id": "law_0",
                    "page_num": 0,
                    "text": "Article 1",
                    "page_class": "body",
                    "entities": [],
                    "created_at": "2026-03-09T00:00:00Z",
                }
            ],
            "paragraphs": [
                {
                    "paragraph_id": "para-1",
                    "page_id": "page-1",
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "paragraph_index": 0,
                    "heading_path": ["law"],
                    "text": "Article 1",
                    "summary_tag": "law",
                    "paragraph_class": "article_clause",
                    "entities": [],
                    "article_refs": [],
                    "law_refs": [],
                    "case_refs": [],
                    "dates": [],
                    "money_mentions": [],
                    "version_lineage_id": "law-v1",
                    "embedding_vector_id": None,
                    "llm_status": "pending",
                    "llm_summary": None,
                    "llm_section_type": None,
                    "llm_tags": [],
                    "llm_payload": {},
                    "llm_model": None,
                    "llm_error": None,
                    "llm_updated_at": None,
                }
            ],
            "chunk_search_documents": [],
            "relation_edges": [],
        }
    )

    assert any("INSERT INTO corpus_paragraphs" in query for query, _ in executed)


def test_pg_persist_ingest_result_strips_nul_bytes_from_text_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple[object, ...]] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query: str, params=None):
            if "INSERT INTO corpus_pages" in query:
                captured["page"] = tuple(params)
            if "INSERT INTO corpus_documents" in query:
                captured["document"] = tuple(params)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self, row_factory=None):
            return FakeCursor()

    monkeypatch.setattr(corpus_pg, "ensure_schema", lambda: None)
    monkeypatch.setattr(corpus_pg, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(corpus_pg, "Json", lambda payload: payload)

    corpus_pg.persist_ingest_result(
        {
            "documents": [
                {
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "pdf_id": "law",
                    "canonical_doc_id": "law-v1",
                    "content_hash": "a" * 64,
                    "doc_type": "law",
                    "title": "Bad\x00Title",
                    "page_count": 1,
                    "status": "parsed",
                    "processing": {"compact_summary": "nul\x00inside"},
                }
            ],
            "pages": [
                {
                    "page_id": "page-1",
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "pdf_id": "law",
                    "source_page_id": "law_0",
                    "page_num": 0,
                    "text": "bad\x00page",
                    "page_class": "body",
                    "entities": ["one\x00entity"],
                    "created_at": "2026-03-09T00:00:00Z",
                }
            ],
            "paragraphs": [],
            "chunk_search_documents": [],
            "relation_edges": [],
        }
    )

    document_params = captured["document"]
    page_params = captured["page"]
    assert "Bad\x00Title" not in document_params
    assert "BadTitle" in document_params
    assert document_params[-1]["compact_summary"] == "nulinside"
    assert "bad\x00page" not in page_params
    assert "badpage" in page_params
    assert page_params[-2] == ["oneentity"]


def test_pg_persist_ingest_result_deletes_stale_relation_edges_for_imported_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[tuple[str, tuple[object, ...] | None]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query: str, params=None):
            executed.append((query, tuple(params) if params is not None else None))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self, row_factory=None):
            return FakeCursor()

    monkeypatch.setattr(corpus_pg, "ensure_schema", lambda: None)
    monkeypatch.setattr(corpus_pg, "_connect", lambda: FakeConnection())
    monkeypatch.setattr(corpus_pg, "Json", lambda payload: payload)

    corpus_pg.persist_ingest_result(
        {
            "documents": [
                {
                    "document_id": "doc-1",
                    "project_id": "proj-1",
                    "pdf_id": "law",
                    "canonical_doc_id": "law-v1",
                    "content_hash": "a" * 64,
                    "doc_type": "law",
                    "page_count": 1,
                    "status": "parsed",
                    "processing": {},
                }
            ],
            "pages": [],
            "paragraphs": [],
            "chunk_search_documents": [],
            "relation_edges": [
                {
                    "edge_id": "edge-1",
                    "source_object_type": "document",
                    "source_object_id": "doc-1",
                    "target_object_type": "document",
                    "target_object_id": "doc-2",
                    "edge_type": "refers_to",
                }
            ],
        }
    )

    delete_queries = [item for item in executed if "DELETE FROM corpus_relation_edges" in item[0]]
    assert len(delete_queries) == 1
    assert delete_queries[0][1] == (["doc-1"],)
