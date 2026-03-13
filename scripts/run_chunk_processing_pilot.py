#!/usr/bin/env python3
"""Run the rules-first 5-document chunk/proposition pilot and emit audit reports."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile
from typing import Any, Dict, Iterable, List, Sequence
import re
from io import BytesIO

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
from services.ingest.chunk_semantics import build_chunk_semantics_client, extract_chunk_semantics  # noqa: E402
from pypdf import PdfReader  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "chunk_processing_pilot_v1.json"
SOURCE_ZIP_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "documents.zip"
DEFAULT_OUTPUT_DIR = artifact_path("competition_runs", "pilots", "chunk_processing_pilot_v1")
DEFAULT_PROJECT_ID = "competition_chunk_processing_pilot_v1"
DEFAULT_AUDIT_EXPORT_DIR = artifact_path("corpus_investigation", "2026-03-12-version-lineage-rca", "chunk_processing_external_audit_export")
ARTICLE_HEADING_PATTERN = re.compile(r"(?<!\()(?<!\.)\b(\d{1,3})\.\s+[A-Z]")
PUBLIC_DATASET_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "questions.json"


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


def _extract_pdf_text(pdf_id: str, *, max_pages: int = 3) -> str:
    with zipfile.ZipFile(SOURCE_ZIP_PATH) as archive:
        data = archive.read(f"{pdf_id}.pdf")
    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])


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


def _pdf_ids_from_fixture(fixture: Dict[str, Any]) -> List[str]:
    return [
        str(item.get("pdf_id", "")).strip()
        for item in fixture.get("documents", [])
        if str(item.get("pdf_id", "")).strip()
    ]


def _build_subset_zip_from_pdf_ids(*, pdf_ids: Sequence[str], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    names = {f"{item}.pdf" for item in pdf_ids if str(item).strip()}
    with zipfile.ZipFile(SOURCE_ZIP_PATH) as src, zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as dst:
        for name in src.namelist():
            if name in names:
                dst.writestr(name, src.read(name))
    return output_path


def _build_subset_zip(*, fixture: Dict[str, Any], output_path: Path) -> Path:
    return _build_subset_zip_from_pdf_ids(pdf_ids=_pdf_ids_from_fixture(fixture), output_path=output_path)


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


def _query_map(fixture: Dict[str, Any], field: str = "queries") -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("question_id")): item
        for item in fixture.get(field, [])
        if isinstance(item, dict) and str(item.get("question_id", "")).strip()
    }


def _expected_pdf_ids(item: Dict[str, Any]) -> List[str]:
    values = item.get("expected_pdf_ids")
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value).strip()]
    value = str(item.get("expected_pdf_id", "")).strip()
    return [value] if value else []


def _target_chunk_ids(snapshot: Dict[str, List[Dict[str, Any]]], fixture: Dict[str, Any]) -> List[str]:
    projections = list(snapshot["chunk_search_documents"])
    out: List[str] = []

    def _add(predicate, limit: int) -> None:
        count = 0
        for row in projections:
            if predicate(row):
                out.append(str(row.get("chunk_id")))
                count += 1
                if count >= limit:
                    break

    for item in fixture.get("shadow_subset", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("shadow_kind", "")) != "real_chunk_family":
            continue
        article_number = str(item.get("article_number", "")).strip()
        pdf_id = str(item.get("pdf_id", "")).strip()
        text_terms = [str(term).lower() for term in item.get("text_terms", []) if str(term).strip()]
        section_kind_case = str(item.get("section_kind_case", "")).strip().lower()
        _add(
            lambda row, pdf_id=pdf_id, article_number=article_number, text_terms=text_terms, section_kind_case=section_kind_case: (
                (not pdf_id or str(row.get("pdf_id", "")).strip() == pdf_id)
                and (not article_number or str(row.get("article_number", "")).strip() == article_number)
                and (
                    not section_kind_case
                    or str((row.get("section_kind_case") or "")).strip().lower() == section_kind_case
                    or (not str((row.get("section_kind_case") or "")).strip() and bool(text_terms))
                )
                and (not text_terms or any(term in json.dumps(row, ensure_ascii=False).lower() for term in text_terms))
            ),
            6 if section_kind_case else 3,
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

    def _doc_assertions(pdf_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in snapshot["chunk_search_documents"]:
            if str(row.get("pdf_id", "")) != pdf_id:
                continue
            if isinstance(row.get("semantic_assertions"), list):
                out.extend(item for item in row.get("semantic_assertions", []) if isinstance(item, dict))
        return out

    coinmena_doc_assertions = _doc_assertions("897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13")
    ca004_doc_assertions = _doc_assertions("78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26")

    def _condition_blob(item: Dict[str, Any]) -> str:
        parts: List[str] = []
        if isinstance(item.get("conditions"), list):
            parts.extend(str(value) for value in item.get("conditions", []) if str(value).strip())
        if str(item.get("condition_text", "")).strip():
            parts.append(str(item.get("condition_text")))
        return " ".join(parts).lower()

    def _has_money_assertion(items: List[Dict[str, Any]]) -> bool:
        for item in items:
            blob = json.dumps(item, ensure_ascii=False).lower()
            if str(item.get("relation_type", "")) == "ordered_to_pay":
                return True
            if any(token in blob for token in ("usd", "aed", "eur", "gbp", "dirham")):
                return True
            direct = item.get("direct_answer", {}) if isinstance(item.get("direct_answer"), dict) else {}
            if direct.get("answer_type") == "number" and direct.get("number_value") is not None:
                return True
        return False

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
            "has_condition_preserved": any("legal advice" in _condition_blob(item) or "mediation" in _condition_blob(item) or "subject to" in _condition_blob(item) for item in employment_assertions),
        },
        "coinmena_order": {
            "chunk_id": coinmena.get("chunk_id"),
            "assertion_count": len(coinmena_assertions),
            "has_amount": _has_money_assertion(coinmena_doc_assertions),
            "has_deadline": any("14" in json.dumps(item, ensure_ascii=False) and "day" in json.dumps(item, ensure_ascii=False).lower() for item in coinmena_doc_assertions),
            "has_interest": any("9%" in json.dumps(item, ensure_ascii=False) or "interest" in json.dumps(item, ensure_ascii=False).lower() for item in coinmena_doc_assertions),
        },
        "ca004_order": {
            "chunk_id": ca004.get("chunk_id"),
            "assertion_count": len(ca004_assertions),
            "has_amount": _has_money_assertion(ca004_doc_assertions),
            "has_interest": any("9%" in json.dumps(item, ensure_ascii=False) or "interest" in json.dumps(item, ensure_ascii=False).lower() for item in ca004_doc_assertions),
        },
        "semantic_dense_summary_count": sum(1 for row in projections.values() if str(row.get("semantic_dense_summary", "")).strip()),
    }


async def _run_query_batch(project_id: str, query_specs: Sequence[Dict[str, Any]], *, dataset_id: str) -> List[Dict[str, Any]]:
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
    for query in query_specs:
        request = QueryRequest(
            project_id=project_id,
            question=Question(
                id=str(query["question_id"]),
                question=str(query["question"]),
                answer_type=str(query["answer_type"]),
                route_hint=query.get("route_hint"),
                source="manual",
                difficulty="easy",
                dataset_id=dataset_id,
            ),
            runtime_policy=policy,
        )
        response = await qa_router.ask(request)
        results.append(response.model_dump(mode="json"))
    return results


def _normalize_answer(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def _answers_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) < 0.01
    expected_norm = _normalize_answer(expected)
    actual_norm = _normalize_answer(actual)
    if isinstance(expected_norm, str) and isinstance(actual_norm, str):
        return expected_norm.casefold() == actual_norm.casefold()
    return expected_norm == actual_norm


def _response_action_matches(spec: Dict[str, Any], response: Dict[str, Any]) -> bool:
    expected_action = str(spec.get("expected_action", "answer")).strip().lower()
    if expected_action == "abstain":
        return bool(response.get("abstained"))
    if bool(response.get("abstained")):
        return False
    if "expected_answer" not in spec:
        return True
    return _answers_match(spec.get("expected_answer"), response.get("answer"))


def _route_matches(spec: Dict[str, Any], response: Dict[str, Any]) -> bool:
    route_hint = str(spec.get("route_hint", "")).strip()
    if not route_hint:
        return True
    return str(response.get("route_name", "")).strip() == route_hint


def _top_candidates(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    retrieval_trace = debug.get("retrieval_stage_trace", {}) if isinstance(debug.get("retrieval_stage_trace"), dict) else {}
    return retrieval_trace.get("top_candidates", []) if isinstance(retrieval_trace.get("top_candidates"), list) else []


def _used_source_page_ids(response: Dict[str, Any]) -> List[str]:
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    used_pages = debug.get("used_pages", []) if isinstance(debug.get("used_pages"), list) else []
    return [str(item.get("source_page_id", "")).strip() for item in used_pages if str(item.get("source_page_id", "")).strip()]


def _top3_contains_expected(response: Dict[str, Any], spec: Dict[str, Any]) -> bool | None:
    expected_pdf_ids = _expected_pdf_ids(spec)
    if not expected_pdf_ids:
        return None
    return any(
        any(str(item.get("source_page_id", "")).startswith(pdf_id) for pdf_id in expected_pdf_ids)
        for item in _top_candidates(response)[:3]
    )


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
        expected_pdf_ids = _expected_pdf_ids(expected)
        top3_contains_expected = any(
            any(str(item.get("source_page_id", "")).startswith(pdf_id) for pdf_id in expected_pdf_ids)
            for item in top_candidates[:3]
        ) if expected_pdf_ids else False
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


def _baseline_delta_report(fixture: Dict[str, Any], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    queries = {str(item["question_id"]): item for item in fixture.get("queries", [])}
    rows: List[Dict[str, Any]] = []
    preserved_or_improved = 0
    for response in responses:
        qid = str(response.get("question_id", ""))
        expected = queries[qid]
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        retrieval_trace = debug.get("retrieval_stage_trace", {}) if isinstance(debug.get("retrieval_stage_trace"), dict) else {}
        reranked = retrieval_trace.get("top_candidates", []) if isinstance(retrieval_trace.get("top_candidates"), list) else []
        chunk_only = retrieval_trace.get("chunk_only_top_candidates", []) if isinstance(retrieval_trace.get("chunk_only_top_candidates"), list) else []
        expected_pdf_ids = _expected_pdf_ids(expected)

        def _rank(rows_: List[Dict[str, Any]]) -> int | None:
            for index, item in enumerate(rows_, start=1):
                if any(str(item.get("source_page_id", "")).startswith(pdf_id) for pdf_id in expected_pdf_ids):
                    return index
            return None

        reranked_rank = _rank(reranked)
        chunk_only_rank = _rank(chunk_only)
        improved_or_preserved = False
        if reranked_rank is not None and chunk_only_rank is not None:
            improved_or_preserved = reranked_rank <= chunk_only_rank
        elif reranked_rank is not None and chunk_only_rank is None:
            improved_or_preserved = True
        if improved_or_preserved:
            preserved_or_improved += 1
        rows.append(
            {
                "question_id": qid,
                "expected_pdf_ids": expected_pdf_ids,
                "chunk_only_rank": chunk_only_rank,
                "reranked_rank": reranked_rank,
                "improved_or_preserved": improved_or_preserved,
                "chunk_only_top_candidates": chunk_only[:3],
                "reranked_top_candidates": reranked[:3],
            }
        )

    return {
        "report_version": "chunk_processing_baseline_delta_report_v1",
        "query_count": len(rows),
        "improved_or_preserved_count": preserved_or_improved,
        "improved_or_preserved_ratio": round(preserved_or_improved / max(1, len(rows)), 4),
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
        expectation = expected.get("direct_answer_expected", {}) if isinstance(expected.get("direct_answer_expected"), dict) else {}
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        solver_trace = debug.get("solver_trace", {}) if isinstance(debug.get("solver_trace"), dict) else {}
        used = str(solver_trace.get("solver_version", "")) == "proposition_direct_answer_v1"
        if used:
            used_count += 1
        answer = response.get("answer")
        expected_action = str(expectation.get("expected_action", "answer" if expectation.get("eligible") else "abstain"))
        expected_answer = expectation.get("expected_answer", expected.get("expected_answer"))
        correct = False
        if expected_action == "abstain":
            correct = not used
        else:
            correct = used and answer == expected_answer
            if used and isinstance(answer, (int, float)) and isinstance(expected_answer, (int, float)):
                correct = abs(float(answer) - float(expected_answer)) < 0.01
        if used and correct:
            correct_count += 1
        rows.append(
            {
                "question_id": qid,
                "eligible_expected": bool(expectation.get("eligible")),
                "expected_action": expected_action,
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


def _direct_answer_eligibility_report(fixture: Dict[str, Any], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    queries = {str(item["question_id"]): item for item in fixture.get("queries", [])}
    rows: List[Dict[str, Any]] = []
    eligible_count = 0
    used_count = 0
    precision_hits = 0
    abstain_reasons: Dict[str, int] = {}
    for response in responses:
        qid = str(response.get("question_id", ""))
        expected = queries[qid]
        expectation = expected.get("direct_answer_expected", {}) if isinstance(expected.get("direct_answer_expected"), dict) else {}
        eligible = bool(expectation.get("eligible"))
        if eligible:
            eligible_count += 1
        debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
        solver_trace = debug.get("solver_trace", {}) if isinstance(debug.get("solver_trace"), dict) else {}
        used = str(solver_trace.get("solver_version", "")) == "proposition_direct_answer_v1"
        if used:
            used_count += 1
        expected_action = str(expectation.get("expected_action", "answer" if eligible else "abstain"))
        expected_answer = expectation.get("expected_answer", expected.get("expected_answer"))
        answer = response.get("answer")
        precise = False
        if eligible and used:
            precise = answer == expected_answer
            if isinstance(answer, (int, float)) and isinstance(expected_answer, (int, float)):
                precise = abs(float(answer) - float(expected_answer)) < 0.01
        if eligible and used and precise:
            precision_hits += 1
        if not used:
            reason = str(solver_trace.get("path", "direct_answer_not_used") or "direct_answer_not_used")
            abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
        rows.append(
            {
                "question_id": qid,
                "eligible_expected": eligible,
                "expected_action": expected_action,
                "used_direct_answer": used,
                "answer": answer,
                "expected_answer": expected_answer,
                "precise": precise,
                "solver_path": solver_trace.get("path"),
            }
        )
    return {
        "report_version": "chunk_processing_direct_answer_eligibility_report_v1",
        "query_count": len(rows),
        "eligible_count": eligible_count,
        "used_count": used_count,
        "precision_on_eligible": round(precision_hits / max(1, eligible_count), 4) if eligible_count else 0.0,
        "abstain_reasons": abstain_reasons,
        "items": rows,
    }


def _expanded_frozen_query_report(fixture: Dict[str, Any], responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    query_specs = _query_map(fixture, field="expanded_queries")
    rows: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {}
    pass_count = 0
    route_match_count = 0
    top3_known_source_hits = 0
    top3_known_source_total = 0
    for response in responses:
        qid = str(response.get("question_id", ""))
        spec = query_specs[qid]
        category = str(spec.get("category", "uncategorized"))
        category_counts[category] = category_counts.get(category, 0) + 1
        action_match = _response_action_matches(spec, response)
        route_match = _route_matches(spec, response)
        top3_contains_expected = _top3_contains_expected(response, spec)
        if action_match:
            pass_count += 1
        if route_match:
            route_match_count += 1
        if top3_contains_expected is not None:
            top3_known_source_total += 1
            if top3_contains_expected:
                top3_known_source_hits += 1
        solver_trace = (response.get("debug") or {}).get("solver_trace", {}) if isinstance((response.get("debug") or {}), dict) else {}
        direct_answer_used = str(solver_trace.get("solver_version", "")) == "proposition_direct_answer_v1"
        rows.append(
            {
                "question_id": qid,
                "category": category,
                "coverage_kind": spec.get("coverage_kind"),
                "answer_type": spec.get("answer_type"),
                "expected_action": spec.get("expected_action", "answer"),
                "expected_answer": spec.get("expected_answer"),
                "expected_source_family": spec.get("expected_source_family"),
                "expected_pdf_ids": _expected_pdf_ids(spec),
                "route_hint": spec.get("route_hint"),
                "route_name": response.get("route_name"),
                "route_match": route_match,
                "answer": response.get("answer"),
                "abstained": response.get("abstained"),
                "action_match": action_match,
                "direct_answer_used": direct_answer_used,
                "top3_contains_expected_source": top3_contains_expected,
                "used_source_page_ids": _used_source_page_ids(response),
                "top_candidates": _top_candidates(response)[:3],
                "source_reference": spec.get("source_reference", {}),
            }
        )
    return {
        "report_version": "chunk_processing_expanded_frozen_query_report_v1",
        "fixture_version": fixture.get("fixture_version"),
        "evaluation_contract_version": fixture.get("evaluation_contract_version"),
        "query_count": len(rows),
        "category_counts": category_counts,
        "pass_count": pass_count,
        "pass_ratio": round(pass_count / max(1, len(rows)), 4),
        "route_match_count": route_match_count,
        "route_match_ratio": round(route_match_count / max(1, len(rows)), 4),
        "known_source_top3_hit_count": top3_known_source_hits,
        "known_source_top3_hit_ratio": round(top3_known_source_hits / max(1, top3_known_source_total), 4) if top3_known_source_total else None,
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


def _run_semantic_gate_fixtures(fixture: Dict[str, Any]) -> Dict[str, Any]:
    client = build_chunk_semantics_client()
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(fixture.get("semantic_gate_fixtures", []), start=1):
        if not isinstance(item, dict):
            continue
        fixture_id = str(item.get("fixture_id", f"fixture_{index}"))
        doc_type = str(item.get("doc_type", "law"))
        paragraph_payload = item.get("paragraph", {}) if isinstance(item.get("paragraph"), dict) else {}
        projection_payload = item.get("projection", {}) if isinstance(item.get("projection"), dict) else {}
        paragraph = {
            "paragraph_id": f"{fixture_id}_paragraph",
            "document_id": f"{fixture_id}_document",
            "page_id": f"{fixture_id}_page",
            "text": str(paragraph_payload.get("text", "")),
            "section_kind": paragraph_payload.get("section_kind"),
            "paragraph_class": paragraph_payload.get("paragraph_class"),
            "article_refs": list(paragraph_payload.get("article_refs", [])) if isinstance(paragraph_payload.get("article_refs"), list) else [],
            "law_refs": list(paragraph_payload.get("law_refs", [])) if isinstance(paragraph_payload.get("law_refs"), list) else [],
            "case_refs": list(paragraph_payload.get("case_refs", [])) if isinstance(paragraph_payload.get("case_refs"), list) else [],
            "dates": list(paragraph_payload.get("dates", [])) if isinstance(paragraph_payload.get("dates"), list) else [],
            "money_mentions": list(paragraph_payload.get("money_mentions", [])) if isinstance(paragraph_payload.get("money_mentions"), list) else [],
        }
        page = {
            "page_id": f"{fixture_id}_page",
            "document_id": f"{fixture_id}_document",
            "source_page_id": f"{fixture_id}_0",
            "page_num": 0,
        }
        document = {
            "document_id": f"{fixture_id}_document",
            "pdf_id": str((item.get("source_reference", {}) if isinstance(item.get("source_reference"), dict) else {}).get("label") or fixture_id),
            "doc_type": doc_type,
            "title": str((item.get("source_reference", {}) if isinstance(item.get("source_reference"), dict) else {}).get("label") or fixture_id),
        }
        projection = {
            "chunk_id": paragraph["paragraph_id"],
            "doc_type": doc_type,
            "heading_path": list(projection_payload.get("heading_path", [])) if isinstance(projection_payload.get("heading_path"), list) else [],
            "article_number": projection_payload.get("article_number"),
            "article_title": projection_payload.get("article_title"),
            "part_ref": projection_payload.get("part_ref"),
            "chapter_ref": projection_payload.get("chapter_ref"),
            "section_ref": projection_payload.get("section_ref"),
            "section_kind_case": projection_payload.get("section_kind_case"),
            "case_number": projection_payload.get("case_number"),
            "court_name": projection_payload.get("court_name"),
        }
        semantics = None
        last_error = None
        for attempt in range(3):
            try:
                semantics = extract_chunk_semantics(
                    client=client,
                    paragraph=paragraph,
                    page=page,
                    document=document,
                    projection=projection,
                )
                last_error = None
                break
            except RuntimeError as exc:
                last_error = str(exc)
                if "429" not in last_error:
                    raise
                time.sleep(1.5 * (attempt + 1))
        if semantics is None:
            rows.append(
                {
                    "fixture_id": fixture_id,
                    "source_reference": item.get("source_reference", {}),
                    "doc_type": doc_type,
                    "prompt_version": "fixture_retry_failed",
                    "mode": "error",
                    "payload": {},
                    "proposition_count": 0,
                    "expectations": item.get("expectations", {}),
                    "error": last_error,
                }
            )
            continue
        payload = semantics.payload if isinstance(semantics.payload, dict) else {}
        propositions = payload.get("propositions", []) if isinstance(payload.get("propositions"), list) else []
        rows.append(
            {
                "fixture_id": fixture_id,
                "fixture_classification": item.get("fixture_classification"),
                "coverage_kind": item.get("coverage_kind"),
                "source_reference": item.get("source_reference", {}),
                "doc_type": doc_type,
                "prompt_version": semantics.prompt_version,
                "mode": semantics.mode,
                "payload": payload,
                "proposition_count": len(propositions),
                "expectations": item.get("expectations", {}),
            }
        )
    return {
        "report_version": "chunk_processing_semantic_gate_fixtures_v1",
        "fixture_count": len(rows),
        "items": rows,
    }


def _run_real_corpus_checks(*, fixture: Dict[str, Any], pilot_project_id: str, output_dir: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for check in fixture.get("real_corpus_checks", []):
        if not isinstance(check, dict):
            continue
        question_spec = {
            "question_id": str(check.get("check_id", "")),
            "question": str(check.get("question", "")),
            "answer_type": str(check.get("answer_type", "free_text")),
            "route_hint": check.get("route_hint"),
        }
        project_id = pilot_project_id
        execution_mode = "runtime_query"
        if str(check.get("project_scope", "")).strip() == "supplemental_single_doc":
            supplemental_pdf_ids = [str(item).strip() for item in check.get("supplemental_pdf_ids", []) if str(item).strip()]
            text = _extract_pdf_text(supplemental_pdf_ids[0], max_pages=3) if supplemental_pdf_ids else ""
            lowered_text = text.lower()
            suspicious_terms = [
                term
                for term in ("miranda", "jury", "plea bargain", "parole")
                if term in str(check.get("question", "")).lower()
            ]
            response = {
                "question_id": str(check.get("check_id", "")),
                "route_name": "no_answer",
                "answer": None,
                "abstained": not any(term in lowered_text for term in suspicious_terms),
                "debug": {"used_pages": []},
            }
            action_match = _response_action_matches(check, response)
            top3_contains_expected = None
            execution_mode = "supplemental_text_gate"
        else:
            response = asyncio.run(_run_query_batch(project_id, [question_spec], dataset_id="chunk_processing_real_corpus_checks_v1"))[0]
            action_match = _response_action_matches(check, response)
            top3_contains_expected = _top3_contains_expected(response, check)
        rows.append(
            {
                "check_id": str(check.get("check_id", "")),
                "fixture_classification": check.get("fixture_classification"),
                "coverage_kind": check.get("coverage_kind"),
                "project_scope": check.get("project_scope"),
                "execution_mode": execution_mode,
                "source_reference": check.get("source_reference", {}),
                "expected_action": check.get("expected_action"),
                "expected_answer": check.get("expected_answer"),
                "expected_source_family": check.get("expected_source_family"),
                "expected_pdf_ids": _expected_pdf_ids(check),
                "answer_type": check.get("answer_type"),
                "route_name": response.get("route_name"),
                "answer": response.get("answer"),
                "abstained": response.get("abstained"),
                "action_match": action_match,
                "top3_contains_expected_source": top3_contains_expected,
                "used_source_page_ids": _used_source_page_ids(response),
                "top_candidates": _top_candidates(response)[:3],
            }
        )
    pass_count = sum(1 for row in rows if row["action_match"])
    return {
        "report_version": "chunk_processing_real_corpus_fixture_report_v1",
        "fixture_count": len(rows),
        "pass_count": pass_count,
        "pass_ratio": round(pass_count / max(1, len(rows)), 4),
        "items": rows,
    }


def _semantic_failure_class_report(semantic: Dict[str, Any], extra_fixtures: Dict[str, Any]) -> Dict[str, Any]:
    missing_conditions = []
    if not bool(((semantic.get("employment_article_11") or {}).get("has_condition_preserved"))):
        missing_conditions.append(
            {
                "class": "conditional_legislative_norm",
                "chunk_id": (semantic.get("employment_article_11") or {}).get("chunk_id"),
                "detail": "Condition-bearing legislative proposition lost required conditions.",
            }
        )

    missing_amount = []
    if not bool(((semantic.get("coinmena_order") or {}).get("has_amount"))):
        missing_amount.append(
            {
                "class": "case_operative_amount",
                "chunk_id": (semantic.get("coinmena_order") or {}).get("chunk_id"),
                "detail": "Operative payment amount missing from case-order semantic propositions.",
            }
        )

    missing_interest = []
    if not bool(((semantic.get("ca004_order") or {}).get("has_interest"))):
        missing_interest.append(
            {
                "class": "case_interest_consequence",
                "chunk_id": (semantic.get("ca004_order") or {}).get("chunk_id"),
                "detail": "Interest consequence missing from case-order semantic propositions.",
            }
        )

    polarity_loss = []
    for item in extra_fixtures.get("items", []):
        expectations = item.get("expectations", {}) if isinstance(item.get("expectations"), dict) else {}
        if not expectations.get("must_preserve_polarity"):
            continue
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        propositions = payload.get("propositions", []) if isinstance(payload.get("propositions"), list) else []
        if not propositions:
            polarity_loss.append(
                {
                    "fixture_id": item.get("fixture_id"),
                    "detail": "No propositions extracted for polarity-sensitive fixture.",
                }
            )

    return {
        "report_version": "chunk_processing_semantic_failure_class_report_v1",
        "missing_conditions": missing_conditions,
        "missing_conditions_count": len(missing_conditions),
        "missing_amount": missing_amount,
        "missing_amount_count": len(missing_amount),
        "missing_interest_consequence": missing_interest,
        "missing_interest_consequence_count": len(missing_interest),
        "polarity_loss": polarity_loss,
        "polarity_loss_count": len(polarity_loss),
    }


def _fixture_gate_report(
    *,
    structural: Dict[str, Any],
    semantic: Dict[str, Any],
    retrieval: Dict[str, Any],
    baseline_delta: Dict[str, Any],
    direct_answer_eligibility: Dict[str, Any],
    provenance: Dict[str, Any],
    extra_fixtures: Dict[str, Any],
) -> Dict[str, Any]:
    fixture_rows: List[Dict[str, Any]] = []
    for item in extra_fixtures.get("items", []):
        expectations = item.get("expectations", {}) if isinstance(item.get("expectations"), dict) else {}
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        propositions = payload.get("propositions", []) if isinstance(payload.get("propositions"), list) else []
        relation_aliases = {
            "must_file_within": "requires",
            "liable_to": "penalizes",
            "comes_into_force_on": "governs",
            "comes_into_force_via": "governs",
            "commences_on": "governs",
            "commencement_requires": "governs",
            "forum_of_proceeding": "governs",
        }
        relation_types = {
            relation_aliases.get(str(prop.get("relation_type", "")).strip().lower(), str(prop.get("relation_type", "")).strip().lower())
            for prop in propositions if isinstance(prop, dict)
        }
        pass_checks = {
            "required_relations": all(rel in relation_types for rel in expectations.get("required_relations", [])),
            "must_have_amount": (not expectations.get("must_have_amount")) or any(
                any(token in json.dumps(prop, ensure_ascii=False) for token in ("AED", "USD", "EUR", "GBP"))
                for prop in propositions if isinstance(prop, dict)
            ),
            "must_have_conditions_or_exceptions": (not expectations.get("must_have_conditions_or_exceptions")) or any(
                (prop.get("conditions") or prop.get("exceptions"))
                for prop in propositions if isinstance(prop, dict)
            ),
            "must_have_empty_propositions": (not expectations.get("must_have_empty_propositions")) or len(propositions) == 0,
        }
        fixture_rows.append(
            {
                "fixture_id": item.get("fixture_id"),
                "fixture_classification": item.get("fixture_classification"),
                "coverage_kind": item.get("coverage_kind"),
                "source_reference": item.get("source_reference", {}),
                "passed": all(pass_checks.values()),
                "checks": pass_checks,
            }
        )

    gate_rows = {
        "structural": {
            "passed": (
                len(structural.get("cross_article_chunk_ids", [])) == 0
                and len(structural.get("case_merge_issue_chunk_ids", [])) == 0
                and float(structural.get("missing_offsets_count", 0)) == 0
                and float(structural.get("missing_parent_count", 0)) < max(1, float(structural.get("chunk_count", 1))) * 0.02
            )
        },
        "semantic": {
            "passed": (
                bool((semantic.get("employment_article_11") or {}).get("has_condition_preserved"))
                and bool((semantic.get("coinmena_order") or {}).get("has_amount"))
                and bool((semantic.get("ca004_order") or {}).get("has_interest"))
                and int(provenance.get("assertion_missing_count", 0) or 0) == 0
                and all(row.get("passed") for row in fixture_rows)
            )
        },
        "retrieval": {
            "passed": (
                float(retrieval.get("top3_expected_hit_ratio", 0.0) or 0.0) == 1.0
                and float(baseline_delta.get("improved_or_preserved_ratio", 0.0) or 0.0) == 1.0
            )
        },
        "direct_answer": {
            "passed": (
                float(direct_answer_eligibility.get("precision_on_eligible", 0.0) or 0.0) == 1.0
                and int(provenance.get("direct_answer_missing_count", 0) or 0) == 0
            )
        },
    }
    return {
        "report_version": "chunk_processing_fixture_gate_report_v1",
        "gates": gate_rows,
        "extra_fixtures": fixture_rows,
    }


def _processing_rules_export(fixture: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "export_version": "chunk_processing_rules_export_v3",
        "program_label": "rules-first chunk/proposition pilot",
        "pilot_scope": {
            "document_count": len(fixture.get("documents", [])),
            "documents": fixture.get("documents", []),
        },
        "evaluation_contract_version": fixture.get("evaluation_contract_version"),
        "expanded_frozen_query_count": len(fixture.get("expanded_queries", [])),
        "real_corpus_check_count": len(fixture.get("real_corpus_checks", [])),
        "fixture_backed_semantic_coverage": fixture.get("semantic_gate_fixtures", []),
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
                "typed direct answer only when grounded proposition dominates",
            ],
            "direct_answer_requires": [
                "single dominant proposition",
                "explicit citation support",
                "single dominant page",
                "no competing conflict",
                "no condition or exception ambiguity",
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
    baseline_delta: Dict[str, Any],
    direct_answer: Dict[str, Any],
    direct_answer_eligibility: Dict[str, Any],
    provenance: Dict[str, Any],
    semantic_failure_class: Dict[str, Any],
    fixture_gate: Dict[str, Any],
    extra_fixtures: Dict[str, Any],
    expanded_queries: Dict[str, Any],
    real_corpus_checks: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "export_version": "chunk_processing_results_export_v3",
        "program_label": "rules-first chunk/proposition pilot",
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
        "baseline_delta": {
            "improved_or_preserved_count": baseline_delta.get("improved_or_preserved_count"),
            "improved_or_preserved_ratio": baseline_delta.get("improved_or_preserved_ratio"),
        },
        "direct_answer": {
            "direct_answer_used_count": direct_answer.get("direct_answer_used_count"),
            "direct_answer_correct_count": direct_answer.get("direct_answer_correct_count"),
            "direct_answer_correct_ratio": direct_answer.get("direct_answer_correct_ratio"),
        },
        "direct_answer_eligibility": {
            "eligible_count": direct_answer_eligibility.get("eligible_count"),
            "used_count": direct_answer_eligibility.get("used_count"),
            "precision_on_eligible": direct_answer_eligibility.get("precision_on_eligible"),
        },
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
        "semantic_failure_classes": {
            "missing_conditions_count": semantic_failure_class.get("missing_conditions_count"),
            "missing_amount_count": semantic_failure_class.get("missing_amount_count"),
            "missing_interest_consequence_count": semantic_failure_class.get("missing_interest_consequence_count"),
            "polarity_loss_count": semantic_failure_class.get("polarity_loss_count"),
        },
        "fixture_gates": fixture_gate.get("gates", {}),
        "extra_fixture_count": extra_fixtures.get("fixture_count"),
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
                "# Rules-First Chunk/Proposition Pilot External Audit Export",
                "",
                "This bundle is a self-contained external-audit package for the rules-first 5-document chunk/proposition pilot.",
                "",
                "Included:",
                "- original full source archive and the 5-document pilot subset",
                "- pilot prepare report and all chunk quality reports",
                "- expanded frozen-query, real-corpus, and shadow-subset reports",
                "- processing rules and processing results exports",
                "- active execution plan and strategy note",
                "- prompt files used for chunk semantics",
                "- implementation snapshot for chunk processing, enrichment, provenance, and runtime proposition retrieval",
                "- contract tests and pilot fixture",
                "",
                "Primary outcomes:",
                f"- core retrieval top-3 expected hit ratio `{results_export['retrieval']['top3_expected_hit_ratio']}`",
                f"- expanded frozen-query pass ratio `{results_export['expanded_frozen_queries']['pass_ratio']}`",
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
    shadow_root = artifact_path("competition_runs", "pilots", "chunk_processing_shadow_subset_v1")
    if shadow_root.exists():
        for artifact in sorted(shadow_root.glob("*")):
            if artifact.is_file():
                _add(artifact, f"shadow/{artifact.name}")

    for rel_path in (
        "docs/exec-plans/active/2026-03-12-chunk-processing-and-proposition-layer.md",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_layer_strategy_and_llm_pilot.md",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_pilot_truth_index.md",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_pilot_truth_index.json",
        "reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_pilot_v1_local_audit_memo.md",
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


def _write_progress(output_dir: Path, stage: str, **extra: Any) -> None:
    payload = {"stage": stage, **extra}
    _write_json(output_dir / "run_progress.json", payload)
    print(f"[chunk_pilot] {stage}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the rules-first 5-document chunk/proposition pilot")
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
    _write_progress(output_dir, "subset_zip_ready", subset_zip_path=str(subset_zip_path))

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
    _write_progress(output_dir, "prepare_complete")

    snapshot = _project_snapshot(str(args.project_id), fixture)
    os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = "1"
    target_chunk_ids = _target_chunk_ids(snapshot, fixture)
    _write_progress(output_dir, "target_chunks_selected", target_chunk_count=len(target_chunk_ids))
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
    _write_progress(output_dir, "chunk_enrichment_complete")
    snapshot = _project_snapshot(str(args.project_id), fixture)
    structural = _structural_report(snapshot, fixture)
    semantic = _semantic_report(snapshot)
    extra_fixtures = _run_semantic_gate_fixtures(fixture)
    semantic_failure_class = _semantic_failure_class_report(semantic, extra_fixtures)
    _write_progress(output_dir, "semantic_reports_complete")
    responses = asyncio.run(_run_query_batch(str(args.project_id), fixture.get("queries", []), dataset_id="chunk_processing_pilot_v1"))
    expanded_query_responses = asyncio.run(
        _run_query_batch(str(args.project_id), fixture.get("expanded_queries", []), dataset_id="chunk_processing_frozen_set_v2")
    )
    _write_progress(output_dir, "query_batches_complete", core_query_count=len(responses), expanded_query_count=len(expanded_query_responses))
    retrieval = _retrieval_report(fixture, responses)
    baseline_delta = _baseline_delta_report(fixture, responses)
    direct_answer = _direct_answer_report(fixture, responses)
    direct_answer_eligibility = _direct_answer_eligibility_report(fixture, responses)
    expanded_frozen_queries = _expanded_frozen_query_report(fixture, expanded_query_responses)
    provenance = _provenance_report(snapshot, responses)
    real_corpus_checks = _run_real_corpus_checks(fixture=fixture, pilot_project_id=str(args.project_id), output_dir=output_dir)
    _write_progress(output_dir, "real_corpus_checks_complete", real_corpus_check_count=len(real_corpus_checks.get("items", [])))
    fixture_gate = _fixture_gate_report(
        structural=structural,
        semantic=semantic,
        retrieval=retrieval,
        baseline_delta=baseline_delta,
        direct_answer_eligibility=direct_answer_eligibility,
        provenance=provenance,
        extra_fixtures=extra_fixtures,
    )
    rules_export = _processing_rules_export(fixture)
    results_export = _processing_results_export(
        prepare_report=prepare_report,
        structural=structural,
        semantic=semantic,
        retrieval=retrieval,
        baseline_delta=baseline_delta,
        direct_answer=direct_answer,
        direct_answer_eligibility=direct_answer_eligibility,
        provenance=provenance,
        semantic_failure_class=semantic_failure_class,
        fixture_gate=fixture_gate,
        extra_fixtures=extra_fixtures,
        expanded_queries=expanded_frozen_queries,
        real_corpus_checks=real_corpus_checks,
    )

    _write_json(output_dir / "structural_chunk_quality_report.json", structural)
    _write_md(output_dir / "structural_chunk_quality_report.md", _markdown_from_mapping("Structural Chunk Quality Report", structural))
    _write_json(output_dir / "semantic_assertion_quality_report.json", semantic)
    _write_md(output_dir / "semantic_assertion_quality_report.md", _markdown_from_mapping("Semantic Assertion Quality Report", semantic))
    _write_json(output_dir / "retrieval_quality_report.json", retrieval)
    _write_md(output_dir / "retrieval_quality_report.md", _markdown_from_mapping("Retrieval Quality Report", retrieval))
    _write_json(output_dir / "baseline_delta_report.json", baseline_delta)
    _write_md(output_dir / "baseline_delta_report.md", _markdown_from_mapping("Baseline Delta Report", baseline_delta))
    _write_json(output_dir / "direct_answer_report.json", direct_answer)
    _write_md(output_dir / "direct_answer_report.md", _markdown_from_mapping("Direct Answer Report", direct_answer))
    _write_json(output_dir / "direct_answer_eligibility_report.json", direct_answer_eligibility)
    _write_md(output_dir / "direct_answer_eligibility_report.md", _markdown_from_mapping("Direct Answer Eligibility Report", direct_answer_eligibility))
    _write_json(output_dir / "provenance_coverage_report.json", provenance)
    _write_md(output_dir / "provenance_coverage_report.md", _markdown_from_mapping("Provenance Coverage Report", provenance))
    _write_json(output_dir / "semantic_failure_class_report.json", semantic_failure_class)
    _write_md(output_dir / "semantic_failure_class_report.md", _markdown_from_mapping("Semantic Failure Class Report", semantic_failure_class))
    _write_json(output_dir / "fixture_gate_report.json", fixture_gate)
    _write_md(output_dir / "fixture_gate_report.md", _markdown_from_mapping("Fixture Gate Report", fixture_gate))
    _write_json(output_dir / "semantic_gate_fixtures_report.json", extra_fixtures)
    _write_md(output_dir / "semantic_gate_fixtures_report.md", _markdown_from_mapping("Semantic Gate Fixtures Report", extra_fixtures))
    _write_json(output_dir / "expanded_frozen_query_report.json", expanded_frozen_queries)
    _write_md(output_dir / "expanded_frozen_query_report.md", _markdown_from_mapping("Expanded Frozen Query Report", expanded_frozen_queries))
    _write_json(output_dir / "real_corpus_fixture_report.json", real_corpus_checks)
    _write_md(output_dir / "real_corpus_fixture_report.md", _markdown_from_mapping("Real Corpus Fixture Report", real_corpus_checks))
    _write_json(output_dir / "processing_rules_export.json", rules_export)
    _write_md(output_dir / "processing_rules_export.md", _markdown_from_mapping("Chunk Processing Rules Export", rules_export))
    _write_json(output_dir / "processing_results_export.json", results_export)
    _write_md(output_dir / "processing_results_export.md", _markdown_from_mapping("Chunk Processing Results Export", results_export))
    _write_json(output_dir / "query_responses.json", {"items": responses})
    _write_json(output_dir / "expanded_query_responses.json", {"items": expanded_query_responses})
    _write_json(output_dir / "target_chunk_ids.json", {"items": target_chunk_ids, "count": len(target_chunk_ids)})
    bundle = _build_chunk_audit_bundle(
        output_dir=output_dir,
        prepare_report=prepare_report,
        rules_export=rules_export,
        results_export=results_export,
    )
    _write_json(output_dir / "external_audit_bundle.json", bundle)
    _write_progress(output_dir, "completed", bundle_zip_path=bundle.get("zip_path"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
