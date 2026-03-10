from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest.case_judgment_chunk_extractor import extract_case_judgment_chunks  # noqa: E402
from services.ingest.case_judgment_document_extractor import extract_case_judgment_document  # noqa: E402
from services.ingest.case_judgment_pipeline import (  # noqa: E402
    run_case_judgment_extraction_pipeline,
    run_case_judgment_router_pipeline,
)


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "case_judgment_bundle" / "examples"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_fixture_context() -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    fixture_document = _load_json("enf_269_2023_full_judgment_document_example.json")
    fixture_chunks = _load_json("enf_269_2023_selected_chunks_example.json")

    document = {
        "document_id": fixture_document["document_id"],
        "project_id": "proj-case-judgment",
        "pdf_id": fixture_document["competition_pdf_id"],
        "canonical_doc_id": fixture_document.get("canonical_slug"),
        "content_hash": "f" * 64,
        "doc_type": "case",
        "title": fixture_document.get("case_caption"),
        "case_id": fixture_document.get("proceeding_no"),
        "edition_date": fixture_document.get("decision_date"),
        "page_count": int(fixture_document.get("page_count", 1) or 1),
        "status": "parsed",
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
            }
        )

    return document, pages, paragraphs


def test_router_and_extractors_are_bundle_compatible() -> None:
    document, pages, paragraphs = _build_fixture_context()

    routing = run_case_judgment_router_pipeline(document=document, pages=pages, metadata={}, llm_client=None)
    assert routing["document_subtype"] in {"order_with_reasons", "judgment", "short_order", "unknown"}
    assert routing["routing_profile"] in {
        "full_reasons_parser",
        "full_judgment_parser",
        "short_order_parser",
        "unknown",
    }

    document_result = extract_case_judgment_document(
        document=document,
        pages=pages,
        paragraphs=paragraphs,
        routing_state=routing,
        use_llm=False,
    )
    assert document_result.validation_status in {"passed", "warning"}
    assert document_result.payload["doc_type"] == "case"

    chunk_result = extract_case_judgment_chunks(
        document_payload=document_result.payload,
        pages=pages,
        paragraphs=paragraphs,
        use_llm=False,
        max_chunks=80,
    )
    assert chunk_result.validation_status == "passed"
    assert len(chunk_result.chunks) >= 8


def test_case_judgment_pipeline_returns_projection_and_qc() -> None:
    document, pages, paragraphs = _build_fixture_context()
    result = run_case_judgment_extraction_pipeline(
        document=document,
        pages=pages,
        paragraphs=paragraphs,
        use_llm=False,
        max_chunks=60,
    )
    assert "routing" in result
    assert "document_extraction" in result
    assert "chunk_extraction" in result
    assert "qc" in result
    assert "projection" in result

    assert isinstance(result["qc"]["checks"], list)
    assert isinstance(result["projection"]["chunk_search_documents"], list)
    assert len(result["chunk_extraction"]["chunks"]) > 0
