#!/usr/bin/env python3
"""Run rules-first chunk/proposition evaluation on the full 30-document corpus."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
import sys

if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.artifacts import artifact_path  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from scripts.competition_batch import _git_metadata  # noqa: E402
from scripts.run_chunk_processing_pilot import (  # noqa: E402
    FIXTURE_PATH,
    SOURCE_ZIP_PATH,
    _apply_enrichment_result,
    _case_merge_issues,
    _cross_article_chunks,
    _expanded_frozen_query_report,
    _markdown_from_mapping,
    _prepare_env,
    _provenance_report,
    _run_query_batch,
    _run_real_corpus_checks,
    _write_json,
    _write_md,
)
from services.ingest.agentic_enrichment import retry_agentic_corpus_enrichment  # noqa: E402
from services.ingest.chunk_semantics import _is_semantically_rich_chunk  # noqa: E402


DEFAULT_OUTPUT_DIR = artifact_path("competition_runs", "full", "chunk_processing_full_corpus_eval_v1")
DEFAULT_PROJECT_ID = "competition_chunk_processing_full_corpus_eval_v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _project_snapshot(project_id: str, *, pdf_ids: List[str] | None = None) -> Dict[str, List[Dict[str, Any]]]:
    pdf_id_set = {str(item).strip() for item in (pdf_ids or []) if str(item).strip()}
    documents = [
        item
        for item in store.documents.values()
        if str(item.get("project_id", "")) == project_id or str(item.get("pdf_id", "")).strip() in pdf_id_set
    ]
    document_ids = {str(item.get("document_id", "")) for item in documents if str(item.get("document_id", "")).strip()}
    return {
        "documents": documents,
        "pages": [item for item in store.pages.values() if str(item.get("document_id", "")) in document_ids],
        "paragraphs": [item for item in store.paragraphs.values() if str(item.get("document_id", "")) in document_ids],
        "chunk_search_documents": [item for item in store.chunk_search_documents.values() if str(item.get("document_id", "")) in document_ids],
        "chunk_assertions": [item for item in store.chunk_ontology_assertions.values() if str(item.get("document_id", "")) in document_ids],
    }


def _structural_report(snapshot: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    paragraphs = snapshot["paragraphs"]
    missing_offsets = [
        str(row.get("paragraph_id"))
        for row in paragraphs
        if row.get("char_start") is None or row.get("char_end") is None or int(row.get("char_end", 0) or 0) < int(row.get("char_start", 0) or 0)
    ]
    missing_parent = [
        str(row.get("paragraph_id"))
        for row in paragraphs
        if len(row.get("heading_path", [])) > 1 and not row.get("parent_section_id") and str(row.get("chunk_type")) != "heading"
    ]
    page_groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in paragraphs:
        page_groups.setdefault(str(row.get("page_id", "")), []).append(row)
    missing_prev_next: List[str] = []
    for rows in page_groups.values():
        ordered = sorted(rows, key=lambda item: int(item.get("paragraph_index", 0) or 0))
        if len(ordered) <= 1:
            continue
        for idx, row in enumerate(ordered):
            if idx > 0 and not row.get("prev_chunk_id"):
                missing_prev_next.append(str(row.get("paragraph_id")))
            if idx + 1 < len(ordered) and not row.get("next_chunk_id"):
                missing_prev_next.append(str(row.get("paragraph_id")))
    return {
        "report_version": "chunk_processing_full_structural_report_v1",
        "document_count": len(snapshot["documents"]),
        "page_count": len(snapshot["pages"]),
        "chunk_count": len(paragraphs),
        "missing_offsets_count": len(missing_offsets),
        "missing_parent_count": len(missing_parent),
        "missing_prev_next_count": len(missing_prev_next),
        "cross_article_chunk_ids": _cross_article_chunks(snapshot),
        "case_merge_issue_chunk_ids": _case_merge_issues(snapshot),
    }


def _semantic_coverage_report(snapshot: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    projections = snapshot["chunk_search_documents"]
    assertions = snapshot["chunk_assertions"]
    by_doc_type = defaultdict(lambda: {"documents": set(), "chunks": 0, "chunks_with_assertions": 0, "assertions": 0})
    relation_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()
    direct_answer_type_counts: Counter[str] = Counter()
    chunks_with_conditions = 0
    chunks_with_exceptions = 0
    chunks_with_money = 0
    chunks_with_interest = 0
    zero_assertion_doc_ids: List[str] = []

    assertion_count_by_chunk: Dict[str, int] = defaultdict(int)
    for assertion in assertions:
        chunk_id = str(assertion.get("paragraph_id", ""))
        assertion_count_by_chunk[chunk_id] += 1

    for row in projections:
        doc_type = str(row.get("doc_type", "unknown") or "unknown")
        document_id = str(row.get("document_id", ""))
        chunk_id = str(row.get("chunk_id", ""))
        semantic_assertions = row.get("semantic_assertions", []) if isinstance(row.get("semantic_assertions"), list) else []
        by_doc_type[doc_type]["documents"].add(document_id)
        by_doc_type[doc_type]["chunks"] += 1
        if semantic_assertions:
            by_doc_type[doc_type]["chunks_with_assertions"] += 1
        by_doc_type[doc_type]["assertions"] += len(semantic_assertions)
        if not semantic_assertions:
            zero_assertion_doc_ids.append(document_id)
        saw_money = False
        saw_interest = False
        saw_conditions = False
        saw_exceptions = False
        for item in semantic_assertions:
            if not isinstance(item, dict):
                continue
            relation_counts[str(item.get("relation_type", "")).strip().lower()] += 1
            modality_counts[str(item.get("modality", "")).strip().lower()] += 1
            direct_answer = item.get("direct_answer") if isinstance(item.get("direct_answer"), dict) else {}
            answer_type = str(direct_answer.get("answer_type", "")).strip().lower()
            if answer_type and answer_type != "none":
                direct_answer_type_counts[answer_type] += 1
            blob = json.dumps(item, ensure_ascii=False).lower()
            saw_money = saw_money or any(token in blob for token in ("usd", "aed", "eur", "gbp", "dirham"))
            saw_interest = saw_interest or ("interest" in blob and "%" in blob)
            saw_conditions = saw_conditions or bool(item.get("conditions"))
            saw_exceptions = saw_exceptions or bool(item.get("exceptions"))
        if saw_money:
            chunks_with_money += 1
        if saw_interest:
            chunks_with_interest += 1
        if saw_conditions:
            chunks_with_conditions += 1
        if saw_exceptions:
            chunks_with_exceptions += 1

    by_doc_type_payload = {
        key: {
            "document_count": len(value["documents"]),
            "chunk_count": value["chunks"],
            "chunks_with_assertions": value["chunks_with_assertions"],
            "assertion_count": value["assertions"],
            "semantic_chunk_ratio": round(value["chunks_with_assertions"] / max(1, value["chunks"]), 4),
        }
        for key, value in sorted(by_doc_type.items())
    }

    return {
        "report_version": "chunk_processing_full_semantic_coverage_report_v1",
        "document_count": len(snapshot["documents"]),
        "chunk_count": len(projections),
        "assertion_count": len(assertions),
        "chunks_with_assertions_count": sum(1 for row in projections if isinstance(row.get("semantic_assertions"), list) and row.get("semantic_assertions")),
        "chunks_with_conditions_count": chunks_with_conditions,
        "chunks_with_exceptions_count": chunks_with_exceptions,
        "chunks_with_money_count": chunks_with_money,
        "chunks_with_interest_count": chunks_with_interest,
        "relation_type_counts": dict(relation_counts.most_common(20)),
        "modality_counts": dict(modality_counts.most_common(20)),
        "direct_answer_type_counts": dict(direct_answer_type_counts),
        "by_doc_type": by_doc_type_payload,
        "zero_assertion_chunk_count": sum(1 for row in projections if not isinstance(row.get("semantic_assertions"), list) or not row.get("semantic_assertions")),
    }


def _semantic_target_chunk_ids(snapshot: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    documents_by_id = {str(item.get("document_id", "")): item for item in snapshot["documents"]}
    projections_by_chunk = {str(item.get("chunk_id", "")): item for item in snapshot["chunk_search_documents"]}
    out: List[str] = []
    for paragraph in snapshot["paragraphs"]:
        paragraph_id = str(paragraph.get("paragraph_id", "")).strip()
        if not paragraph_id:
            continue
        projection = projections_by_chunk.get(paragraph_id, {})
        document = documents_by_id.get(str(paragraph.get("document_id", "")), {})
        doc_type = str(document.get("doc_type", projection.get("doc_type", "")) or "").strip().lower()
        if _is_semantically_rich_chunk(doc_type, paragraph, projection):
            out.append(paragraph_id)
    return out


def _write_progress(output_dir: Path, stage: str, **extra: Any) -> None:
    payload = {"stage": stage, **extra}
    _write_json(output_dir / "run_progress.json", payload)
    print(f"[chunk_full_eval] {stage}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rules-first chunk/proposition evaluation on the full corpus")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    args = parser.parse_args()

    _prepare_env()
    # Full chunk evaluation should measure the chunk/proposition layer, not spend
    # time repeating document-level metadata normalization.
    os.environ["CORPUS_METADATA_NORMALIZER_PROVIDER"] = "openai"
    os.environ["CORPUS_METADATA_NORMALIZER_MODEL"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    fixture = _load_json(FIXTURE_PATH)
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utcnow()
    prepare_result = corpus_router.import_zip(
        {
            "project_id": str(args.project_id),
            "blob_url": str(SOURCE_ZIP_PATH.resolve()),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        }
    )
    completed_at = _utcnow()
    prepare_report = {
        "command": "prepare",
        "started_at_utc": _iso(started_at),
        "completed_at_utc": _iso(completed_at),
        "documents_path": str(SOURCE_ZIP_PATH.resolve()),
        "project_id": str(args.project_id),
        "result": prepare_result,
        "code_version": _git_metadata(),
    }
    _write_json(output_dir / "prepare_report.chunk_processing_full_corpus_eval_v1.json", prepare_report)
    _write_progress(output_dir, "prepare_complete")

    imported_pdf_ids = [
        str(item.get("pdf_id", "")).strip()
        for item in (((prepare_result.get("ingest_diagnostics") or {}).get("documents")) or [])
        if str(item.get("pdf_id", "")).strip()
    ]

    snapshot = _project_snapshot(str(args.project_id), pdf_ids=imported_pdf_ids)
    os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = "1"
    target_chunk_ids = _semantic_target_chunk_ids(snapshot)
    _write_progress(
        output_dir,
        "target_chunks_selected",
        target_chunk_count=len(target_chunk_ids),
        total_chunk_count=len(snapshot["paragraphs"]),
    )
    enrichment = retry_agentic_corpus_enrichment(
        project_id=str(args.project_id),
        import_job_id=str((prepare_result.get("enrichment_job") or {}).get("import_job_id") or prepare_result.get("job_id") or "chunk_processing_full_corpus_eval"),
        documents=snapshot["documents"],
        pages=snapshot["pages"],
        paragraphs=snapshot["paragraphs"],
        chunk_search_documents=snapshot["chunk_search_documents"],
        relation_edges=list(store.relation_edges.values()),
        existing_registry_entries=list(store.ontology_registry_entries.values()),
        target_type="chunk",
        target_ids=target_chunk_ids,
    )
    _apply_enrichment_result(str(args.project_id), enrichment)
    _write_progress(output_dir, "chunk_enrichment_complete")

    snapshot = _project_snapshot(str(args.project_id), pdf_ids=imported_pdf_ids)
    structural = _structural_report(snapshot)
    semantic = _semantic_coverage_report(snapshot)
    provenance = _provenance_report(snapshot, [])
    _write_progress(output_dir, "coverage_reports_complete")

    expanded_query_responses = asyncio.run(
        _run_query_batch(str(args.project_id), fixture.get("expanded_queries", []), dataset_id="chunk_processing_full_corpus_frozen_set_v1")
    )
    expanded_queries = _expanded_frozen_query_report(fixture, expanded_query_responses)
    real_corpus_checks = _run_real_corpus_checks(fixture=fixture, pilot_project_id=str(args.project_id), output_dir=output_dir)
    _write_progress(output_dir, "query_reports_complete", expanded_query_count=len(expanded_query_responses))

    results_export = {
        "export_version": "chunk_processing_full_corpus_results_export_v1",
        "program_label": "rules-first chunk/proposition full-corpus evaluation",
        "prepare_report": {
            "status": ((prepare_report.get("result") or {}).get("metadata_normalization_job") or {}).get("status"),
            "project_id": prepare_report.get("project_id"),
            "documents_path": prepare_report.get("documents_path"),
        },
        "structural": structural,
        "semantic_coverage": semantic,
        "expanded_frozen_queries": {
            "query_count": expanded_queries.get("query_count"),
            "pass_ratio": expanded_queries.get("pass_ratio"),
            "route_match_ratio": expanded_queries.get("route_match_ratio"),
            "known_source_top3_hit_ratio": expanded_queries.get("known_source_top3_hit_ratio"),
            "category_counts": expanded_queries.get("category_counts", {}),
        },
        "real_corpus_checks": {
            "fixture_count": real_corpus_checks.get("fixture_count"),
            "pass_ratio": real_corpus_checks.get("pass_ratio"),
        },
        "provenance": {
            "document_field_missing_count": provenance.get("document_field_missing_count"),
            "assertion_missing_count": provenance.get("assertion_missing_count"),
            "projection_missing_count": provenance.get("projection_missing_count"),
            "direct_answer_missing_count": provenance.get("direct_answer_missing_count"),
        },
    }

    _write_json(output_dir / "structural_chunk_quality_report.json", structural)
    _write_md(output_dir / "structural_chunk_quality_report.md", _markdown_from_mapping("Full Corpus Structural Chunk Quality Report", structural))
    _write_json(output_dir / "semantic_coverage_report.json", semantic)
    _write_md(output_dir / "semantic_coverage_report.md", _markdown_from_mapping("Full Corpus Semantic Coverage Report", semantic))
    _write_json(output_dir / "provenance_coverage_report.json", provenance)
    _write_md(output_dir / "provenance_coverage_report.md", _markdown_from_mapping("Full Corpus Provenance Coverage Report", provenance))
    _write_json(output_dir / "expanded_frozen_query_report.json", expanded_queries)
    _write_md(output_dir / "expanded_frozen_query_report.md", _markdown_from_mapping("Full Corpus Expanded Frozen Query Report", expanded_queries))
    _write_json(output_dir / "expanded_query_responses.json", {"items": expanded_query_responses})
    _write_json(output_dir / "real_corpus_fixture_report.json", real_corpus_checks)
    _write_md(output_dir / "real_corpus_fixture_report.md", _markdown_from_mapping("Full Corpus Real Corpus Fixture Report", real_corpus_checks))
    _write_json(output_dir / "processing_results_export.json", results_export)
    _write_md(output_dir / "processing_results_export.md", _markdown_from_mapping("Full Corpus Processing Results Export", results_export))
    _write_progress(output_dir, "completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
