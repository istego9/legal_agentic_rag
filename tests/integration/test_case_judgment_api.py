from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.state import store  # noqa: E402


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "case_judgment_bundle" / "examples"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_fixture_context() -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    fixture_document = _load_json("enf_269_2023_full_judgment_document_example.json")
    fixture_chunks = _load_json("enf_269_2023_selected_chunks_example.json")

    document = {
        "document_id": fixture_document["document_id"],
        "project_id": "proj-case-judgment-int",
        "pdf_id": fixture_document["competition_pdf_id"],
        "canonical_doc_id": fixture_document.get("canonical_slug"),
        "content_hash": "e" * 64,
        "doc_type": "case",
        "title": fixture_document.get("case_caption"),
        "case_id": fixture_document.get("proceeding_no"),
        "edition_date": fixture_document.get("decision_date"),
        "page_count": int(fixture_document.get("page_count", 1) or 1),
        "status": "parsed",
        "processing": {},
    }

    page_texts: Dict[int, List[str]] = {}
    for chunk in fixture_chunks:
        page_number_1 = int(chunk.get("page_number_1", 1) or 1)
        page_texts.setdefault(page_number_1, []).append(str(chunk.get("text_clean", "")))

    pages: List[Dict[str, Any]] = []
    for page_number_1 in sorted(page_texts):
        page_num = page_number_1 - 1
        pages.append(
            {
                "page_id": f"page-{page_number_1}",
                "document_id": document["document_id"],
                "project_id": document["project_id"],
                "pdf_id": document["pdf_id"],
                "source_page_id": f"{document['pdf_id']}_{page_number_1}",
                "page_num": page_num,
                "text": "\n".join(page_texts[page_number_1]),
                "page_class": "body",
                "entities": [],
            }
        )

    page_id_by_num = {int(row["page_num"]): str(row["page_id"]) for row in pages}
    paragraph_index_by_page: Dict[str, int] = {}
    paragraphs: List[Dict[str, Any]] = []
    for chunk in fixture_chunks:
        page_num = int(chunk.get("page_number_0", int(chunk.get("page_number_1", 1)) - 1) or 0)
        page_id = page_id_by_num.get(page_num, f"page-{page_num + 1}")
        paragraph_index = paragraph_index_by_page.get(page_id, 0)
        paragraph_index_by_page[page_id] = paragraph_index + 1
        paragraphs.append(
            {
                "paragraph_id": chunk["chunk_id"],
                "page_id": page_id,
                "document_id": document["document_id"],
                "project_id": document["project_id"],
                "paragraph_index": paragraph_index,
                "heading_path": [],
                "text": chunk.get("text_clean", ""),
                "paragraph_class": chunk.get("chunk_type", "body"),
                "entities": [],
                "article_refs": [],
                "law_refs": [],
                "case_refs": [],
                "dates": [],
                "money_mentions": [],
            }
        )

    return document, pages, paragraphs


@pytest.fixture(autouse=True)
def _restore_store_state() -> None:
    snapshot = copy.deepcopy(store.__dict__)
    try:
        yield
    finally:
        for key, value in snapshot.items():
            setattr(store, key, value)


def _seed_store_context() -> Dict[str, Any]:
    document, pages, paragraphs = _build_fixture_context()
    store.documents[document["document_id"]] = document
    for page in pages:
        store.pages[page["page_id"]] = page
    for paragraph in paragraphs:
        store.paragraphs[paragraph["paragraph_id"]] = paragraph
    return document


def test_case_judgment_endpoints_router_extract_promote_revert() -> None:
    document = _seed_store_context()
    client = TestClient(app)

    router_run_resp = client.post(
        "/v1/corpus/case-judgment/router-runs",
        json={
            "document_id": document["document_id"],
            "source": "integration_test",
        },
    )
    assert router_run_resp.status_code == 202
    routing = router_run_resp.json()["routing"]
    assert routing["routing_profile"] in {
        "full_reasons_parser",
        "full_judgment_parser",
        "short_order_parser",
        "unknown",
    }

    extract_resp_v1 = client.post(
        "/v1/corpus/case-judgment/extraction-runs",
        json={
            "document_id": document["document_id"],
            "use_llm": False,
            "auto_promote": False,
            "source": "integration_test",
        },
    )
    assert extract_resp_v1.status_code == 202
    extraction_payload_v1 = extract_resp_v1.json()
    run_id_v1 = extraction_payload_v1["run"]["run_id"]
    document_extraction_id_v1 = extraction_payload_v1["document_extraction"]["document_extraction_id"]
    assert extraction_payload_v1["chunks_count"] > 0

    promote_v1 = client.post(
        f"/v1/corpus/case-judgment/document-extractions/{document_extraction_id_v1}/promote",
        json={"force": True},
    )
    assert promote_v1.status_code == 200

    run_detail = client.get(f"/v1/corpus/case-judgment/runs/{run_id_v1}")
    assert run_detail.status_code == 200
    assert run_detail.json()["run"]["run_id"] == run_id_v1

    extract_resp_v2 = client.post(
        "/v1/corpus/case-judgment/extraction-runs",
        json={
            "document_id": document["document_id"],
            "use_llm": False,
            "auto_promote": False,
            "source": "integration_test",
        },
    )
    assert extract_resp_v2.status_code == 202
    document_extraction_id_v2 = extract_resp_v2.json()["document_extraction"]["document_extraction_id"]

    promote_v2 = client.post(
        f"/v1/corpus/case-judgment/document-extractions/{document_extraction_id_v2}/promote",
        json={"force": True},
    )
    assert promote_v2.status_code == 200

    revert = client.post(
        f"/v1/corpus/case-judgment/document-extractions/{document_extraction_id_v2}/revert",
        json={"target_document_extraction_id": document_extraction_id_v1},
    )
    assert revert.status_code == 200
    assert revert.json()["active_document_extraction_id"] == document_extraction_id_v1
