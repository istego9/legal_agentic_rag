from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
SCRIPT_PATH = ROOT / "scripts" / "competition_batch.py"

if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.state import store  # noqa: E402


def _load_module():
    spec = importlib.util.spec_from_file_location("competition_batch_integration", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _seed_article_candidate(
    *,
    project_id: str,
    chunk_id: str,
    pdf_id: str,
    page_num: int,
    text: str,
) -> None:
    page_id = f"{chunk_id}-page"
    document_id = f"{chunk_id}-doc"

    store.documents[document_id] = {
        "document_id": document_id,
        "project_id": project_id,
        "pdf_id": pdf_id,
        "canonical_doc_id": f"{pdf_id}-v1",
        "content_hash": "a" * 64,
        "doc_type": "law",
        "title": "Sample Law",
        "page_count": 3,
        "status": "parsed",
    }
    store.pages[page_id] = {
        "page_id": page_id,
        "document_id": document_id,
        "project_id": project_id,
        "source_page_id": f"{pdf_id}_{page_num}",
        "page_num": page_num,
        "text": text,
    }
    store.paragraphs[chunk_id] = {
        "paragraph_id": chunk_id,
        "page_id": page_id,
        "document_id": document_id,
        "project_id": project_id,
        "paragraph_index": 0,
        "heading_path": ["law"],
        "text": text,
        "paragraph_class": "article_clause",
        "entities": [],
        "article_refs": ["10"],
        "law_refs": ["Sample Law"],
        "case_refs": [],
        "dates": [],
        "money_mentions": [],
    }
    store.chunk_search_documents[chunk_id] = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "pdf_id": pdf_id,
        "page_id": page_id,
        "page_number": page_num,
        "doc_type": "law",
        "text_clean": text,
        "retrieval_text": "sample law article 10 compliance reporting requirement",
        "article_number": "10",
        "article_refs": ["10"],
        "section_ref": "10",
        "law_title": "Sample Law",
        "law_number": "1",
        "law_year": 2020,
        "entity_names": [],
        "dates": [],
        "money_values": [],
        "exact_terms": ["article 10", "sample law"],
        "search_keywords": ["sample law", "article 10"],
        "edge_types": [],
    }


def test_batch_runner_integration_groups_pages_and_handles_abstain(tmp_path: Path) -> None:
    module = _load_module()
    project_id = "integration-batch-project"
    _seed_article_candidate(
        project_id=project_id,
        chunk_id="sample-law-page-0",
        pdf_id="sample-law",
        page_num=0,
        text="Article 10 requires annual compliance report submission.",
    )
    _seed_article_candidate(
        project_id=project_id,
        chunk_id="sample-law-page-2",
        pdf_id="sample-law",
        page_num=2,
        text="Article 10 requires supporting evidence for compliance.",
    )

    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-grouped-pages",
                    "question": "According to Article 10 of Sample Law, what is required?",
                    "answer_type": "free_text",
                    "route_hint": "article_lookup",
                },
                {
                    "id": "q-abstain",
                    "question": "Is there a Mars lunar tax under this corpus?",
                    "answer_type": "free_text",
                    "route_hint": "no_answer",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "competition_run"
    rc = module.main(
        [
            "run",
            "--questions",
            str(questions_path),
            "--output",
            str(output_dir),
            "--project-id",
            project_id,
            "--dataset-id",
            "integration-dataset",
            "--limit",
            "2",
        ]
    )
    assert rc == 0

    submission = json.loads((output_dir / "submission.json").read_text(encoding="utf-8"))
    answers = {row["question_id"]: row for row in submission["answers"]}
    grouped_pages = answers["q-grouped-pages"]["telemetry"]["retrieval"]["retrieved_chunk_pages"]
    assert grouped_pages == [{"doc_id": "sample-law", "page_numbers": [1, 3]}]
    abstain_pages = answers["q-abstain"]["telemetry"]["retrieval"]["retrieved_chunk_pages"]
    assert abstain_pages == []

    status_rows = [
        json.loads(line)
        for line in (output_dir / "question_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["question_id"]: row for row in status_rows}
    assert by_id["q-abstain"]["abstained"] is True
    assert by_id["q-abstain"]["success"] is True

    validate_rc = module.main(
        [
            "validate",
            "--submission",
            str(output_dir / "submission.json"),
            "--report",
            str(output_dir / "submission.validation_report.json"),
        ]
    )
    assert validate_rc == 0
    validation = json.loads((output_dir / "submission.validation_report.json").read_text(encoding="utf-8"))
    assert validation["valid"] is True
