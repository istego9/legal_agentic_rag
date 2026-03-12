#!/usr/bin/env python3
"""Run the 5-document chunk-processing pilot and emit quality reports."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile
from typing import Any, Dict, List
import re

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
import sys

if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import Question, QueryRequest, RuntimePolicy  # noqa: E402
from legal_rag_api.artifacts import artifact_path  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.routers import qa as qa_router  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from scripts.competition_batch import _git_metadata  # noqa: E402
from services.ingest.agentic_enrichment import retry_agentic_corpus_enrichment  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "chunk_processing_pilot_v1.json"
SOURCE_ZIP_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "documents.zip"
DEFAULT_OUTPUT_DIR = artifact_path("competition_runs", "pilots", "chunk_processing_pilot_v1")
DEFAULT_PROJECT_ID = "competition_chunk_processing_pilot_v1"
DEFAULT_AUDIT_EXPORT_DIR = artifact_path("corpus_investigation", "2026-03-12-version-lineage-rca", "chunk_processing_external_audit_export")
ARTICLE_HEADING_PATTERN = re.compile(r"(?<!\()(?<!\.)\b(\d{1,3})\.\s+[A-Z]")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in {"DATABASE_URL", "COMPETITION_MODE"}:
            continue
        if key not in os.environ:
            os.environ[key] = value.strip()


def _prepare_env() -> None:
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("COMPETITION_MODE", None)
    _load_env_file(ROOT / "infra" / "docker" / ".env")
    os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = "0"
    os.environ.setdefault("CHUNK_SEMANTICS_DEPLOYMENT", os.environ.get("CORPUS_METADATA_NORMALIZER_DEPLOYMENT", "wf-gpt5mini-metadata"))
    os.environ.setdefault("CHUNK_SEMANTICS_API_MODE", os.environ.get("CORPUS_METADATA_NORMALIZER_API_MODE", "responses"))
    os.environ.setdefault("CHUNK_SEMANTICS_TIMEOUT_SECONDS", os.environ.get("CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS", "30"))
    os.environ.setdefault("CHUNK_SEMANTICS_TOKEN_PARAMETER", os.environ.get("CORPUS_METADATA_NORMALIZER_TOKEN_PARAMETER", "max_output_tokens"))
    os.environ.setdefault("CHUNK_SEMANTICS_REASONING_EFFORT", os.environ.get("CORPUS_METADATA_NORMALIZER_REASONING_EFFORT", "minimal"))
    os.environ.setdefault("CHUNK_SEMANTICS_VERBOSITY", os.environ.get("CORPUS_METADATA_NORMALIZER_VERBOSITY", "low"))


def _build_subset_zip(*, fixture: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_ids = {f"{item['pdf_id']}.pdf" for item in fixture.get("documents", []) if str(item.get("pdf_id", "")).strip()}
    with zipfile.ZipFile(SOURCE_ZIP_PATH) as src, zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
        for name in src.namelist():
            if name in pdf_ids:
                dst.writestr(name, src.read(name))
    return output_path


def _project_snapshot(project_id: str, fixture: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    pilot_pdf_ids = {str(item.get("pdf_id", "")) for item in fixture.get("documents", []) if str(item.get("pdf_id", "")).strip()}
    documents = [
        item
        for item in store.documents.values()
        if str(item.get("project_id", "")) == project_id or str(item.get("pdf_id", "")) in pilot_pdf_ids
    ]
    document_ids = {str(item.get("document_id")) for item in documents}
    return {
        "documents": documents,
        "pages": [item for item in store.pages.values() if str(item.get("document_id", "")) in document_ids],
        "paragraphs": [item for item in store.paragraphs.values() if str(item.get("document_id", "")) in document_ids],
        "chunk_search_documents": [item for item in store.chunk_search_documents.values() if str(item.get("document_id", "")) in document_ids],
        "chunk_assertions": [item for item in store.chunk_ontology_assertions.values() if str(item.get("document_id", "")) in document_ids],
    }


def _apply_enrichment_result(project_id: str, enrichment: Dict[str, Any]) -> None:
    for document in enrichment.get("updated_documents", {}).values():
        if str(document.get("project_id", "")) == project_id:
            store.documents[str(document.get("document_id"))] = document
    for paragraph in enrichment.get("updated_paragraphs", {}).values():
        store.paragraphs[str(paragraph.get("paragraph_id"))] = paragraph
    for projection in enrichment.get("updated_chunk_projections", {}).values():
        store.chunk_search_documents[str(projection.get("chunk_id"))] = projection
    for edge in enrichment.get("projected_relation_edges", []):
        store.relation_edges[str(edge.get("edge_id"))] = edge
    for row in enrichment.get("registry_entries", []):
        store.ontology_registry_entries[str(row.get("entry_id"))] = row
    for row in enrichment.get("chunk_assertions", []):
        store.chunk_ontology_assertions[str(row.get("assertion_id"))] = row
    for row in enrichment.get("document_views", []):
        store.document_ontology_views[str(row.get("document_id"))] = row
    job = enrichment.get("job")
    if isinstance(job, dict):
        store.corpus_enrichment_jobs[str(job.get("job_id"))] = job


def _target_chunk_ids(snapshot: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    projections = list(snapshot["chunk_search_documents"])
    out: List[str] = []
    pilot_case_pdf_ids = {
        "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13",
        "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26",
    }

    def _add(predicate, limit: int) -> None:
        count = 0
        for row in projections:
            if predicate(row):
                out.append(str(row.get("chunk_id")))
                count += 1
                if count >= limit:
                    break

    _add(
        lambda row: str(row.get("pdf_id", "")) == "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16"
        and str(row.get("article_number", "")) == "11",
        2,
    )
    _add(
        lambda row: str(row.get("pdf_id", "")) == "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16"
        and str(row.get("article_number", "")) == "11"
        and ("precludes" in str(row.get("text_clean", "")).lower() or "void in all circumstances" in str(row.get("text_clean", "")).lower()),
        1,
    )
    _add(
        lambda row: str(row.get("pdf_id", "")) == "4e387152960c1029b3711cacb05b287b13c977bc61f2558059a62b7b427a62eb"
        and bool(str(row.get("article_number", ""))),
        1,
    )
    _add(
        lambda row: str(row.get("pdf_id", "")) == "fbdd7f9dd299d83b1f398778da2e6765dfaaed62005667264734a1f76ec09071"
        and bool(str(row.get("article_number", ""))),
        1,
    )
    _add(
        lambda row: str(row.get("pdf_id", "")) in pilot_case_pdf_ids
        and str(row.get("doc_type", "")) == "case"
        and str(row.get("section_kind_case", "")).lower() in {"parties", "procedural_history", "reasoning", "order", "disposition"},
        200,
    )
    seen = set()
    return [item for item in out if item and not (item in seen or seen.add(item))]


def _cross_article_chunks(snapshot: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    out: List[str] = []
    for row in snapshot["chunk_search_documents"]:
        if str(row.get("doc_type", "")) != "law":
            continue
        article_number = str(row.get("article_number", "")).strip()
        text = str(row.get("text_clean", ""))
        if not article_number:
            continue
        for match in ARTICLE_HEADING_PATTERN.finditer(text):
            candidate = str(match.group(1))
            if candidate != article_number and match.start() > 40:
                out.append(str(row.get("chunk_id")))
                break
    return sorted(set(out))


def _case_merge_issues(snapshot: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    out: List[str] = []
    for row in snapshot["chunk_search_documents"]:
        if str(row.get("doc_type", "")) != "case":
            continue
        text = str(row.get("text_clean", ""))
        section_kind_case = str(row.get("section_kind_case", "")).strip().lower()
        if section_kind_case in {"parties", "procedural_history"} and ("IT IS HEREBY ORDERED" in text or "SCHEDULE OF REASONS" in text):
            out.append(str(row.get("chunk_id")))
    return sorted(set(out))


def _structural_report(snapshot: Dict[str, List[Dict[str, Any]]], fixture: Dict[str, Any]) -> Dict[str, Any]:
    projections = {str(row.get("chunk_id")): row for row in snapshot["chunk_search_documents"]}
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
        "report_version": "chunk_processing_structural_report_v1",
        "project_id": DEFAULT_PROJECT_ID,
        "document_count": len(snapshot["documents"]),
        "chunk_count": len(paragraphs),
        "missing_offsets_count": len(missing_offsets),
        "missing_offsets": missing_offsets,
        "missing_parent_count": len(missing_parent),
        "missing_parent": missing_parent,
        "missing_prev_next_count": len(missing_prev_next),
        "missing_prev_next": missing_prev_next,
        "cross_article_chunk_ids": _cross_article_chunks(snapshot),
        "case_merge_issue_chunk_ids": _case_merge_issues(snapshot),
        "fixture_documents": fixture.get("documents", []),
    }


def _semantic_report(snapshot: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    assertions = snapshot["chunk_assertions"]
    projections = {str(row.get("chunk_id")): row for row in snapshot["chunk_search_documents"]}

    def _find_projection(pdf_id: str, *, article_number: str | None = None, text_terms: List[str] | None = None) -> Dict[str, Any]:
        matches = []
        for row in snapshot["chunk_search_documents"]:
            if str(row.get("pdf_id", "")) != pdf_id:
                continue
            if article_number and str(row.get("article_number", "")) != article_number:
                continue
            text_blob = json.dumps(row, ensure_ascii=False).lower()
            if text_terms and not all(term.lower() in text_blob for term in text_terms):
                continue
            matches.append(row)
        if not matches:
            return {}
        matches.sort(key=lambda row: (int(row.get("semantic_assertion_count", 0) or 0), len(str(row.get("text_clean", "")))), reverse=True)
        return matches[0]

    employment = _find_projection(
        "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16",
        article_number="11",
        text_terms=["waive"],
    )
    coinmena = _find_projection(
        "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13",
        text_terms=["interest"],
    )
    ca004 = _find_projection(
        "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26",
        text_terms=["interest"],
    )

    employment_assertions = employment.get("semantic_assertions", []) if isinstance(employment.get("semantic_assertions"), list) else []
    coinmena_assertions = coinmena.get("semantic_assertions", []) if isinstance(coinmena.get("semantic_assertions"), list) else []
    ca004_assertions = ca004.get("semantic_assertions", []) if isinstance(ca004.get("semantic_assertions"), list) else []

    return {
        "report_version": "chunk_processing_semantic_report_v1",
        "assertion_count": len(assertions),
        "chunk_with_assertions_count": sum(1 for row in snapshot["chunk_search_documents"] if int(row.get("semantic_assertion_count", 0) or 0) > 0),
        "employment_article_11": {
            "chunk_id": employment.get("chunk_id"),
            "assertion_count": len(employment_assertions),
            "has_void_assertion": any(str(item.get("relation_type", "")) == "is_void" or "void" in str(item.get("object_text", "")).lower() for item in employment_assertions),
            "has_more_favourable_permission": any("more favourable" in str(item.get("object_text", "")).lower() for item in employment_assertions),
            "has_employee_waive_permission": any("employee" in str(item.get("subject_text", "")).lower() and "waive" in str(item.get("relation_type", "")).lower() or ("employee" in str(item.get("subject_text", "")).lower() and "rights" in str(item.get("object_text", "")).lower() and str(item.get("modality", "")) == "permission") for item in employment_assertions),
            "has_condition_preserved": any("legal advice" in str(item.get("condition_text", "")).lower() or "mediation" in str(item.get("condition_text", "")).lower() for item in employment_assertions),
        },
        "coinmena_order": {
            "chunk_id": coinmena.get("chunk_id"),
            "assertion_count": len(coinmena_assertions),
            "has_amount": any("155,879.50" in json.dumps(item, ensure_ascii=False) for item in coinmena_assertions),
            "has_deadline": any("14" in json.dumps(item, ensure_ascii=False) and "day" in json.dumps(item, ensure_ascii=False).lower() for item in coinmena_assertions),
            "has_interest": any("9%" in json.dumps(item, ensure_ascii=False) or "interest" in json.dumps(item, ensure_ascii=False).lower() for item in coinmena_assertions),
        },
        "ca004_order": {
            "chunk_id": ca004.get("chunk_id"),
            "assertion_count": len(ca004_assertions),
            "has_amount": any("720,000" in json.dumps(item, ensure_ascii=False) for item in ca004_assertions),
            "has_interest": any("9%" in json.dumps(item, ensure_ascii=False) or "interest" in json.dumps(item, ensure_ascii=False).lower() for item in ca004_assertions),
        },
        "semantic_dense_summary_count": sum(1 for row in projections.values() if str(row.get("semantic_dense_summary", "")).strip()),
    }


async def _run_queries(project_id: str, fixture: Dict[str, Any]) -> List[Dict[str, Any]]:
    policy = RuntimePolicy(
        use_llm=False,
        max_candidate_pages=8,
        max_context_paragraphs=8,
        page_index_base_export=0,
        scoring_policy_version="contest_v2026_public_rules_v1",
        allow_dense_fallback=False,
        return_debug_trace=True,
    )
    results: List[Dict[str, Any]] = []
    for query in fixture.get("queries", []):
        request = QueryRequest(
            project_id=project_id,
            question=Question(
                id=str(query["question_id"]),
                question=str(query["question"]),
                answer_type=str(query["answer_type"]),
                route_hint=query.get("route_hint"),
                source="manual",
                difficulty="easy",
                dataset_id="chunk_processing_pilot_v1",
            ),
            runtime_policy=policy,
        )
        response = await qa_router.ask(request)
        results.append(response.model_dump(mode="json"))
    return results


def _retrieval_report(fixture: Dict[str, Any], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    queries = {str(item["question_id"]): item for item in fixture.get("queries", [])}
    rows: List[Dict[str, Any]] = []
    success_top3 = 0
    for response in responses:
        qid = str(response.get("question_id", ""))
        expected = queries[qid]
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        retrieval_trace = debug.get("retrieval_stage_trace", {}) if isinstance(debug.get("retrieval_stage_trace"), dict) else {}
        top_candidates = retrieval_trace.get("top_candidates", []) if isinstance(retrieval_trace.get("top_candidates"), list) else []
        top3_contains_expected = any(
            str(item.get("source_page_id", "")).startswith(str(expected.get("expected_pdf_id", "")))
            for item in top_candidates[:3]
        )
        success_top3 += 1 if top3_contains_expected else 0
        rows.append(
            {
                "question_id": qid,
                "answer": response.get("answer"),
                "abstained": response.get("abstained"),
                "route_name": response.get("route_name"),
                "top3_contains_expected": top3_contains_expected,
                "used_source_page_ids": [item.get("source_page_id") for item in debug.get("used_pages", [])] if isinstance(debug.get("used_pages"), list) else [],
                "top_candidates": top_candidates[:3],
            }
        )
    return {
        "report_version": "chunk_processing_retrieval_report_v1",
        "query_count": len(rows),
        "top3_expected_hit_count": success_top3,
        "top3_expected_hit_ratio": round(success_top3 / max(1, len(rows)), 4),
        "items": rows,
    }


def _direct_answer_report(fixture: Dict[str, Any], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    queries = {str(item["question_id"]): item for item in fixture.get("queries", [])}
    rows: List[Dict[str, Any]] = []
    used_count = 0
    correct_count = 0
    for response in responses:
        qid = str(response.get("question_id", ""))
        expected = queries[qid]
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        solver_trace = debug.get("solver_trace", {}) if isinstance(debug.get("solver_trace"), dict) else {}
        used = str(solver_trace.get("solver_version", "")) == "proposition_direct_answer_v1"
        if used:
            used_count += 1
        answer = response.get("answer")
        expected_answer = expected.get("expected_answer")
        correct = answer == expected_answer
        if isinstance(answer, (int, float)) and isinstance(expected_answer, (int, float)):
            correct = abs(float(answer) - float(expected_answer)) < 0.01
        if used and correct:
            correct_count += 1
        rows.append(
            {
                "question_id": qid,
                "used_direct_answer": used,
                "solver_path": solver_trace.get("path"),
                "answer": answer,
                "expected_answer": expected_answer,
                "correct": correct,
                "abstained": response.get("abstained"),
            }
        )
    return {
        "report_version": "chunk_processing_direct_answer_report_v1",
        "query_count": len(rows),
        "direct_answer_used_count": used_count,
        "direct_answer_correct_count": correct_count,
        "direct_answer_correct_ratio": round(correct_count / max(1, used_count), 4) if used_count else 0.0,
        "items": rows,
    }


def _provenance_report(snapshot: Dict[str, List[Dict[str, Any]]], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    missing_document_fields: List[Dict[str, Any]] = []
    for document in snapshot["documents"]:
        processing = document.get("processing") if isinstance(document.get("processing"), dict) else {}
        normalization = processing.get("metadata_normalization") if isinstance(processing.get("metadata_normalization"), dict) else {}
        field_evidence = normalization.get("field_evidence") if isinstance(normalization.get("field_evidence"), dict) else {}
        for section_name in ("canonical_document", "type_specific_document", "processing_candidates", "court_normalization"):
            section = normalization.get(section_name)
            if not isinstance(section, dict):
                continue
            for field_name, value in section.items():
                if not _has_value(value):
                    continue
                evidence = field_evidence.get(field_name) if isinstance(field_evidence.get(field_name), dict) else {}
                if not isinstance(evidence.get("source_page_ids"), list) or not any(str(item).strip() for item in evidence.get("source_page_ids", [])):
                    missing_document_fields.append(
                        {
                            "document_id": str(document.get("document_id")),
                            "pdf_id": str(document.get("pdf_id")),
                            "section": section_name,
                            "field_name": field_name,
                            "value": value,
                        }
                    )

    missing_assertion_provenance: List[Dict[str, Any]] = []
    for assertion in snapshot["chunk_assertions"]:
        properties = assertion.get("properties") if isinstance(assertion.get("properties"), dict) else {}
        evidence = properties.get("evidence") if isinstance(properties.get("evidence"), dict) else {}
        if not isinstance(evidence.get("source_page_ids"), list) or not any(str(item).strip() for item in evidence.get("source_page_ids", [])):
            missing_assertion_provenance.append(
                {
                    "assertion_id": str(assertion.get("assertion_id")),
                    "paragraph_id": str(assertion.get("paragraph_id")),
                    "source_page_id": assertion.get("source_page_id"),
                }
            )
            continue
        if evidence.get("char_start") is None or evidence.get("char_end") is None:
            missing_assertion_provenance.append(
                {
                    "assertion_id": str(assertion.get("assertion_id")),
                    "paragraph_id": str(assertion.get("paragraph_id")),
                    "issue": "missing_offsets",
                }
            )

    missing_projection_provenance: List[Dict[str, Any]] = []
    for projection in snapshot["chunk_search_documents"]:
        assertions = projection.get("semantic_assertions")
        if not isinstance(assertions, list):
            continue
        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            evidence = assertion.get("evidence") if isinstance(assertion.get("evidence"), dict) else {}
            if not isinstance(evidence.get("source_page_ids"), list) or not any(str(item).strip() for item in evidence.get("source_page_ids", [])):
                missing_projection_provenance.append(
                    {
                        "chunk_id": str(projection.get("chunk_id")),
                        "assertion_id": str(assertion.get("assertion_id")),
                    }
                )

    direct_answer_missing_provenance: List[Dict[str, Any]] = []
    for response in responses:
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        solver_trace = debug.get("solver_trace") if isinstance(debug.get("solver_trace"), dict) else {}
        if str(solver_trace.get("solver_version", "")) != "proposition_direct_answer_v1":
            continue
        top = solver_trace.get("top_proposition") if isinstance(solver_trace.get("top_proposition"), dict) else {}
        evidence = top.get("evidence") if isinstance(top.get("evidence"), dict) else {}
        if not isinstance(evidence.get("source_page_ids"), list) or not any(str(item).strip() for item in evidence.get("source_page_ids", [])):
            direct_answer_missing_provenance.append(
                {
                    "question_id": str(response.get("question_id")),
                    "answer": response.get("answer"),
                }
            )

    return {
        "report_version": "chunk_processing_provenance_report_v1",
        "document_count": len(snapshot["documents"]),
        "chunk_count": len(snapshot["paragraphs"]),
        "document_field_missing_count": len(missing_document_fields),
        "document_field_missing": missing_document_fields,
        "assertion_missing_count": len(missing_assertion_provenance),
        "assertion_missing": missing_assertion_provenance,
        "projection_missing_count": len(missing_projection_provenance),
        "projection_missing": missing_projection_provenance,
        "direct_answer_missing_count": len(direct_answer_missing_provenance),
        "direct_answer_missing": direct_answer_missing_provenance,
    }


def _processing_rules_export(fixture: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "export_version": "chunk_processing_rules_export_v1",
        "pilot_scope": {
            "document_count": len(fixture.get("documents", [])),
            "documents": fixture.get("documents", []),
        },
        "structural_chunking": {
            "laws": ["part", "chapter", "section", "article", "schedule item"],
            "cases": ["caption", "heading", "reasoning paragraphs", "order", "disposition/costs/timing"],
            "page_grounding_invariant": "page remains canonical source unit",
        },
        "ownership": {
            "deterministic": [
                "ids",
                "page references",
                "structural anchors",
                "offsets",
                "lexical refs",
                "document field provenance",
                "assertion provenance",
            ],
            "llm": [
                "semantic provision kind",
                "atomic propositions",
                "negation/conditions/exceptions",
                "dense semantic summary",
            ],
        },
        "retrieval": {
            "stages": [
                "deterministic query parse",
                "structural filter narrowing",
                "hybrid chunk ranking",
                "proposition reranking",
                "local context expansion",
                "direct answer only when grounded proposition dominates",
            ],
            "direct_answer_requires": [
                "single dominant proposition",
                "explicit citation support",
                "no competing conflict",
                "page-grounded provenance",
            ],
        },
        "auditability": {
            "document_fields_require_field_evidence": True,
            "assertions_require_page_provenance": True,
            "proposition_projection_requires_traceback": True,
        },
    }


def _processing_results_export(
    *,
    prepare_report: Dict[str, Any],
    structural: Dict[str, Any],
    semantic: Dict[str, Any],
    retrieval: Dict[str, Any],
    direct_answer: Dict[str, Any],
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "export_version": "chunk_processing_results_export_v1",
        "prepare_report": {
            "status": ((prepare_report.get("result") or {}).get("metadata_normalization_job") or {}).get("status"),
            "project_id": prepare_report.get("project_id"),
            "documents_path": prepare_report.get("documents_path"),
        },
        "structural": {
            "chunk_count": structural.get("chunk_count"),
            "missing_offsets_count": structural.get("missing_offsets_count"),
            "missing_parent_count": structural.get("missing_parent_count"),
            "missing_prev_next_count": structural.get("missing_prev_next_count"),
            "cross_article_chunk_ids": structural.get("cross_article_chunk_ids", []),
            "case_merge_issue_chunk_ids": structural.get("case_merge_issue_chunk_ids", []),
        },
        "semantic": semantic,
        "retrieval": {
            "query_count": retrieval.get("query_count"),
            "top3_expected_hit_ratio": retrieval.get("top3_expected_hit_ratio"),
        },
        "direct_answer": {
            "direct_answer_used_count": direct_answer.get("direct_answer_used_count"),
            "direct_answer_correct_count": direct_answer.get("direct_answer_correct_count"),
            "direct_answer_correct_ratio": direct_answer.get("direct_answer_correct_ratio"),
        },
        "provenance": {
            "document_field_missing_count": provenance.get("document_field_missing_count"),
            "assertion_missing_count": provenance.get("assertion_missing_count"),
            "projection_missing_count": provenance.get("projection_missing_count"),
            "direct_answer_missing_count": provenance.get("direct_answer_missing_count"),
        },
    }


def _copy_file(src: Path, dest_root: Path, rel_path: str) -> Path:
    dest = dest_root / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _build_chunk_audit_bundle(
    *,
    output_dir: Path,
    prepare_report: Dict[str, Any],
    rules_export: Dict[str, Any],
    results_export: Dict[str, Any],
) -> Dict[str, Any]:
    bundle_root = DEFAULT_AUDIT_EXPORT_DIR
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    included: List[Dict[str, Any]] = []

    def _add(src: Path, rel_path: str) -> None:
        copied = _copy_file(src, bundle_root, rel_path)
        included.append({"path": rel_path, "sha256": _sha256(copied), "size_bytes": copied.stat().st_size})

    rules_json = bundle_root / "processing_rules_export.json"
    _write_json(rules_json, rules_export)
    included.append({"path": "processing_rules_export.json", "sha256": _sha256(rules_json), "size_bytes": rules_json.stat().st_size})
    rules_md = bundle_root / "processing_rules_export.md"
    _write_md(rules_md, _markdown_from_mapping("Chunk Processing Rules Export", rules_export))
    included.append({"path": "processing_rules_export.md", "sha256": _sha256(rules_md), "size_bytes": rules_md.stat().st_size})

    results_json = bundle_root / "processing_results_export.json"
    _write_json(results_json, results_export)
    included.append({"path": "processing_results_export.json", "sha256": _sha256(results_json), "size_bytes": results_json.stat().st_size})
    results_md = bundle_root / "processing_results_export.md"
    _write_md(results_md, _markdown_from_mapping("Chunk Processing Results Export", results_export))
    included.append({"path": "processing_results_export.md", "sha256": _sha256(results_md), "size_bytes": results_md.stat().st_size})

    readme = bundle_root / "README.md"
    _write_md(
        readme,
        "\n".join(
            [
                "# Chunk Processing External Audit Export",
                "",
                "This bundle is a self-contained external-audit package for the 5-document chunk-processing pilot.",
                "",
                "Included:",
                "- original full source archive and the 5-document pilot subset",
                "- pilot prepare report and all chunk quality reports",
                "- processing rules and processing results exports",
                "- active execution plan and strategy note",
                "- prompt files used for chunk semantics",
                "- implementation snapshot for chunk processing, enrichment, provenance, and runtime proposition retrieval",
                "- contract tests and pilot fixture",
                "",
                "Primary outcomes:",
                f"- retrieval top-3 expected hit ratio `{results_export['retrieval']['top3_expected_hit_ratio']}`",
                f"- document field provenance missing `{results_export['provenance']['document_field_missing_count']}`",
                f"- assertion provenance missing `{results_export['provenance']['assertion_missing_count']}`",
                f"- projection provenance missing `{results_export['provenance']['projection_missing_count']}`",
            ]
        )
        + "\n",
    )
    included.append({"path": "README.md", "sha256": _sha256(readme), "size_bytes": readme.stat().st_size})

    _add(SOURCE_ZIP_PATH, "datasets/official_fetch_2026-03-11/documents.zip")
    for artifact in sorted(output_dir.glob("*")):
        if artifact.is_file():
            _add(artifact, f"pilot/{artifact.name}")

    for rel_path in (
        "docs/exec-plans/active/2026-03-12-chunk-processing-and-proposition-layer.md",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_layer_strategy_and_llm_pilot.md",
        "packages/prompts/law_chunk_semantics_v1.md",
        "packages/prompts/case_chunk_semantics_v1.md",
        "packages/prompts/corpus_law_title_identity_v2.md",
        "packages/prompts/corpus_case_title_identity_v2.md",
        "services/ingest/chunk_processing.py",
        "services/ingest/chunk_semantics.py",
        "services/ingest/agentic_enrichment.py",
        "services/ingest/corpus_metadata_normalizer.py",
        "services/ingest/ingest.py",
        "services/runtime/proposition_layer.py",
        "apps/api/src/legal_rag_api/routers/qa.py",
        "tests/contracts/test_chunk_processing.py",
        "tests/contracts/test_chunk_semantics_contracts.py",
        "tests/contracts/test_agentic_enrichment.py",
        "tests/contracts/test_proposition_layer.py",
        "tests/contracts/test_corpus_metadata_normalizer.py",
        "tests/fixtures/chunk_processing_pilot_v1.json",
    ):
        path = ROOT / rel_path
        if path.exists():
            _add(path, rel_path)

    manifest = {
        "bundle_version": "chunk_processing_external_audit_export_v1",
        "generated_at_utc": _iso(_utcnow()),
        "items": sorted(included, key=lambda item: item["path"]),
    }
    manifest_path = bundle_root / "bundle_manifest.json"
    _write_json(manifest_path, manifest)
    zip_path = bundle_root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in manifest["items"] + [{"path": "bundle_manifest.json"}]:
            rel_path = item["path"]
            archive.write(bundle_root / rel_path, arcname=rel_path)
    sha_path = bundle_root / "chunk_processing_external_audit_export.sha256.txt"
    sha_path.write_text(f"{_sha256(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    return {
        "bundle_root": str(bundle_root),
        "zip_path": str(zip_path),
        "sha256": _sha256(zip_path),
    }


def _markdown_from_mapping(title: str, payload: Dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.append(f"## {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        else:
            lines.append(f"- {key}: `{value}`")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chunk-processing pilot on five documents")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    args = parser.parse_args()

    _prepare_env()
    fixture = _load_json(FIXTURE_PATH)
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subset_zip_path = output_dir / "chunk_processing_pilot_documents.zip"
    _build_subset_zip(fixture=fixture, output_path=subset_zip_path)

    started_at = _utcnow()
    prepare_result = corpus_router.import_zip(
        {
            "project_id": str(args.project_id),
            "blob_url": str(subset_zip_path.resolve()),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        }
    )
    completed_at = _utcnow()
    prepare_report = {
        "command": "prepare",
        "started_at_utc": _iso(started_at),
        "completed_at_utc": _iso(completed_at),
        "documents_path": str(subset_zip_path.resolve()),
        "project_id": str(args.project_id),
        "result": prepare_result,
        "code_version": _git_metadata(),
    }
    _write_json(output_dir / "prepare_report.chunk_processing_pilot_v1.json", prepare_report)
    _write_json(output_dir / "pilot_fixture.chunk_processing_pilot_v1.json", fixture)

    snapshot = _project_snapshot(str(args.project_id), fixture)
    os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = "1"
    target_chunk_ids = _target_chunk_ids(snapshot)
    enrichment = retry_agentic_corpus_enrichment(
        project_id=str(args.project_id),
        import_job_id=str((prepare_result.get("enrichment_job") or {}).get("import_job_id") or prepare_result.get("job_id") or "chunk_processing_pilot"),
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
    snapshot = _project_snapshot(str(args.project_id), fixture)
    structural = _structural_report(snapshot, fixture)
    semantic = _semantic_report(snapshot)
    responses = asyncio.run(_run_queries(str(args.project_id), fixture))
    retrieval = _retrieval_report(fixture, responses)
    direct_answer = _direct_answer_report(fixture, responses)
    provenance = _provenance_report(snapshot, responses)
    rules_export = _processing_rules_export(fixture)
    results_export = _processing_results_export(
        prepare_report=prepare_report,
        structural=structural,
        semantic=semantic,
        retrieval=retrieval,
        direct_answer=direct_answer,
        provenance=provenance,
    )

    _write_json(output_dir / "structural_chunk_quality_report.json", structural)
    _write_md(output_dir / "structural_chunk_quality_report.md", _markdown_from_mapping("Structural Chunk Quality Report", structural))
    _write_json(output_dir / "semantic_assertion_quality_report.json", semantic)
    _write_md(output_dir / "semantic_assertion_quality_report.md", _markdown_from_mapping("Semantic Assertion Quality Report", semantic))
    _write_json(output_dir / "retrieval_quality_report.json", retrieval)
    _write_md(output_dir / "retrieval_quality_report.md", _markdown_from_mapping("Retrieval Quality Report", retrieval))
    _write_json(output_dir / "direct_answer_report.json", direct_answer)
    _write_md(output_dir / "direct_answer_report.md", _markdown_from_mapping("Direct Answer Report", direct_answer))
    _write_json(output_dir / "provenance_coverage_report.json", provenance)
    _write_md(output_dir / "provenance_coverage_report.md", _markdown_from_mapping("Provenance Coverage Report", provenance))
    _write_json(output_dir / "processing_rules_export.json", rules_export)
    _write_md(output_dir / "processing_rules_export.md", _markdown_from_mapping("Chunk Processing Rules Export", rules_export))
    _write_json(output_dir / "processing_results_export.json", results_export)
    _write_md(output_dir / "processing_results_export.md", _markdown_from_mapping("Chunk Processing Results Export", results_export))
    _write_json(output_dir / "query_responses.json", {"items": responses})
    _write_json(output_dir / "target_chunk_ids.json", {"items": target_chunk_ids, "count": len(target_chunk_ids)})
    bundle = _build_chunk_audit_bundle(
        output_dir=output_dir,
        prepare_report=prepare_report,
        rules_export=rules_export,
        results_export=results_export,
    )
    _write_json(output_dir / "external_audit_bundle.json", bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
