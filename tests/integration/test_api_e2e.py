from __future__ import annotations

import copy
from datetime import datetime, timezone
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse
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
from legal_rag_api.contracts import PageRef, QueryResponse, Telemetry  # noqa: E402
from legal_rag_api.routers import review as review_router  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from services.ingest import ingest as ingest_module  # noqa: E402
from services.runtime.solvers import normalize_answer  # noqa: E402


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


def _make_zip_with_pdf(path: Path) -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sample.pdf", b"%PDF-1.4 fake pdf bytes")
    path.write_bytes(data.getvalue())


def _make_determinism_zip(path: Path) -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("alpha.pdf", b"%PDF-1.4 alpha body bytes")
        zf.writestr("nested/alpha_copy.pdf", b"%PDF-1.4 alpha body bytes")
        zf.writestr("beta.pdf", b"%PDF-1.4 beta body bytes")
    path.write_bytes(data.getvalue())


def _collect_ingest_identity_snapshot(client: TestClient, project_id: str) -> dict:
    listed = client.get("/v1/corpus/documents", params={"project_id": project_id})
    assert listed.status_code == 200
    documents = sorted(listed.json()["items"], key=lambda row: str(row.get("document_id", "")))

    snapshot_docs = []
    for document in documents:
        document_id = str(document["document_id"])
        detail = client.get(f"/v1/corpus/documents/{document_id}/detail")
        assert detail.status_code == 200
        detail_payload = detail.json()
        pages = sorted(
            detail_payload.get("pages", []),
            key=lambda row: (
                int(row.get("page_num", 0) or 0),
                str(row.get("page_id", "")),
            ),
        )
        page_rows = []
        for page in pages:
            chunks = sorted(
                page.get("chunks", []),
                key=lambda row: (
                    int(row.get("paragraph_index", 0) or 0),
                    str(row.get("paragraph_id", "")),
                ),
            )
            page_rows.append(
                {
                    "page_id": str(page.get("page_id", "")),
                    "source_page_id": str(page.get("source_page_id", "")),
                    "page_num": int(page.get("page_num", 0) or 0),
                    "chunk_ids": [str(chunk.get("paragraph_id", "")) for chunk in chunks],
                }
            )

        snapshot_docs.append(
            {
                "document_id": document_id,
                "canonical_doc_id": str(document.get("canonical_doc_id", "")),
                "pdf_id": str(document.get("pdf_id", "")),
                "content_hash": str(document.get("content_hash", "")),
                "duplicate_group_id": document.get("duplicate_group_id"),
                "pages": page_rows,
            }
        )

    processing = client.get("/v1/corpus/processing-results", params={"project_id": project_id, "limit": 200})
    assert processing.status_code == 200
    summary = processing.json().get("summary", {})
    return {
        "summary": {
            "documents": summary.get("documents", 0),
            "pages": summary.get("pages", 0),
            "paragraphs": summary.get("paragraphs", 0),
            "duplicate_documents": summary.get("duplicate_documents", 0),
            "by_doc_type": summary.get("by_doc_type", {}),
        },
        "documents": snapshot_docs,
    }


def _runtime_policy_payload(*, return_debug_trace: bool = False) -> dict:
    return {
        "use_llm": False,
        "max_candidate_pages": 8,
        "max_context_paragraphs": 8,
        "page_index_base_export": 0,
        "scoring_policy_version": "contest_v2026_public_rules_v1",
        "allow_dense_fallback": True,
        "return_debug_trace": return_debug_trace,
    }


def _snapshot_solver_runtime_state() -> dict:
    return {
        "documents": copy.deepcopy(store.documents),
        "pages": copy.deepcopy(store.pages),
        "paragraphs": copy.deepcopy(store.paragraphs),
        "chunk_search_documents": copy.deepcopy(store.chunk_search_documents),
        "feature_flags": copy.deepcopy(store.feature_flags),
    }


def _restore_solver_runtime_state(state: dict) -> None:
    store.documents = state["documents"]
    store.pages = state["pages"]
    store.paragraphs = state["paragraphs"]
    store.chunk_search_documents = state["chunk_search_documents"]
    store.feature_flags = state["feature_flags"]


def _seed_typed_solver_candidate(
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


def test_e2e_flow(tmp_path: Path) -> None:
    project_id = str(uuid4())
    dataset_id = str(uuid4())
    zip_path = tmp_path / "docs.zip"
    _make_zip_with_pdf(zip_path)

    client = TestClient(app)

    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    otel_enabled = str(health.json().get("otel_enabled", "false")).lower() == "true"

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
    assert imported.json()["status"] == "accepted"
    assert imported.json()["processing_profile_version"] == "agentic_corpus_enrichment_v1"
    assert imported.json()["enrichment_job"]["status"] in {"completed", "partial"}

    listed = client.get("/v1/corpus/documents")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    processing = client.get("/v1/corpus/processing-results", params={"project_id": project_id, "limit": 20})
    assert processing.status_code == 200
    assert processing.json()["summary"]["enrichment_jobs"] >= 1
    assert "enrichment_jobs" in processing.json()

    search = client.post(
        "/v1/corpus/search",
        json={
            "project_id": project_id,
            "query": "placeholder",
            "search_profile": "default",
            "top_k": 10,
        },
    )
    assert search.status_code == 200
    assert len(search.json()["items"]) >= 1
    source_page_id = search.json()["items"][0]["source_page_id"]

    ask = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "q-1",
                "question": "What is stated in article 1?",
                "answer_type": "free_text",
                "tags": ["e2e"],
            },
            "runtime_policy": {
                "use_llm": False,
                "max_candidate_pages": 8,
                "max_context_paragraphs": 8,
                "page_index_base_export": 0,
                "scoring_policy_version": "contest_v2026_public_rules_v1",
                "allow_dense_fallback": True,
                "return_debug_trace": True,
            },
        },
    )
    assert ask.status_code == 200
    ask_payload = ask.json()
    assert ask_payload["question_id"] == "q-1"
    assert ask_payload["route_name"] == "article_lookup"
    assert ask_payload["telemetry"]["search_profile"] == "article_lookup_recall_v2"
    assert ask_payload["debug"]["telemetry_shadow"]["gen_ai"]["trace_id"] == ask_payload["telemetry"]["trace_id"]
    if otel_enabled:
        assert re.fullmatch(r"[0-9a-f]{32}", str(ask_payload["telemetry"]["trace_id"]))
        assert ask_payload["telemetry"]["telemetry_complete"] is True
    assert ask_payload["debug"]["retrieval_profile_id"] == "article_lookup_recall_v2"
    assert ask_payload["debug"]["route_recall_diagnostics"]["diagnostics_version"] == "route_recall_diagnostics_v1"
    assert ask_payload["debug"]["route_recall_diagnostics"]["route_name"] == "article_lookup"
    assert ask_payload["debug"]["latency_budget_assertion"]["assertion_version"] == "latency_budget_assertion_v1"
    assert ask_payload["debug"]["latency_budget_assertion"]["retrieval_profile_id"] == "article_lookup_recall_v2"
    assert ask_payload["debug"]["retrieval_stage_trace"]["trace_version"] == "retrieval_stage_trace_v1"
    assert ask_payload["debug"]["retrieval_quality_features"]["feature_version"] == "retrieval_quality_features_v1"
    assert ask_payload["debug"]["candidate_pages"] == ask_payload["debug"]["retrieved_pages"]
    assert ask_payload["debug"]["evidence_selection_trace"]["trace_version"] == "evidence_selection_trace_v1"
    assert ask_payload["debug"]["evidence_selection_trace"]["route_name"] == "article_lookup"
    assert ask_payload["debug"]["evidence_selection_trace"]["retrieved_candidate_count"] == len(
        ask_payload["debug"]["retrieved_pages"]
    )
    assert ask_payload["debug"]["evidence_selection_trace"]["used_candidate_count"] == len(
        ask_payload["debug"]["used_pages"]
    )

    non_article = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "q-route-default",
                "question": "Show amendment history for this law",
                "answer_type": "free_text",
                "route_hint": "history_lineage",
                "tags": ["e2e"],
            },
            "runtime_policy": {
                "use_llm": False,
                "max_candidate_pages": 8,
                "max_context_paragraphs": 8,
                "page_index_base_export": 0,
                "scoring_policy_version": "contest_v2026_public_rules_v1",
                "allow_dense_fallback": True,
                "return_debug_trace": True,
            },
        },
    )
    assert non_article.status_code == 200
    non_article_payload = non_article.json()
    assert non_article_payload["route_name"] == "history_lineage"
    assert non_article_payload["telemetry"]["search_profile"] == "history_lineage_graph_v1"
    assert non_article_payload["debug"]["retrieval_profile_id"] == "history_lineage_graph_v1"

    no_answer_fast_path = client.post(
        "/v1/qa/ask",
        json={
            "project_id": project_id,
            "question": {
                "id": "q-no-answer-fast-path",
                "question": "What did the jury decide in case ENF 053/2025?",
                "answer_type": "free_text",
                "tags": ["e2e"],
            },
            "runtime_policy": {
                "use_llm": False,
                "max_candidate_pages": 8,
                "max_context_paragraphs": 8,
                "page_index_base_export": 0,
                "scoring_policy_version": "contest_v2026_public_rules_v1",
                "allow_dense_fallback": True,
                "return_debug_trace": True,
            },
        },
    )
    assert no_answer_fast_path.status_code == 200
    no_answer_fast_path_payload = no_answer_fast_path.json()
    assert no_answer_fast_path_payload["route_name"] == "no_answer"
    assert no_answer_fast_path_payload["abstained"] is True
    assert no_answer_fast_path_payload["sources"] == []
    assert no_answer_fast_path_payload["telemetry"]["search_profile"] == "no_answer_fast_path_v1"
    assert no_answer_fast_path_payload["debug"]["retrieval_profile_id"] == "no_answer_fast_path_v1"
    assert no_answer_fast_path_payload["debug"]["no_answer_fast_path_triggered"] is True
    assert no_answer_fast_path_payload["debug"]["candidate_page_budget"] == 0
    assert no_answer_fast_path_payload["debug"]["used_page_budget"] == 0
    assert no_answer_fast_path_payload["debug"]["evidence_selection_trace"]["no_answer_fast_path_triggered"] is True
    assert no_answer_fast_path_payload["debug"]["evidence_selection_trace"]["selection_rule"] == "no_answer_fast_path"
    assert no_answer_fast_path_payload["debug"]["evidence_selection_trace"]["retrieved_candidate_count"] == 0
    assert no_answer_fast_path_payload["debug"]["evidence_selection_trace"]["used_candidate_count"] == 0
    assert no_answer_fast_path_payload["debug"]["retrieval_stage_trace"]["retrieval_skipped"] is True
    assert (
        no_answer_fast_path_payload["debug"]["retrieval_stage_trace"]["retrieval_skipped_reason"]
        == "route_no_answer_fast_path"
    )
    assert no_answer_fast_path_payload["debug"]["telemetry_shadow"]["gen_ai"]["no_answer_fast_path_triggered"] is True

    imported_questions = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [
                {
                    "id": "q-1",
                    "question": "sample",
                    "answer_type": "free_text",
                },
                {
                    "id": "q-2",
                    "question": "sample",
                    "answer_type": "free_text",
                },
            ],
        },
    )
    assert imported_questions.status_code == 200

    batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": ["q-1", "q-2"],
            "runtime_policy": {
                "use_llm": False,
                "max_candidate_pages": 8,
                "max_context_paragraphs": 8,
                "page_index_base_export": 0,
                "scoring_policy_version": "contest_v2026_public_rules_v1",
                "allow_dense_fallback": True,
                "return_debug_trace": False,
            },
        },
    )
    assert batch.status_code == 202
    run_id = batch.json()["run_id"]

    run_get = client.get(f"/v1/runs/{run_id}")
    assert run_get.status_code == 200
    assert run_get.json()["run_id"] == run_id

    run_item = client.get(f"/v1/runs/{run_id}/questions/q-1")
    assert run_item.status_code == 200

    review_detail = client.get(f"/v1/runs/{run_id}/questions/q-1/detail")
    assert review_detail.status_code == 200
    review_payload = review_detail.json()
    assert review_payload["run_id"] == run_id
    assert review_payload["question_id"] == "q-1"
    assert "retrieved_chunk_ids" in review_payload["evidence"]
    assert "used_chunk_ids" in review_payload["evidence"]
    assert "documents" in review_payload["document_viewer"]

    first_document_id = review_payload["document_viewer"]["default_document_id"]
    doc_file = client.get(f"/v1/corpus/documents/{first_document_id}/file")
    assert doc_file.status_code == 200
    assert doc_file.headers["content-type"].startswith("application/pdf")

    exported_submission = client.post(
        f"/v1/runs/{run_id}/export-submission",
        json={"page_index_base": 0},
    )
    assert exported_submission.status_code == 200
    assert "artifact_url" in exported_submission.json()

    created_gold_ds = client.post(
        "/v1/gold/datasets",
        json={
            "project_id": project_id,
            "name": "e2e-gold",
            "version": "1.0.0",
        },
    )
    assert created_gold_ds.status_code == 200
    gold_dataset_id = created_gold_ds.json()["gold_dataset_id"]

    promoted = client.post(
        f"/v1/runs/{run_id}/questions/q-1/promote-to-gold",
        json={"gold_dataset_id": gold_dataset_id},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "promoted"

    create_gold_q = client.post(
        f"/v1/gold/datasets/{gold_dataset_id}/questions",
        json={
            "question_id": "q-1",
            "canonical_answer": ask_payload["answer"],
            "answer_type": "free_text",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": [source_page_id],
                    "notes": "e2e",
                }
            ],
        },
    )
    assert create_gold_q.status_code == 200

    created_eval = client.post(
        "/v1/eval/runs",
        json={
            "run_id": run_id,
            "gold_dataset_id": gold_dataset_id,
            "scoring_policy_version": "contest_v2026_public_rules_v1",
            "judge_policy_version": "judge_v1",
        },
    )
    assert created_eval.status_code == 202
    eval_run_id = created_eval.json()["eval_run_id"]

    eval_run = client.get(f"/v1/eval/runs/{eval_run_id}")
    assert eval_run.status_code == 200
    report = client.get(f"/v1/eval/runs/{eval_run_id}/report")
    assert report.status_code == 200
    assert "items" in report.json()
    assert "answer_type" in report.json()["items"][0]
    assert "error_tags" in report.json()["items"][0]
    assert "value_report" in report.json()
    assert report.json()["value_report"]["report_version"] == "value_report.v1"

    synth_job = client.post(
        "/v1/synth/jobs",
        json={
            "job_id": str(uuid4()),
            "project_id": project_id,
            "status": "queued",
            "source_scope": {"document_ids": [], "doc_types": []},
            "generation_policy": {
                "target_count": 3,
                "answer_type_mix": {"free_text": 1.0},
                "route_mix": {"article_lookup": 1.0},
                "adversarial_ratio": 0.0,
                "paraphrase_ratio": 0.0,
                "require_human_review": True,
            },
        },
    )
    assert synth_job.status_code == 200
    job_id = synth_job.json()["job_id"]

    preview = client.post(f"/v1/synth/jobs/{job_id}/preview", json={"limit": 2})
    assert preview.status_code == 200

    publish = client.post(f"/v1/synth/jobs/{job_id}/publish", json={})
    assert publish.status_code == 200
    assert "artifact_url" in publish.json()

    policies = client.get("/v1/config/scoring-policies")
    assert policies.status_code == 200
    assert len(policies.json()["items"]) >= 1


@pytest.mark.parametrize(
    ("raw_answer", "answer_type", "expected_answer", "expected_normalized"),
    [
        ("AED 12,500.00", "number", 12500, "12500"),
        ("7 March 2024", "date", "2024-03-07", "2024-03-07"),
        ("  mariam   al haddad  ", "name", "Mariam Al Haddad", "Mariam Al Haddad"),
        (
            [" Omar Al Haddad ", "mariam al haddad", "Omar Al Haddad"],
            "names",
            ["Mariam Al Haddad", "Omar Al Haddad"],
            "Mariam Al Haddad, Omar Al Haddad",
        ),
    ],
)
def test_typed_answer_normalization_invariants_are_canonical(
    raw_answer: object,
    answer_type: str,
    expected_answer: object,
    expected_normalized: str,
) -> None:
    normalized_answer, normalized_text = normalize_answer(raw_answer, answer_type)
    assert normalized_answer == expected_answer
    assert normalized_text == expected_normalized


@pytest.mark.parametrize(
    (
        "answer_type",
        "question_text",
        "route_hint",
        "seed_rows",
        "expected_answer",
        "expected_answer_normalized",
        "expected_solver_version",
        "expected_trace_path",
    ),
    [
        (
            "boolean",
            "Was the Employment Law enacted in the same year as the Intellectual Property Law?",
            "article_lookup",
            [
                {
                    "chunk_id": "employment_boolean_chunk",
                    "doc_type": "law",
                    "text": "Employment Law No. 2 of 2019 was enacted on 28 August 2019.",
                    "retrieval_text": "Employment Law enacted same year 2019 article lookup",
                    "paragraph_overrides": {"dates": ["2019-08-28"]},
                    "chunk_overrides": {"law_number": "2", "law_year": 2019, "dates": ["2019-08-28"]},
                },
                {
                    "chunk_id": "ip_boolean_chunk",
                    "doc_type": "law",
                    "text": "Intellectual Property Law No. 4 of 2019 was enacted on 10 September 2019.",
                    "retrieval_text": "Intellectual Property Law enacted same year 2019 article lookup",
                    "paragraph_overrides": {"dates": ["2019-09-10"]},
                    "chunk_overrides": {"law_number": "4", "law_year": 2019, "dates": ["2019-09-10"]},
                },
            ],
            True,
            "true",
            "typed_deterministic_solver_v1",
            "boolean_same_year",
        ),
        (
            "number",
            "What was the claim value referenced in the appeal judgment CA 005/2025?",
            "single_case_extraction",
            [
                {
                    "chunk_id": "claim_value_number_chunk",
                    "doc_type": "case",
                    "text": "In appeal judgment CA 005/2025, the claim value was AED 12,500.00.",
                    "retrieval_text": "claim value appeal judgment CA 005/2025 AED 12,500.00",
                    "paragraph_overrides": {"money_mentions": ["AED 12,500.00"], "case_refs": ["CA 005/2025"]},
                    "chunk_overrides": {
                        "case_number": "CA 005/2025",
                        "money_values": ["AED 12,500.00"],
                    },
                }
            ],
            12500,
            "12500",
            "typed_deterministic_solver_v1",
            "number_evidence_value",
        ),
        (
            "date",
            "On what date was the Employment Law Amendment Law enacted?",
            "history_lineage",
            [
                {
                    "chunk_id": "enactment_date_chunk",
                    "doc_type": "enactment_notice",
                    "text": "The Employment Law Amendment Law was enacted on 7 March 2024.",
                    "retrieval_text": "Employment Law Amendment Law enacted on 7 March 2024",
                    "paragraph_overrides": {"dates": ["7 March 2024"]},
                    "chunk_overrides": {"dates": ["7 March 2024"], "commencement_date": "7 March 2024"},
                }
            ],
            "2024-03-07",
            "2024-03-07",
            "law_history_deterministic_solver_v1",
            "history_date_evidence_value",
        ),
        (
            "name",
            "Which case was decided earlier: CFI 016/2025 or ENF 269/2023?",
            "single_case_extraction",
            [
                {
                    "chunk_id": "case_name_chunk_a",
                    "doc_type": "case",
                    "text": "Case CFI 016/2025 was decided on 14 May 2025.",
                    "retrieval_text": "CFI 016/2025 decided on 14 May 2025 case earlier",
                    "paragraph_overrides": {"dates": ["2025-05-14"], "case_refs": ["CFI 016/2025"]},
                    "chunk_overrides": {"case_number": "CFI 016/2025", "decision_date": "2025-05-14"},
                },
                {
                    "chunk_id": "case_name_chunk_b",
                    "doc_type": "case",
                    "text": "Case ENF 269/2023 was decided on 2 November 2023.",
                    "retrieval_text": "ENF 269/2023 decided on 2 November 2023 case earlier",
                    "paragraph_overrides": {"dates": ["2023-11-02"], "case_refs": ["ENF 269/2023"]},
                    "chunk_overrides": {"case_number": "ENF 269/2023", "decision_date": "2023-11-02"},
                },
            ],
            "ENF 269/2023",
            "ENF 269/2023",
            "typed_deterministic_solver_v1",
            "name_case_timeline",
        ),
        (
            "names",
            "Who were the claimants in case CFI 010/2024?",
            "single_case_extraction",
            [
                {
                    "chunk_id": "claimants_names_chunk",
                    "doc_type": "case",
                    "text": "Claimants: Mariam Al Haddad; Omar Al Haddad; Mariam Al Haddad.",
                    "retrieval_text": "claimants in case CFI 010/2024 Mariam Al Haddad Omar Al Haddad",
                    "paragraph_overrides": {
                        "entities": ["Mariam Al Haddad", "Omar Al Haddad", "Mariam Al Haddad"],
                        "case_refs": ["CFI 010/2024"],
                    },
                    "chunk_overrides": {
                        "case_number": "CFI 010/2024",
                        "entity_names": ["Mariam Al Haddad", "Omar Al Haddad", "Mariam Al Haddad"],
                        "party_names_normalized": ["mariam al haddad", "omar al haddad"],
                    },
                }
            ],
            ["Mariam Al Haddad", "Omar Al Haddad"],
            "Mariam Al Haddad, Omar Al Haddad",
            "typed_deterministic_solver_v1",
            "names_evidence_list",
        ),
    ],
)
def test_typed_solver_regressions_follow_deterministic_evidence_path(
    answer_type: str,
    question_text: str,
    route_hint: str,
    seed_rows: list[dict],
    expected_answer: object,
    expected_answer_normalized: str,
    expected_solver_version: str,
    expected_trace_path: str,
) -> None:
    state = _snapshot_solver_runtime_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        project_id = str(uuid4())
        client = TestClient(app)

        for row in seed_rows:
            _seed_typed_solver_candidate(
                project_id,
                chunk_id=row["chunk_id"],
                text=row["text"],
                retrieval_text=row["retrieval_text"],
                doc_type=row["doc_type"],
                paragraph_overrides=row.get("paragraph_overrides"),
                chunk_overrides=row.get("chunk_overrides"),
            )

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": f"typed-{answer_type}",
                    "question": question_text,
                    "answer_type": answer_type,
                    "route_hint": route_hint,
                    "tags": ["typed-regression"],
                },
                "runtime_policy": _runtime_policy_payload(return_debug_trace=True),
            },
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["answer"] == expected_answer
        assert payload["answer_normalized"] == expected_answer_normalized
        assert payload["abstained"] is False
        assert payload["telemetry"]["model_name"] == "deterministic-router"
        assert payload["debug"]["solver_trace"]["solver_version"] == expected_solver_version
        assert payload["debug"]["solver_trace"]["execution_mode"] == "deterministic_evidence"
        assert payload["debug"]["solver_trace"]["path"] == expected_trace_path
        assert payload["debug"]["solver_trace"]["matched_candidate_count"] >= 1
        assert payload["debug"]["solver_trace"]["candidate_count"] == len(seed_rows)
        assert len(payload["sources"]) >= 1
        assert len(payload["debug"]["used_pages"]) >= 1
    finally:
        _restore_solver_runtime_state(state)


def test_boolean_same_year_solver_ignores_unrelated_earlier_candidates() -> None:
    state = _snapshot_solver_runtime_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        project_id = str(uuid4())
        client = TestClient(app)

        seed_rows = [
            {
                "chunk_id": "distractor_law_a_chunk",
                "doc_type": "law",
                "text": "Consumer Protection Law No. 7 of 2019 was enacted on 11 January 2019.",
                "retrieval_text": "Consumer Protection Law enacted in 2019 unrelated distractor",
                "paragraph_overrides": {"dates": ["2019-01-11"]},
                "chunk_overrides": {"law_number": "7", "law_year": 2019, "dates": ["2019-01-11"]},
            },
            {
                "chunk_id": "distractor_law_b_chunk",
                "doc_type": "law",
                "text": "Companies Law No. 5 of 2019 was enacted on 19 February 2019.",
                "retrieval_text": "Companies Law enacted in 2019 unrelated distractor",
                "paragraph_overrides": {"dates": ["2019-02-19"]},
                "chunk_overrides": {"law_number": "5", "law_year": 2019, "dates": ["2019-02-19"]},
            },
            {
                "chunk_id": "employment_boolean_target_chunk",
                "doc_type": "law",
                "text": "Employment Law No. 2 of 2019 was enacted on 28 August 2019.",
                "retrieval_text": "Employment Law enacted same year 2019 target",
                "paragraph_overrides": {"dates": ["2019-08-28"]},
                "chunk_overrides": {"law_number": "2", "law_year": 2019, "dates": ["2019-08-28"]},
            },
            {
                "chunk_id": "ip_boolean_target_chunk",
                "doc_type": "law",
                "text": "Intellectual Property Law No. 4 of 2019 was enacted on 10 September 2019.",
                "retrieval_text": "Intellectual Property Law enacted same year 2019 target",
                "paragraph_overrides": {"dates": ["2019-09-10"]},
                "chunk_overrides": {"law_number": "4", "law_year": 2019, "dates": ["2019-09-10"]},
            },
        ]

        for row in seed_rows:
            _seed_typed_solver_candidate(
                project_id,
                chunk_id=row["chunk_id"],
                text=row["text"],
                retrieval_text=row["retrieval_text"],
                doc_type=row["doc_type"],
                paragraph_overrides=row.get("paragraph_overrides"),
                chunk_overrides=row.get("chunk_overrides"),
            )

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "typed-boolean-distractors",
                    "question": "Was the Employment Law enacted in the same year as the Intellectual Property Law?",
                    "answer_type": "boolean",
                    "route_hint": "article_lookup",
                    "tags": ["typed-regression", "distractor"],
                },
                "runtime_policy": _runtime_policy_payload(return_debug_trace=True),
            },
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["answer"] is True
        assert payload["answer_normalized"] == "true"
        assert payload["abstained"] is False
        assert payload["debug"]["solver_trace"]["path"] == "boolean_same_year"
        assert payload["debug"]["solver_trace"]["candidate_count"] == len(seed_rows)
        assert payload["debug"]["solver_trace"]["matched_candidate_count"] == 2
        assert len(payload["debug"]["solver_trace"]["matched_candidate_indices"]) == 2
        assert payload["debug"]["solver_trace"]["values_considered"] == [
            "Employment Law@2019",
            "Intellectual Property Law@2019",
        ]
    finally:
        _restore_solver_runtime_state(state)


def test_name_case_timeline_solver_ignores_unrelated_case_distractors() -> None:
    state = _snapshot_solver_runtime_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        project_id = str(uuid4())
        client = TestClient(app)

        seed_rows = [
            {
                "chunk_id": "distractor_case_chunk",
                "doc_type": "case",
                "text": "Case ARB 111/2022 was decided on 12 January 2022.",
                "retrieval_text": "ARB 111/2022 decided on 12 January 2022 unrelated distractor",
                "paragraph_overrides": {"dates": ["2022-01-12"], "case_refs": ["ARB 111/2022"]},
                "chunk_overrides": {"case_number": "ARB 111/2022", "decision_date": "2022-01-12"},
            },
            {
                "chunk_id": "case_name_target_chunk_a",
                "doc_type": "case",
                "text": "Case CFI 016/2025 was decided on 14 May 2025.",
                "retrieval_text": "CFI 016/2025 decided on 14 May 2025 target case",
                "paragraph_overrides": {"dates": ["2025-05-14"], "case_refs": ["CFI 016/2025"]},
                "chunk_overrides": {"case_number": "CFI 016/2025", "decision_date": "2025-05-14"},
            },
            {
                "chunk_id": "case_name_target_chunk_b",
                "doc_type": "case",
                "text": "Case ENF 269/2023 was decided on 2 November 2023.",
                "retrieval_text": "ENF 269/2023 decided on 2 November 2023 target case",
                "paragraph_overrides": {"dates": ["2023-11-02"], "case_refs": ["ENF 269/2023"]},
                "chunk_overrides": {"case_number": "ENF 269/2023", "decision_date": "2023-11-02"},
            },
        ]

        for row in seed_rows:
            _seed_typed_solver_candidate(
                project_id,
                chunk_id=row["chunk_id"],
                text=row["text"],
                retrieval_text=row["retrieval_text"],
                doc_type=row["doc_type"],
                paragraph_overrides=row.get("paragraph_overrides"),
                chunk_overrides=row.get("chunk_overrides"),
            )

        response = client.post(
            "/v1/qa/ask",
            json={
                "project_id": project_id,
                "question": {
                    "id": "typed-name-distractors",
                    "question": "Which case was decided earlier: CFI 016/2025 or ENF 269/2023?",
                    "answer_type": "name",
                    "route_hint": "single_case_extraction",
                    "tags": ["typed-regression", "distractor"],
                },
                "runtime_policy": _runtime_policy_payload(return_debug_trace=True),
            },
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["answer"] == "ENF 269/2023"
        assert payload["answer_normalized"] == "ENF 269/2023"
        assert payload["abstained"] is False
        assert payload["debug"]["solver_trace"]["path"] == "name_case_timeline"
        assert payload["debug"]["solver_trace"]["candidate_count"] == len(seed_rows)
        assert payload["debug"]["solver_trace"]["matched_candidate_count"] == 2
        assert len(payload["debug"]["solver_trace"]["matched_candidate_indices"]) == 2
        assert payload["debug"]["solver_trace"]["values_considered"] == [
            "ENF 269/2023@2023-11-02",
            "CFI 016/2025@2025-05-14",
        ]
    finally:
        _restore_solver_runtime_state(state)


def test_gold_lock_workflow_enforces_immutability_and_audit_trail() -> None:
    project_id = str(uuid4())
    client = TestClient(app)
    audit_start = len(store.audit_log)

    dataset_response = client.post(
        "/v1/gold/datasets",
        json={
            "project_id": project_id,
            "name": "lock-regression",
            "version": "1.0.0",
        },
    )
    assert dataset_response.status_code == 200
    gold_dataset_id = dataset_response.json()["gold_dataset_id"]

    question_response = client.post(
        f"/v1/gold/datasets/{gold_dataset_id}/questions",
        json={
            "question_id": "q-lock",
            "canonical_answer": "answer",
            "answer_type": "free_text",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["sample_0"],
                }
            ],
        },
    )
    assert question_response.status_code == 200
    gold_question_id = question_response.json()["gold_question_id"]

    update_response = client.patch(
        f"/v1/gold/questions/{gold_question_id}",
        json={"notes": "updated before lock"},
    )
    assert update_response.status_code == 200

    add_source_response = client.post(
        f"/v1/gold/questions/{gold_question_id}/source-sets",
        json={"is_primary": False, "page_ids": ["sample_1"], "notes": "secondary"},
    )
    assert add_source_response.status_code == 200

    review_response = client.post(
        f"/v1/gold/questions/{gold_question_id}/review",
        json={"decision": "approve", "comment": "qa approved"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "reviewed"

    lock_response = client.post(f"/v1/gold/datasets/{gold_dataset_id}/lock", json={})
    assert lock_response.status_code == 200
    assert lock_response.json()["status"] == "locked"

    idempotent_lock = client.post(f"/v1/gold/datasets/{gold_dataset_id}/lock", json={})
    assert idempotent_lock.status_code == 200
    assert idempotent_lock.json()["status"] == "already_locked"

    blocked_create = client.post(
        f"/v1/gold/datasets/{gold_dataset_id}/questions",
        json={
            "question_id": "q-lock-blocked",
            "canonical_answer": "blocked",
            "answer_type": "free_text",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["sample_2"],
                }
            ],
        },
    )
    assert blocked_create.status_code == 409
    assert "locked and immutable" in blocked_create.json()["detail"]

    blocked_update = client.patch(
        f"/v1/gold/questions/{gold_question_id}",
        json={"notes": "should fail"},
    )
    assert blocked_update.status_code == 409
    assert "locked and immutable" in blocked_update.json()["detail"]

    blocked_source_set = client.post(
        f"/v1/gold/questions/{gold_question_id}/source-sets",
        json={"is_primary": False, "page_ids": ["sample_3"]},
    )
    assert blocked_source_set.status_code == 409
    assert "locked and immutable" in blocked_source_set.json()["detail"]

    blocked_review = client.post(
        f"/v1/gold/questions/{gold_question_id}/review",
        json={"decision": "changes_requested", "comment": "should fail"},
    )
    assert blocked_review.status_code == 409
    assert "locked and immutable" in blocked_review.json()["detail"]

    audit_tail = store.audit_log[audit_start:]
    event_targets = {(entry.get("event"), entry.get("target")) for entry in audit_tail}
    assert ("gold_dataset_created", gold_dataset_id) in event_targets
    assert ("gold_question_created", gold_question_id) in event_targets
    assert ("gold_question_updated", gold_question_id) in event_targets
    assert ("gold_source_set_added", gold_question_id) in event_targets
    assert ("gold_question_review", gold_question_id) in event_targets
    assert ("gold_dataset_locked", gold_dataset_id) in event_targets

    locked_rejections = [entry for entry in audit_tail if entry.get("event") == "gold_dataset_mutation_rejected_locked"]
    assert len(locked_rejections) == 4


def test_gold_export_compatibility_assertions_are_machine_checkable_for_eval() -> None:
    project_id = str(uuid4())
    dataset_id = str(uuid4())
    client = TestClient(app)

    imported = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [
                {
                    "id": "q-export",
                    "question": "What is article 1?",
                    "answer_type": "free_text",
                }
            ],
        },
    )
    assert imported.status_code == 200

    ask_batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": ["q-export"],
            "runtime_policy": _runtime_policy_payload(),
        },
    )
    assert ask_batch.status_code == 202
    run_id = ask_batch.json()["run_id"]

    dataset_response = client.post(
        "/v1/gold/datasets",
        json={
            "project_id": project_id,
            "name": "eval-export",
            "version": "1.0.0",
        },
    )
    assert dataset_response.status_code == 200
    gold_dataset_id = dataset_response.json()["gold_dataset_id"]

    question_response = client.post(
        f"/v1/gold/datasets/{gold_dataset_id}/questions",
        json={
            "question_id": "q-export",
            "canonical_answer": None,
            "answer_type": "free_text",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["sample_0"],
                }
            ],
        },
    )
    assert question_response.status_code == 200
    gold_question_id = question_response.json()["gold_question_id"]

    export_ok = client.get(f"/v1/gold/datasets/{gold_dataset_id}/export")
    assert export_ok.status_code == 200
    export_ok_payload = export_ok.json()
    compatibility_ok = export_ok_payload["eval_export_compatibility"]
    assert compatibility_ok["assertion_version"] == "eval_gold_export_compatibility.v1"
    assert compatibility_ok["compatible"] is True
    assert compatibility_ok["issue_count"] == 0

    artifact_path = Path(urlparse(export_ok_payload["artifact_url"]).path)
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["eval_export_compatibility"]["compatible"] is True

    corrupted = client.patch(
        f"/v1/gold/questions/{gold_question_id}",
        json={"source_sets": []},
    )
    assert corrupted.status_code == 200

    export_broken = client.get(f"/v1/gold/datasets/{gold_dataset_id}/export")
    assert export_broken.status_code == 200
    broken_compatibility = export_broken.json()["eval_export_compatibility"]
    assert broken_compatibility["compatible"] is False
    assert broken_compatibility["issue_count"] > 0
    assert any(issue["field"] == "source_sets" for issue in broken_compatibility["issues"])

    eval_response = client.post(
        "/v1/eval/runs",
        json={
            "run_id": run_id,
            "gold_dataset_id": gold_dataset_id,
            "scoring_policy_version": "contest_v2026_public_rules_v1",
            "judge_policy_version": "judge_v1",
        },
    )
    assert eval_response.status_code == 422
    detail = eval_response.json()["detail"]
    assert detail["code"] == "gold_export_incompatible_for_eval"
    assert detail["compatibility"]["compatible"] is False
    assert detail["compatibility"]["issue_count"] > 0


def test_repeat_ingest_is_deterministic_for_identity_and_artifacts(tmp_path: Path) -> None:
    first_project_id = str(uuid4())
    second_project_id = str(uuid4())
    zip_path = tmp_path / "deterministic_docs.zip"
    _make_determinism_zip(zip_path)
    client = TestClient(app)

    payload = {
        "project_id": first_project_id,
        "blob_url": str(zip_path),
        "parse_policy": "balanced",
        "dedupe_enabled": True,
    }

    imported_first = client.post("/v1/corpus/import-zip", json=payload)
    assert imported_first.status_code == 202
    first_body = imported_first.json()
    assert first_body["status"] == "accepted"
    assert "ingest_diagnostics" in first_body
    first_diagnostics = first_body["ingest_diagnostics"]
    assert first_diagnostics["diagnostics_version"] == "ingest_diagnostics_v1"
    assert first_diagnostics["identity_fingerprint"]
    assert first_diagnostics["artifact_fingerprint"]

    snapshot_first = _collect_ingest_identity_snapshot(client, project_id=first_project_id)

    imported_second = client.post("/v1/corpus/import-zip", json={**payload, "project_id": second_project_id})
    assert imported_second.status_code == 202
    second_body = imported_second.json()
    assert second_body["status"] == "accepted"
    second_diagnostics = second_body["ingest_diagnostics"]

    snapshot_second = _collect_ingest_identity_snapshot(client, project_id=second_project_id)

    assert second_diagnostics["identity_fingerprint"] == first_diagnostics["identity_fingerprint"]
    assert second_diagnostics["artifact_fingerprint"] == first_diagnostics["artifact_fingerprint"]
    assert snapshot_second == snapshot_first


def test_import_upload_accepts_zip_without_project_id(tmp_path: Path) -> None:
    zip_path = tmp_path / "upload_docs.zip"
    _make_zip_with_pdf(zip_path)
    client = TestClient(app)

    with zip_path.open("rb") as handle:
        imported = client.post(
            "/v1/corpus/import-upload",
            data={"parse_policy": "balanced", "dedupe_enabled": "true"},
            files={"file": ("upload_docs.zip", handle, "application/zip")},
        )

    assert imported.status_code == 202
    assert imported.json()["status"] == "accepted"

    processing = client.get("/v1/corpus/processing-results", params={"limit": 20})
    assert processing.status_code == 200
    assert processing.json()["summary"]["documents"] >= 1


def test_import_strips_nul_bytes_from_extracted_corpus_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "nul_docs.zip"
    _make_zip_with_pdf(zip_path)
    client = TestClient(app)

    monkeypatch.setattr(ingest_module, "_extract_pdf_page_texts", lambda raw: (["Alpha\x00Beta"], 1, None))

    imported = client.post(
        "/v1/corpus/import-zip",
        json={
            "blob_url": str(zip_path),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        },
    )
    assert imported.status_code == 202

    documents = client.get("/v1/corpus/documents")
    assert documents.status_code == 200
    document_id = documents.json()["items"][0]["document_id"]
    detail = client.get(f"/v1/corpus/documents/{document_id}/detail")
    assert detail.status_code == 200
    page = detail.json()["pages"][0]
    chunk = page["chunks"][0]

    assert "\x00" not in page["text"]
    assert "\x00" not in chunk["text"]
    assert "\x00" not in chunk["text_clean"]
    assert "\x00" not in chunk["retrieval_text"]


def test_reingest_document_uses_source_pdf_and_refreshes_page_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip_path = tmp_path / "reingest_docs.zip"
    _make_zip_with_pdf(zip_path)
    client = TestClient(app)

    mode = {"value": "initial"}

    def fake_extract_pdf_page_texts(raw: bytes) -> tuple[list[str], int, str | None]:
        if mode["value"] == "initial":
            return (["Initial parser text"], 1, None)
        return (["Reingested parser text"], 1, None)

    monkeypatch.setattr(ingest_module, "_extract_pdf_page_texts", fake_extract_pdf_page_texts)

    imported = client.post(
        "/v1/corpus/import-zip",
        json={
            "blob_url": str(zip_path),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        },
    )
    assert imported.status_code == 202

    listed_before = client.get("/v1/corpus/documents")
    assert listed_before.status_code == 200
    items_before = listed_before.json()["items"]
    assert len(items_before) == 1
    document_id = str(items_before[0]["document_id"])

    detail_before = client.get(f"/v1/corpus/documents/{document_id}/detail")
    assert detail_before.status_code == 200
    assert "Initial parser text" in detail_before.json()["pages"][0]["text"]

    mode["value"] = "reingest"
    reingested = client.post(f"/v1/corpus/documents/{document_id}/reingest")
    assert reingested.status_code == 202
    assert reingested.json()["status"] == "accepted"

    listed_after = client.get("/v1/corpus/documents")
    assert listed_after.status_code == 200
    items_after = listed_after.json()["items"]
    assert len(items_after) == 1
    assert str(items_after[0]["document_id"]) == document_id

    detail_after = client.get(f"/v1/corpus/documents/{document_id}/detail")
    assert detail_after.status_code == 200
    page_text_after = detail_after.json()["pages"][0]["text"]
    assert "Reingested parser text" in page_text_after
    assert "Initial parser text" not in page_text_after


def test_ask_batch_rejects_unknown_dataset_question(tmp_path: Path) -> None:
    project_id = str(uuid4())
    dataset_id = str(uuid4())
    zip_path = tmp_path / "docs.zip"
    _make_zip_with_pdf(zip_path)
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

    imported_questions = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [{"id": "q-1", "question": "sample", "answer_type": "free_text"}],
        },
    )
    assert imported_questions.status_code == 200

    batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": ["q-local-1"],
            "runtime_policy": _runtime_policy_payload(return_debug_trace=False),
        },
    )
    assert batch.status_code == 404
    assert batch.json()["detail"] == "dataset question not found"


def test_promote_to_gold_rejects_cross_project_dataset(tmp_path: Path) -> None:
    project_id = str(uuid4())
    other_project_id = str(uuid4())
    dataset_id = str(uuid4())
    zip_path = tmp_path / "docs.zip"
    _make_zip_with_pdf(zip_path)
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

    imported_questions = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [{"id": "q-1", "question": "sample", "answer_type": "free_text"}],
        },
    )
    assert imported_questions.status_code == 200

    batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": ["q-1"],
            "runtime_policy": _runtime_policy_payload(return_debug_trace=False),
        },
    )
    assert batch.status_code == 202
    run_id = batch.json()["run_id"]

    created_gold_ds = client.post(
        "/v1/gold/datasets",
        json={
            "project_id": other_project_id,
            "name": "cross-project-gold",
            "version": "1.0.0",
        },
    )
    assert created_gold_ds.status_code == 200
    gold_dataset_id = created_gold_ds.json()["gold_dataset_id"]

    promoted = client.post(
        f"/v1/runs/{run_id}/questions/q-1/promote-to-gold",
        json={"gold_dataset_id": gold_dataset_id},
    )
    assert promoted.status_code == 409
    assert promoted.json()["detail"] == "gold dataset project does not match run project"


def test_enrichment_retry_endpoint_returns_role_runs(tmp_path: Path) -> None:
    project_id = str(uuid4())
    zip_path = tmp_path / "docs.zip"
    _make_zip_with_pdf(zip_path)
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
    enrichment_job = imported.json()["enrichment_job"]
    assert enrichment_job["role_sequence"] == [
        "chunk_interpreter",
        "chunk_validator",
        "document_synthesizer",
        "projection_agent",
    ]

    listed = client.get("/v1/corpus/documents", params={"project_id": project_id})
    assert listed.status_code == 200
    document_id = listed.json()["items"][0]["document_id"]
    detail = client.get(f"/v1/corpus/documents/{document_id}/detail")
    assert detail.status_code == 200
    paragraph_id = detail.json()["pages"][0]["chunks"][0]["paragraph_id"]

    retried = client.post(
        f"/v1/corpus/enrichment-jobs/{enrichment_job['job_id']}/retry",
        json={"target_type": "chunk", "target_ids": [paragraph_id]},
    )
    assert retried.status_code == 200
    retry_job = retried.json()["job"]
    assert retry_job["chunk_stage_runs"][paragraph_id]["chunk_interpreter"]["status"] == "completed"
    assert retry_job["chunk_stage_runs"][paragraph_id]["chunk_validator"]["status"] == "completed"
    assert retry_job["chunk_stage_runs"][paragraph_id]["projection_agent"]["status"] == "completed"


def test_no_answer_run_exports_empty_sources_and_review_has_no_used_pages() -> None:
    project_id = str(uuid4())
    dataset_id = str(uuid4())
    client = TestClient(app)

    imported_questions = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [
                {
                    "id": "q-no-answer",
                    "question": "What is the capital reserve ratio for the missing law?",
                    "answer_type": "free_text",
                }
            ],
        },
    )
    assert imported_questions.status_code == 200

    batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": ["q-no-answer"],
            "runtime_policy": _runtime_policy_payload(return_debug_trace=False),
        },
    )
    assert batch.status_code == 202
    run_id = batch.json()["run_id"]

    answer = client.get(f"/v1/runs/{run_id}/questions/q-no-answer")
    assert answer.status_code == 200
    assert answer.json()["abstained"] is True
    assert answer.json()["sources"] == []

    detail = client.get(f"/v1/runs/{run_id}/questions/q-no-answer/detail")
    assert detail.status_code == 200
    assert detail.json()["evidence"]["used_page_ids"] == []
    assert detail.json()["promotion_preview"]["source_sets"] == []

    exported = client.post(
        f"/v1/runs/{run_id}/export-submission",
        json={"page_index_base": 0},
    )
    assert exported.status_code == 200
    artifact_url = exported.json()["artifact_url"]
    exported_path = Path(urlparse(artifact_url).path)
    artifact_payload = json.loads(exported_path.read_text(encoding="utf-8"))
    assert artifact_payload["items"][0]["sources"] == []


def test_export_submission_official_matches_starter_kit_shape() -> None:
    client = TestClient(app)

    run = store.create_run(dataset_id=str(uuid4()), question_count=1, status="completed")
    run_id = run["run_id"]
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    prediction = QueryResponse(
        question_id="q-official-shape",
        answer="Fursa Consulting",
        answer_normalized="Fursa Consulting",
        answer_type="free_text",
        confidence=0.91,
        route_name="article_lookup",
        abstained=False,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc",
                pdf_id="443e04bc1a78940b3fcd5438d24b6c5f182a276d354a3108e738b193675de032",
                page_num=0,
                page_index_base=0,
                source_page_id="443e04bc1a78940b3fcd5438d24b6c5f182a276d354a3108e738b193675de032_0",
                used=True,
                evidence_role="primary",
                score=0.9,
            )
        ],
        telemetry=Telemetry(
            request_started_at=now,
            first_token_at=now,
            completed_at=now,
            ttft_ms=1180,
            total_response_ms=2440,
            time_per_output_token_ms=52.0,
            input_tokens=1420,
            output_tokens=188,
            model_name="participant-case10",
            route_name="article_lookup",
            judge_model_name=None,
            search_profile="default",
            telemetry_complete=True,
            trace_id=f"trace-{uuid4()}",
        ),
        debug=None,
    )
    store.upsert_run_question(run_id, prediction.question_id, prediction)

    exported = client.post(
        f"/v1/runs/{run_id}/export-submission-official",
        json={
            "page_index_base": 0,
            "architecture_summary": "Naive RAG with vector search",
        },
    )
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "official_starter_kit_v1"
    artifact_url = payload["artifact_url"]
    exported_path = Path(urlparse(artifact_url).path)
    artifact_payload = json.loads(exported_path.read_text(encoding="utf-8"))

    assert set(artifact_payload.keys()) == {"architecture_summary", "answers"}
    assert artifact_payload["architecture_summary"] == "Naive RAG with vector search"
    assert isinstance(artifact_payload["answers"], list) and len(artifact_payload["answers"]) == 1

    answer_item = artifact_payload["answers"][0]
    assert set(answer_item.keys()) == {"question_id", "answer", "telemetry"}
    assert answer_item["question_id"] == "q-official-shape"
    assert answer_item["answer"] == "Fursa Consulting"
    assert "sources" not in answer_item

    telemetry = answer_item["telemetry"]
    assert set(telemetry.keys()) == {"timing", "retrieval", "usage", "model_name"}
    assert telemetry["timing"] == {
        "ttft_ms": 1180,
        "tpot_ms": 52,
        "total_time_ms": 2440,
    }
    assert telemetry["retrieval"] == {
        "retrieved_chunk_pages": [
            {
                "doc_id": "443e04bc1a78940b3fcd5438d24b6c5f182a276d354a3108e738b193675de032",
                "page_numbers": [1],
            }
        ]
    }
    assert telemetry["usage"] == {
        "input_tokens": 1420,
        "output_tokens": 188,
    }
    assert telemetry["model_name"] == "participant-case10"


def test_export_submission_official_groups_pages_and_handles_abstain() -> None:
    client = TestClient(app)

    run = store.create_run(dataset_id=str(uuid4()), question_count=2, status="completed")
    run_id = run["run_id"]
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)

    grouped_prediction = QueryResponse(
        question_id="q-official-grouped-pages",
        answer="Law A is earlier",
        answer_normalized="Law A is earlier",
        answer_type="free_text",
        confidence=0.93,
        route_name="cross_law_compare",
        abstained=False,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc-alpha",
                pdf_id="doc-alpha",
                page_num=0,
                page_index_base=0,
                source_page_id="doc-alpha_0",
                used=True,
                evidence_role="primary",
                score=0.9,
            ),
            PageRef(
                project_id="proj",
                document_id="doc-alpha",
                pdf_id="doc-alpha",
                page_num=2,
                page_index_base=0,
                source_page_id="doc-alpha_2",
                used=True,
                evidence_role="primary",
                score=0.88,
            ),
            PageRef(
                project_id="proj",
                document_id="doc-beta",
                pdf_id="doc-beta",
                page_num=7,
                page_index_base=1,
                source_page_id="doc-beta_7",
                used=True,
                evidence_role="supporting",
                score=0.8,
            ),
            PageRef(
                project_id="proj",
                document_id="doc-beta",
                pdf_id="doc-beta",
                page_num=9,
                page_index_base=1,
                source_page_id="doc-beta_9",
                used=False,
                evidence_role="supporting",
                score=0.1,
            ),
        ],
        telemetry=Telemetry(
            request_started_at=now,
            first_token_at=now,
            completed_at=now,
            ttft_ms=900,
            total_response_ms=1700,
            time_per_output_token_ms=40.0,
            input_tokens=500,
            output_tokens=120,
            model_name="participant-case10",
            route_name="cross_law_compare",
            judge_model_name=None,
            search_profile="cross_law_compare_matrix_v1",
            telemetry_complete=True,
            trace_id=f"trace-{uuid4()}",
        ),
        debug=None,
    )
    abstain_prediction = QueryResponse(
        question_id="q-official-abstain",
        answer=None,
        answer_normalized=None,
        answer_type="free_text",
        confidence=0.0,
        route_name="cross_law_compare",
        abstained=True,
        sources=[],
        telemetry=Telemetry(
            request_started_at=now,
            first_token_at=now,
            completed_at=now,
            ttft_ms=300,
            total_response_ms=620,
            time_per_output_token_ms=0.0,
            input_tokens=210,
            output_tokens=0,
            model_name="participant-case10",
            route_name="cross_law_compare",
            judge_model_name=None,
            search_profile="cross_law_compare_matrix_v1",
            telemetry_complete=True,
            trace_id=f"trace-{uuid4()}",
        ),
        debug=None,
    )
    store.upsert_run_question(run_id, grouped_prediction.question_id, grouped_prediction)
    store.upsert_run_question(run_id, abstain_prediction.question_id, abstain_prediction)

    exported = client.post(
        f"/v1/runs/{run_id}/export-submission-official",
        json={"page_index_base": 0},
    )
    assert exported.status_code == 200
    payload = exported.json()
    artifact_url = payload["artifact_url"]
    exported_path = Path(urlparse(artifact_url).path)
    artifact_payload = json.loads(exported_path.read_text(encoding="utf-8"))
    answers = {entry["question_id"]: entry for entry in artifact_payload["answers"]}

    grouped_retrieval = answers["q-official-grouped-pages"]["telemetry"]["retrieval"]["retrieved_chunk_pages"]
    assert grouped_retrieval == [
        {"doc_id": "doc-alpha", "page_numbers": [1, 3]},
        {"doc_id": "doc-beta", "page_numbers": [7]},
    ]
    abstain_retrieval = answers["q-official-abstain"]["telemetry"]["retrieval"]["retrieved_chunk_pages"]
    assert abstain_retrieval == []


def test_export_submission_fails_closed_with_strict_contract_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRICT_COMPETITION_CONTRACTS", "1")
    client = TestClient(app)

    run = store.create_run(dataset_id=str(uuid4()), question_count=1, status="completed")
    run_id = run["run_id"]
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    invalid_prediction = QueryResponse(
        question_id="q-strict-preflight",
        answer="A",
        answer_normalized=None,
        answer_type="free_text",
        confidence=1.0,
        route_name="article_lookup",
        abstained=False,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc",
                pdf_id="doc",
                page_num=3,
                page_index_base=0,
                source_page_id="doc_1",
                used=True,
                evidence_role="primary",
                score=1.0,
            )
        ],
        telemetry=Telemetry(
            request_started_at=now,
            first_token_at=now,
            completed_at=now,
            ttft_ms=800,
            total_response_ms=1000,
            time_per_output_token_ms=1.0,
            input_tokens=8,
            output_tokens=8,
            model_name="test-model",
            route_name="article_lookup",
            judge_model_name=None,
            search_profile="default",
            telemetry_complete=True,
            trace_id=f"trace-{uuid4()}",
        ),
        debug=None,
    )
    store.upsert_run_question(run_id, "q-strict-preflight", invalid_prediction)

    exported = client.post(
        f"/v1/runs/{run_id}/export-submission",
        json={"page_index_base": 0},
    )
    assert exported.status_code == 422
    payload = exported.json()["detail"]
    assert payload["code"] == "submission_contract_preflight_failed"
    assert payload["preflight"]["strict_contract_mode"] is True
    assert payload["preflight"]["invalid_prediction_count"] == 1


def test_export_submission_official_fails_closed_with_strict_contract_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRICT_COMPETITION_CONTRACTS", "1")
    client = TestClient(app)

    run = store.create_run(dataset_id=str(uuid4()), question_count=1, status="completed")
    run_id = run["run_id"]
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    invalid_prediction = QueryResponse(
        question_id="q-strict-preflight-official",
        answer="A",
        answer_normalized=None,
        answer_type="free_text",
        confidence=1.0,
        route_name="article_lookup",
        abstained=False,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc",
                pdf_id="doc",
                page_num=3,
                page_index_base=0,
                source_page_id="doc_1",
                used=True,
                evidence_role="primary",
                score=1.0,
            )
        ],
        telemetry=Telemetry(
            request_started_at=now,
            first_token_at=now,
            completed_at=now,
            ttft_ms=800,
            total_response_ms=1000,
            time_per_output_token_ms=1.0,
            input_tokens=8,
            output_tokens=8,
            model_name="test-model",
            route_name="article_lookup",
            judge_model_name=None,
            search_profile="default",
            telemetry_complete=True,
            trace_id=f"trace-{uuid4()}",
        ),
        debug=None,
    )
    store.upsert_run_question(run_id, "q-strict-preflight-official", invalid_prediction)

    exported = client.post(
        f"/v1/runs/{run_id}/export-submission-official",
        json={"page_index_base": 0},
    )
    assert exported.status_code == 422
    payload = exported.json()["detail"]
    assert payload["code"] == "submission_contract_preflight_failed"
    assert payload["preflight"]["strict_contract_mode"] is True
    assert payload["preflight"]["invalid_prediction_count"] == 1


def test_review_console_endpoints_support_generation_lock_export_and_minicheck_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _snapshot_solver_runtime_state()
    try:
        store.feature_flags["canonical_chunk_model_v1"] = True
        store.feature_flags["review_console_v1"] = True
        store.feature_flags["review_mini_check_v1"] = True
        project_id = str(uuid4())
        dataset_id = str(uuid4())
        client = TestClient(app)

        seed_rows = [
            {
                "chunk_id": "review_case_a_chunk",
                "doc_type": "case",
                "text": "Case CFI 016/2025 was decided on 14 May 2025.",
                "retrieval_text": "CFI 016/2025 decided on 14 May 2025 target case",
                "paragraph_overrides": {"dates": ["2025-05-14"], "case_refs": ["CFI 016/2025"]},
                "chunk_overrides": {"case_number": "CFI 016/2025", "decision_date": "2025-05-14"},
            },
            {
                "chunk_id": "review_case_b_chunk",
                "doc_type": "case",
                "text": "Case ENF 269/2023 was decided on 2 November 2023.",
                "retrieval_text": "ENF 269/2023 decided on 2 November 2023 target case",
                "paragraph_overrides": {"dates": ["2023-11-02"], "case_refs": ["ENF 269/2023"]},
                "chunk_overrides": {"case_number": "ENF 269/2023", "decision_date": "2023-11-02"},
            },
        ]
        for row in seed_rows:
            _seed_typed_solver_candidate(
                project_id,
                chunk_id=row["chunk_id"],
                text=row["text"],
                retrieval_text=row["retrieval_text"],
                doc_type=row["doc_type"],
                paragraph_overrides=row.get("paragraph_overrides"),
                chunk_overrides=row.get("chunk_overrides"),
            )

        imported_questions = client.post(
            f"/v1/qa/datasets/{dataset_id}/import-questions",
            json={
                "project_id": project_id,
                "questions": [
                    {
                        "id": "q-review",
                        "question": "Which case was decided earlier: CFI 016/2025 or ENF 269/2023?",
                        "answer_type": "name",
                        "route_hint": "single_case_extraction",
                    }
                ],
            },
        )
        assert imported_questions.status_code == 200

        batch = client.post(
            "/v1/qa/ask-batch",
            json={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "question_ids": ["q-review"],
                "runtime_policy": _runtime_policy_payload(return_debug_trace=False),
            },
        )
        assert batch.status_code == 202
        run_id = batch.json()["run_id"]

        review_list = client.get("/v1/review/questions", params={"run_id": run_id})
        assert review_list.status_code == 200
        list_payload = review_list.json()
        assert list_payload["total"] == 1
        assert list_payload["items"][0]["question_id"] == "q-review"
        assert any(candidate["candidate_kind"] == "system" for candidate in list_payload["items"][0]["candidate_bundle"])

        review_detail = client.get(f"/v1/review/questions/q-review", params={"run_id": run_id})
        assert review_detail.status_code == 200
        assert review_detail.json()["question_id"] == "q-review"

        pdf_preview = client.get(f"/v1/review/questions/q-review/pdf-preview", params={"run_id": run_id})
        assert pdf_preview.status_code == 200
        assert "fallback" in pdf_preview.json()

        created_gold_ds = client.post(
            "/v1/gold/datasets",
            json={
                "project_id": project_id,
                "name": "review-gold",
                "version": "1.0.0",
            },
        )
        assert created_gold_ds.status_code == 200
        gold_dataset_id = created_gold_ds.json()["gold_dataset_id"]

        profile_response = client.post(
            "/v1/experiments/profiles",
            json={
                "name": "review-strong",
                "project_id": project_id,
                "dataset_id": dataset_id,
                "gold_dataset_id": gold_dataset_id,
                "runtime_policy": _runtime_policy_payload(return_debug_trace=False),
            },
        )
        assert profile_response.status_code == 200
        profile_id = profile_response.json()["profile_id"]

        generated = client.post(
            f"/v1/review/questions/q-review/generate-candidates",
            params={"run_id": run_id},
            json={"reviewer": "qa", "strong_profile_id": profile_id},
        )
        assert generated.status_code == 200
        generated_record = generated.json()["record"]
        assert any(candidate["candidate_kind"] == "strong_model" for candidate in generated_record["candidate_bundle"])
        strong_candidate = next(
            candidate for candidate in generated_record["candidate_bundle"] if candidate["candidate_kind"] == "strong_model"
        )

        accepted = client.post(
            f"/v1/review/questions/q-review/accept-candidate",
            params={"run_id": run_id},
            json={"reviewer": "qa", "candidate_kind": "system", "reviewer_confidence": 0.9},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted_decision"]["decision_source"] == "system"

        mini_check = client.post(
            f"/v1/review/questions/q-review/mini-check",
            params={"run_id": run_id},
            json={
                "reviewer": "qa",
                "candidate_kind": "strong_model",
                "candidate_answer": strong_candidate["answer"],
                "candidate_answerability": "answerable",
                "answer_type": "name",
                "evidence": [
                    {
                        "doc_id": "review_case_b",
                        "page_number": 0,
                        "snippet": "Case ENF 269/2023 was decided on 2 November 2023.",
                    }
                ],
            },
        )
        assert mini_check.status_code == 503
        assert "Azure OpenAI" in mini_check.json()["detail"]

        async def _fake_complete_chat(*args: object, **kwargs: object) -> tuple[str, dict[str, int]]:
            return (
                json.dumps(
                    {
                        "verdict": "not_supported",
                        "extracted_answer": "ENF 269/2023",
                        "confidence": 0.73,
                        "rationale": "Selected evidence supports ENF 269/2023 instead.",
                        "conflict_type": "answer_mismatch",
                    }
                ),
                {"prompt_tokens": 10, "completion_tokens": 12},
            )

        monkeypatch.setattr(review_router.llm_client, "complete_chat", _fake_complete_chat)
        monkeypatch.setattr(review_router.llm_client.config, "endpoint", "https://azure.example")
        monkeypatch.setattr(review_router.llm_client.config, "api_key", "key")
        monkeypatch.setattr(review_router.llm_client.config, "deployment", "gpt-test")

        mini_check_ready = client.post(
            f"/v1/review/questions/q-review/mini-check",
            params={"run_id": run_id},
            json={
                "reviewer": "qa",
                "candidate_kind": "strong_model",
                "candidate_answer": strong_candidate["answer"],
                "candidate_answerability": strong_candidate["answerability"],
                "answer_type": "name",
                "evidence": strong_candidate["sources"],
            },
        )
        assert mini_check_ready.status_code == 200
        ready_payload = mini_check_ready.json()
        assert ready_payload["mini_check_result"]["candidate_kind"] == "strong_model"
        assert ready_payload["mini_check_result"]["verdict"] == "not_supported"
        mini_check_candidate = next(
            candidate for candidate in ready_payload["record"]["candidate_bundle"] if candidate["candidate_kind"] == "mini_check"
        )
        assert mini_check_candidate["metadata"]["candidate_kind"] == "strong_model"

        locked = client.post(
            f"/v1/review/questions/q-review/lock-gold",
            params={"run_id": run_id},
            json={"gold_dataset_id": gold_dataset_id, "reviewer": "qa", "reviewer_confidence": 0.9},
        )
        assert locked.status_code == 200
        assert locked.json()["status"] == "gold_locked"

        unlocked = client.post(
            f"/v1/review/questions/q-review/unlock-gold",
            params={"run_id": run_id},
            json={"gold_dataset_id": gold_dataset_id, "reviewer": "qa"},
        )
        assert unlocked.status_code == 200
        assert unlocked.json()["status"] == "review_in_progress"

        exported = client.post(f"/v1/review/report/{run_id}/export", json={"reviewer": "qa", "format": "both"})
        assert exported.status_code == 200
        export_payload = exported.json()
        assert export_payload["summary"]["total_questions"] == 1
        assert "review_report_json" in export_payload

        downloadable = client.get(f"/v1/review/report/{run_id}/export")
        assert downloadable.status_code == 200
        assert downloadable.headers["content-disposition"].startswith("attachment;")
        downloadable_payload = downloadable.json()
        assert downloadable_payload["schema_version"] == "review_report_export.v1"
        assert downloadable_payload["run_id"] == run_id
        assert "exported_at" in downloadable_payload

        report = client.get(f"/v1/review/report/{run_id}")
        assert report.status_code == 200
        assert report.json()["summary"]["total_questions"] == 1
    finally:
        _restore_solver_runtime_state(state)
