from __future__ import annotations

import hashlib
import json
from http import HTTPStatus
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional
from uuid import uuid4
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from legal_rag_api.azure_llm import AzureLLMClient
from legal_rag_api import case_extraction_pg
from legal_rag_api.contracts import CorpusSearchRequest, DocumentManifest, ParagraphChunk
from legal_rag_api.state import store
from legal_rag_api import corpus_pg
from packages.contracts.corpus_scope import (
    matches_corpus_scope,
    resolve_corpus_import_project_id,
)
from packages.retrieval.search import score_candidate
from services.ingest.agentic_enrichment import (
    ENRICHMENT_PROFILE_VERSION,
    retry_agentic_corpus_enrichment,
    run_agentic_corpus_enrichment,
)
from services.ingest.case_judgment_document_extractor import (
    PIPELINE_NAME as CASE_DOCUMENT_PIPELINE_NAME,
    PIPELINE_VERSION as CASE_DOCUMENT_PIPELINE_VERSION,
    PROMPT_VERSION as CASE_DOCUMENT_PROMPT_VERSION,
    SCHEMA_VERSION as CASE_JUDGMENT_SCHEMA_VERSION,
    choose_document_model,
)
from services.ingest.case_judgment_chunk_extractor import (
    PROMPT_VERSION as CASE_CHUNK_PROMPT_VERSION,
    choose_chunk_model,
)
from services.ingest.case_judgment_pipeline import (
    run_case_judgment_extraction_pipeline,
    run_case_judgment_router_pipeline,
)
from services.ingest.case_judgment_projection import project_case_judgment_artifacts
from services.ingest.case_judgment_router import (
    PIPELINE_NAME as CASE_ROUTER_PIPELINE_NAME,
    PIPELINE_VERSION as CASE_ROUTER_PIPELINE_VERSION,
    PROMPT_VERSION as CASE_ROUTER_PROMPT_VERSION,
    choose_router_model,
)
from services.ingest.corpus_metadata_normalizer import (
    NORMALIZATION_PROFILE_VERSION,
    run_corpus_metadata_normalization,
)
from services.ingest.ingest import compact_ingest_diagnostics, run_deterministic_ingest

router = APIRouter(prefix="/v1/corpus", tags=["Corpus"])
UPLOAD_DIR = Path(os.getenv("LEGAL_RAG_UPLOAD_DIR", "/workspace/reports/uploads"))
chunk_llm_client = AzureLLMClient()


def _sanitize_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", filename or "upload.zip")


def _resolve_upload_dir() -> Path:
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        return UPLOAD_DIR
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "legal_rag_uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _canonical_write_enabled(job_id: str) -> bool:
    if not store.feature_flags.get("canonical_chunk_model_v1", True):
        return False
    canary_percent_raw = os.getenv("CANONICAL_CHUNK_MODEL_CANARY_PERCENT", "100")
    try:
        canary_percent = int(canary_percent_raw)
    except ValueError:
        canary_percent = 100
    canary_percent = max(0, min(100, canary_percent))
    if canary_percent == 100:
        return True
    if canary_percent == 0:
        return False
    bucket = int(hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < canary_percent


def _merge_enrichment_into_result(result: Dict[str, Any], enrichment: Dict[str, Any]) -> None:
    updated_documents = enrichment.get("updated_documents", {})
    updated_paragraphs = enrichment.get("updated_paragraphs", {})
    updated_chunk_projections = enrichment.get("updated_chunk_projections", {})
    relation_edges = enrichment.get("projected_relation_edges", [])

    result["documents"] = [
        updated_documents.get(str(item.get("document_id")), item)
        for item in result.get("documents", [])
    ]
    result["paragraphs"] = [
        updated_paragraphs.get(str(item.get("paragraph_id")), item)
        for item in result.get("paragraphs", [])
    ]
    result["chunk_search_documents"] = [
        updated_chunk_projections.get(str(item.get("chunk_id")), item)
        for item in result.get("chunk_search_documents", [])
    ]
    result["relation_edges"] = relation_edges


def _merge_metadata_normalization_into_result(result: Dict[str, Any], normalization: Dict[str, Any]) -> None:
    updated_documents = normalization.get("updated_documents", {})
    updated_document_bases = normalization.get("updated_document_bases", {})
    updated_law_docs = normalization.get("updated_law_documents", {})
    updated_reg_docs = normalization.get("updated_regulation_documents", {})
    updated_notice_docs = normalization.get("updated_enactment_notice_documents", {})
    updated_case_docs = normalization.get("updated_case_documents", {})
    updated_chunk_projections = normalization.get("updated_chunk_projections", {})
    relation_edges = normalization.get("projected_relation_edges", [])

    result["documents"] = [
        updated_documents.get(str(item.get("document_id")), item)
        for item in result.get("documents", [])
    ]
    result["document_bases"] = [
        updated_document_bases.get(str(item.get("document_id")), item)
        for item in result.get("document_bases", [])
    ]
    result["law_documents"] = [
        updated_law_docs.get(str(item.get("document_id")), item)
        for item in result.get("law_documents", [])
    ]
    result["regulation_documents"] = [
        updated_reg_docs.get(str(item.get("document_id")), item)
        for item in result.get("regulation_documents", [])
    ]
    result["enactment_notice_documents"] = [
        updated_notice_docs.get(str(item.get("document_id")), item)
        for item in result.get("enactment_notice_documents", [])
    ]
    result["case_documents"] = [
        updated_case_docs.get(str(item.get("document_id")), item)
        for item in result.get("case_documents", [])
    ]
    result["chunk_search_documents"] = [
        updated_chunk_projections.get(str(item.get("chunk_id")), item)
        for item in result.get("chunk_search_documents", [])
    ]
    result["relation_edges"] = relation_edges


def _persist_enrichment_artifacts(enrichment: Dict[str, Any]) -> None:
    job = enrichment.get("job") if isinstance(enrichment.get("job"), dict) else {}
    if job:
        store.corpus_enrichment_jobs[str(job.get("job_id"))] = job
        if corpus_pg.enabled():
            corpus_pg.upsert_enrichment_job(job)

    for entry in enrichment.get("registry_entries", []):
        if not isinstance(entry, dict):
            continue
        store.ontology_registry_entries[str(entry.get("entry_id"))] = entry
        if corpus_pg.enabled():
            corpus_pg.upsert_ontology_registry_entry(entry)

    for assertion in enrichment.get("chunk_assertions", []):
        if not isinstance(assertion, dict):
            continue
        store.chunk_ontology_assertions[str(assertion.get("assertion_id"))] = assertion
        if corpus_pg.enabled():
            corpus_pg.upsert_chunk_ontology_assertion(assertion)

    for view in enrichment.get("document_views", []):
        if not isinstance(view, dict):
            continue
        store.document_ontology_views[str(view.get("document_id"))] = view
        if corpus_pg.enabled():
            corpus_pg.upsert_document_ontology_view(view)


def _current_corpus_snapshot(project_id: Optional[str]) -> Dict[str, Any]:
    if corpus_pg.enabled():
        documents = corpus_pg.list_documents(project_id=project_id, include_processing=True)
        pages = corpus_pg.list_pages(project_id=project_id)
        paragraphs = corpus_pg.list_paragraphs(project_id=project_id)
        chunk_search_documents = corpus_pg.list_chunk_search_documents(project_id=project_id)
        relation_edges = corpus_pg.list_relation_edges(project_id=project_id)
        registry_entries = corpus_pg.list_ontology_registry_entries()
    else:
        documents = [item for item in store.documents.values() if matches_corpus_scope(item.get("project_id"), project_id)]
        pages = [item for item in store.pages.values() if matches_corpus_scope(item.get("project_id"), project_id)]
        paragraphs = [item for item in store.paragraphs.values() if matches_corpus_scope(item.get("project_id"), project_id)]
        chunk_search_documents = [
            item
            for item in store.chunk_search_documents.values()
            if str(item.get("document_id", "")) in {str(doc.get("document_id", "")) for doc in documents}
        ]
        relation_edges = list(store.relation_edges.values())
        registry_entries = list(store.ontology_registry_entries.values())
    return {
        "documents": documents,
        "pages": pages,
        "paragraphs": paragraphs,
        "chunk_search_documents": chunk_search_documents,
        "relation_edges": relation_edges,
        "registry_entries": registry_entries,
    }


def _run_import(project_id: Optional[str], blob_url: str, parse_policy: str, dedupe_enabled: bool) -> dict:
    corpus_project_id = resolve_corpus_import_project_id(project_id)
    job_id = store.create_corpus_import(
        project_id=corpus_project_id,
        blob_url=blob_url,
        parse_policy=parse_policy,
        dedupe_enabled=dedupe_enabled,
    )
    store.import_jobs[job_id]["status"] = "running"
    if corpus_pg.enabled():
        corpus_pg.create_import_job(
            project_id=corpus_project_id,
            blob_url=blob_url,
            parse_policy=parse_policy,
            dedupe_enabled=dedupe_enabled,
            job_id=job_id,
        )
        corpus_pg.update_import_job_status(job_id, "running")

    try:
        ingest_payload = run_deterministic_ingest(
            blob_url=blob_url,
            project_id=corpus_project_id,
            parse_policy=parse_policy,
            dedupe_enabled=dedupe_enabled,
        )
        result = ingest_payload["result"]
        diagnostics = compact_ingest_diagnostics(ingest_payload["diagnostics"])
        metadata_normalization = run_corpus_metadata_normalization(
            project_id=corpus_project_id,
            import_job_id=job_id,
            documents=result.get("documents", []),
            pages=result.get("pages", []),
            chunk_search_documents=result.get("chunk_search_documents", []),
            relation_edges=result.get("relation_edges", []),
            document_bases=result.get("document_bases", []),
            law_documents=result.get("law_documents", []),
            regulation_documents=result.get("regulation_documents", []),
            enactment_notice_documents=result.get("enactment_notice_documents", []),
            case_documents=result.get("case_documents", []),
        )
        _merge_metadata_normalization_into_result(result, metadata_normalization)
        enrichment = run_agentic_corpus_enrichment(
            project_id=corpus_project_id,
            import_job_id=job_id,
            documents=result.get("documents", []),
            pages=result.get("pages", []),
            paragraphs=result.get("paragraphs", []),
            chunk_search_documents=result.get("chunk_search_documents", []),
            relation_edges=result.get("relation_edges", []),
        )
        _merge_enrichment_into_result(result, enrichment)
        for doc in result["documents"]:
            manifest = doc.copy()
            store.documents[manifest["document_id"]] = manifest
        for page in result["pages"]:
            store.pages[page["page_id"]] = page
        for para in result["paragraphs"]:
            store.paragraphs[para["paragraph_id"]] = para
        canonical_enabled_for_job = _canonical_write_enabled(job_id)
        if canonical_enabled_for_job:
            for row in result.get("document_bases", []):
                store.document_bases[row["document_id"]] = row
            for row in result.get("law_documents", []):
                store.law_documents[row["document_id"]] = row
            for row in result.get("regulation_documents", []):
                store.regulation_documents[row["document_id"]] = row
            for row in result.get("enactment_notice_documents", []):
                store.enactment_notice_documents[row["document_id"]] = row
            for row in result.get("case_documents", []):
                store.case_documents[row["document_id"]] = row
            for row in result.get("chunk_bases", []):
                store.chunk_bases[row["chunk_id"]] = row
            for row in result.get("law_chunk_facets", []):
                store.law_chunk_facets[row["chunk_id"]] = row
            for row in result.get("regulation_chunk_facets", []):
                store.regulation_chunk_facets[row["chunk_id"]] = row
            for row in result.get("enactment_notice_chunk_facets", []):
                store.enactment_notice_chunk_facets[row["chunk_id"]] = row
            for row in result.get("case_chunk_facets", []):
                store.case_chunk_facets[row["chunk_id"]] = row
            for edge in result.get("relation_edges", []):
                store.relation_edges[edge["edge_id"]] = edge
            for chunk_doc in result.get("chunk_search_documents", []):
                store.chunk_search_documents[chunk_doc["chunk_id"]] = chunk_doc
        _persist_enrichment_artifacts(enrichment)

        if corpus_pg.enabled():
            corpus_pg.persist_ingest_result(result)
            corpus_pg.update_import_job_status(job_id, "completed")
        store.import_jobs[job_id]["ingest_diagnostics"] = diagnostics
        store.import_jobs[job_id]["status"] = "completed"
        store.import_jobs[job_id]["processing_profile_version"] = ENRICHMENT_PROFILE_VERSION
        store.import_jobs[job_id]["metadata_normalization_job"] = metadata_normalization.get("job")
        store.import_jobs[job_id]["enrichment_job"] = enrichment.get("job")
        return {
            "job_id": job_id,
            "status": "accepted",
            "items": len(result["pages"]),
            "documents": len(result["documents"]),
            "canonical_chunk_write_enabled": canonical_enabled_for_job,
            "ingest_diagnostics": diagnostics,
            "processing_profile_version": ENRICHMENT_PROFILE_VERSION,
            "metadata_normalization_profile_version": NORMALIZATION_PROFILE_VERSION,
            "metadata_normalization_job": metadata_normalization.get("job"),
            "enrichment_job": enrichment.get("job"),
        }
    except Exception:
        store.import_jobs[job_id]["status"] = "failed"
        if corpus_pg.enabled():
            corpus_pg.update_import_job_status(job_id, "failed")
        raise


def _derive_processing_status(document_status: Any, processing: Dict[str, Any]) -> tuple[str, str]:
    parse_error = processing.get("parse_error")
    if parse_error:
        return "failed", str(parse_error)

    parse_warning = processing.get("parse_warning")
    if parse_warning:
        return "warning", str(parse_warning)

    score_raw = processing.get("text_quality_score")
    score: Optional[float] = None
    try:
        if score_raw is not None:
            score = float(score_raw)
    except Exception:
        score = None
    if score is not None and score < 0.65:
        return "needs_review", f"low_text_quality:{score:.2f}"

    normalized = str(document_status or "").strip().lower()
    if normalized in {"parsed", "indexed", "completed"}:
        return "completed", "ready"
    if normalized in {"queued", "running", "processing", "importing"}:
        return "processing", "in_progress"
    if normalized == "failed":
        return "failed", "document_failed"
    return "unknown", "status_unset"


def _document_source_file_path(document: Dict[str, Any], processing: Dict[str, Any]) -> str:
    direct = str(document.get("source_pdf_path", "")).strip()
    if direct:
        return direct
    return str(processing.get("source_pdf_path", "")).strip()


def _extract_first_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _normalize_str_list(value: Any, limit: int = 12) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    seen = set()
    for item in value:
        token = re.sub(r"\s+", " ", str(item).strip())
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _chunk_prompt(text: str) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) > 2200:
        compact = compact[:2200]
    return (
        "Return strict JSON only. "
        "Schema: {summary, section_type, tags, entities, article_refs, law_refs, case_refs, obligations, prohibitions, penalties, dates, amounts, confidence}. "
        "summary <= 40 words. "
        "section_type enum: definition|obligation|prohibition|procedure|fact|reasoning|holding|penalty|other. "
        "tags: up to 8 concise snake_case labels. "
        "entities/article_refs/law_refs/case_refs/obligations/prohibitions/penalties/dates/amounts are arrays of strings. "
        "confidence is float 0..1.\n"
        f"Text: {compact}"
    )


async def _run_chunk_llm(text: str) -> Dict[str, Any]:
    completion, usage = await chunk_llm_client.complete_chat(
        _chunk_prompt(text),
        user_context={"task": "chunk_enrichment"},
        system_prompt=(
            "You are a legal information extraction engine. "
            "Extract structured legal evidence exactly as JSON. No markdown."
        ),
        max_tokens=420,
        temperature=0.1,
    )
    parsed = _extract_first_json_object(completion)
    summary = str(parsed.get("summary", "")).strip()
    section_type = str(parsed.get("section_type", "other")).strip().lower()
    if section_type not in {
        "definition",
        "obligation",
        "prohibition",
        "procedure",
        "fact",
        "reasoning",
        "holding",
        "penalty",
        "other",
    }:
        section_type = "other"
    tags = []
    for tag in _normalize_str_list(parsed.get("tags"), limit=8):
        normalized = re.sub(r"[^a-z0-9_]+", "_", str(tag).strip().lower()).strip("_")
        if normalized:
            tags.append(normalized)
    if not summary:
        summary = re.sub(r"\s+", " ", text or "").strip()[:160]
    try:
        confidence = float(parsed.get("confidence", 0.7))
    except Exception:
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))
    payload = {
        "summary": summary[:320],
        "section_type": section_type,
        "tags": tags,
        "entities": _normalize_str_list(parsed.get("entities"), limit=12),
        "article_refs": _normalize_str_list(parsed.get("article_refs"), limit=16),
        "law_refs": _normalize_str_list(parsed.get("law_refs"), limit=16),
        "case_refs": _normalize_str_list(parsed.get("case_refs"), limit=16),
        "obligations": _normalize_str_list(parsed.get("obligations"), limit=10),
        "prohibitions": _normalize_str_list(parsed.get("prohibitions"), limit=10),
        "penalties": _normalize_str_list(parsed.get("penalties"), limit=10),
        "dates": _normalize_str_list(parsed.get("dates"), limit=12),
        "amounts": _normalize_str_list(parsed.get("amounts"), limit=8),
        "confidence": confidence,
    }
    return {
        "summary": payload["summary"],
        "section_type": payload["section_type"],
        "tags": payload["tags"],
        "payload": payload,
        "usage": usage,
    }


def _document_prompt(document: Dict[str, Any], context_text: str) -> str:
    compact = re.sub(r"\s+", " ", context_text or "").strip()
    if len(compact) > 16000:
        compact = compact[:16000]
    return (
        "Return strict JSON only. "
        "Schema: {doc_type,title,citation_title,short_title,jurisdiction,language,issued_date,effective_start_date,effective_end_date,year,law_number,case_id,parties,key_entities,article_refs,law_refs,case_refs,obligations,prohibitions,penalties,key_topics,summary,confidence,quality_flags}. "
        "doc_type enum: law|regulation|enactment_notice|case|other. "
        "Date fields in YYYY-MM-DD or null. "
        "Arrays are arrays of strings. confidence is float 0..1.\n"
        f"Document metadata: {json.dumps({'pdf_id': document.get('pdf_id'), 'title': document.get('title'), 'doc_type': document.get('doc_type')}, ensure_ascii=False)}\n"
        f"Document text excerpt: {compact}"
    )


async def _run_document_llm(document: Dict[str, Any], context_text: str) -> Dict[str, Any]:
    completion, usage = await chunk_llm_client.complete_chat(
        _document_prompt(document, context_text),
        user_context={"task": "document_classification", "document_id": document.get("document_id")},
        system_prompt=(
            "You are a legal document classifier and extractor. "
            "Extract document-level legal metadata and normalized structured fields as JSON."
        ),
        max_tokens=900,
        temperature=0.1,
    )
    parsed = _extract_first_json_object(completion)
    doc_type = str(parsed.get("doc_type", "other")).strip().lower()
    if doc_type not in {"law", "regulation", "enactment_notice", "case", "other"}:
        doc_type = "other"
    try:
        confidence = float(parsed.get("confidence", 0.65))
    except Exception:
        confidence = 0.65
    confidence = max(0.0, min(1.0, confidence))
    payload = {
        "doc_type": doc_type,
        "title": str(parsed.get("title", "")).strip() or document.get("title"),
        "citation_title": str(parsed.get("citation_title", "")).strip() or document.get("citation_title"),
        "short_title": str(parsed.get("short_title", "")).strip() or None,
        "jurisdiction": str(parsed.get("jurisdiction", "")).strip() or None,
        "language": str(parsed.get("language", "")).strip() or None,
        "issued_date": str(parsed.get("issued_date", "")).strip() or None,
        "effective_start_date": str(parsed.get("effective_start_date", "")).strip() or None,
        "effective_end_date": str(parsed.get("effective_end_date", "")).strip() or None,
        "year": parsed.get("year"),
        "law_number": str(parsed.get("law_number", "")).strip() or None,
        "case_id": str(parsed.get("case_id", "")).strip() or None,
        "parties": _normalize_str_list(parsed.get("parties"), limit=20),
        "key_entities": _normalize_str_list(parsed.get("key_entities"), limit=20),
        "article_refs": _normalize_str_list(parsed.get("article_refs"), limit=24),
        "law_refs": _normalize_str_list(parsed.get("law_refs"), limit=24),
        "case_refs": _normalize_str_list(parsed.get("case_refs"), limit=24),
        "obligations": _normalize_str_list(parsed.get("obligations"), limit=16),
        "prohibitions": _normalize_str_list(parsed.get("prohibitions"), limit=16),
        "penalties": _normalize_str_list(parsed.get("penalties"), limit=16),
        "key_topics": _normalize_str_list(parsed.get("key_topics"), limit=16),
        "summary": str(parsed.get("summary", "")).strip()[:500],
        "confidence": confidence,
        "quality_flags": _normalize_str_list(parsed.get("quality_flags"), limit=12),
    }
    return {"payload": payload, "usage": usage}


def _document_context_from_chunks(chunks: List[Dict[str, Any]]) -> str:
    ordered = sorted(
        chunks,
        key=lambda c: (
            int(c.get("paragraph_index", 0) or 0),
            str(c.get("paragraph_id", "")),
        ),
    )
    blocks: List[str] = []
    total = 0
    for chunk in ordered:
        text = re.sub(r"\s+", " ", str(chunk.get("text", "") or "")).strip()
        if not text:
            continue
        blocks.append(text)
        total += len(text)
        if total >= 18000:
            break
    return "\n".join(blocks)


def _load_case_document_context(document_id: str) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if corpus_pg.enabled():
        document = corpus_pg.get_document_with_processing(document_id) or corpus_pg.get_document(document_id) or {}
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        pages = corpus_pg.list_pages(document_id=document_id)
        paragraphs = corpus_pg.list_paragraphs(document_id=document_id)
    else:
        document = store.documents.get(document_id) or {}
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        pages = [item for item in store.pages.values() if str(item.get("document_id", "")) == str(document_id)]
        pages = sorted(pages, key=lambda item: int(item.get("page_num", 0) or 0))
        paragraphs = [item for item in store.paragraphs.values() if str(item.get("document_id", "")) == str(document_id)]
        paragraphs = sorted(
            paragraphs,
            key=lambda row: (
                int((next((p.get("page_num", 0) for p in pages if str(p.get("page_id", "")) == str(row.get("page_id", ""))), 0)) or 0),
                int(row.get("paragraph_index", 0) or 0),
                str(row.get("paragraph_id", "")),
            ),
        )
    return document, pages, paragraphs


def _case_run_store_enabled() -> bool:
    return case_extraction_pg.enabled()


def _case_create_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _case_run_store_enabled():
        return case_extraction_pg.create_case_extraction_run(payload)
    return store.create_case_extraction_run(payload)


def _case_update_run(run_id: str, patch: Dict[str, Any]) -> Dict[str, Any] | None:
    if _case_run_store_enabled():
        return case_extraction_pg.update_case_extraction_run(run_id, patch)
    return store.update_case_extraction_run(run_id, patch)


def _case_get_run(run_id: str) -> Dict[str, Any] | None:
    if _case_run_store_enabled():
        return case_extraction_pg.get_case_extraction_run(run_id)
    return store.get_case_extraction_run(run_id)


def _case_list_runs(*, document_id: Optional[str] = None, pipeline_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.list_case_extraction_runs(document_id=document_id, pipeline_name=pipeline_name, limit=limit)
    return store.list_case_extraction_runs(document_id=document_id, pipeline_name=pipeline_name, limit=limit)


def _case_upsert_document_extraction(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _case_run_store_enabled():
        return case_extraction_pg.upsert_case_document_extraction(payload)
    return store.upsert_case_document_extraction(payload)


def _case_get_document_extraction(document_extraction_id: str) -> Dict[str, Any] | None:
    if _case_run_store_enabled():
        return case_extraction_pg.get_case_document_extraction(document_extraction_id)
    return store.get_case_document_extraction(document_extraction_id)


def _case_list_document_extractions(
    *,
    document_id: Optional[str] = None,
    run_id: Optional[str] = None,
    active_only: bool = False,
    schema_version: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.list_case_document_extractions(
            document_id=document_id,
            run_id=run_id,
            active_only=active_only,
            schema_version=schema_version,
            limit=limit,
        )
    return store.list_case_document_extractions(
        document_id=document_id,
        run_id=run_id,
        active_only=active_only,
        schema_version=schema_version,
        limit=limit,
    )


def _case_activate_document_extraction(document_extraction_id: str) -> Dict[str, Any] | None:
    if _case_run_store_enabled():
        return case_extraction_pg.activate_case_document_extraction(document_extraction_id)
    return store.set_case_document_extraction_active(document_extraction_id)


def _case_upsert_chunk_extractions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.upsert_case_chunk_extractions(rows)
    return [store.upsert_case_chunk_extraction(row) for row in rows]


def _case_list_chunk_extractions(
    *,
    document_extraction_id: Optional[str] = None,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.list_case_chunk_extractions(
            document_extraction_id=document_extraction_id,
            run_id=run_id,
            document_id=document_id,
            limit=limit,
        )
    return store.list_case_chunk_extractions(
        document_extraction_id=document_extraction_id,
        run_id=run_id,
        document_id=document_id,
        limit=limit,
    )


def _case_upsert_qc_results(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.upsert_case_qc_results(rows)
    return [store.upsert_case_qc_result(row) for row in rows]


def _case_list_qc_results(*, run_id: Optional[str] = None, document_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    if _case_run_store_enabled():
        return case_extraction_pg.list_case_qc_results(run_id=run_id, document_id=document_id, limit=limit)
    return store.list_case_qc_results(run_id=run_id, document_id=document_id, limit=limit)


def _next_case_artifact_version(document_id: str, schema_version: str) -> int:
    existing = _case_list_document_extractions(
        document_id=document_id,
        schema_version=schema_version,
        active_only=False,
        limit=1000,
    )
    current = 0
    for row in existing:
        try:
            current = max(current, int(row.get("artifact_version", 0) or 0))
        except Exception:
            continue
    return current + 1


def _persist_case_projection(
    *,
    document_id: str,
    chunk_payloads: List[Dict[str, Any]],
    document_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    document, pages, paragraphs = _load_case_document_context(document_id)
    pages_by_id = {str(row.get("page_id", "")): row for row in pages}
    paragraphs_by_id = {str(row.get("paragraph_id", "")): row for row in paragraphs}

    projection = project_case_judgment_artifacts(
        document_payload=document_payload or document,
        chunk_payloads=chunk_payloads,
        paragraphs_by_id=paragraphs_by_id,
        pages_by_id=pages_by_id,
    )
    for row in projection.get("case_chunk_facets", []):
        chunk_id = str(row.get("chunk_id", ""))
        if chunk_id:
            store.case_chunk_facets[chunk_id] = row
    for row in projection.get("chunk_search_documents", []):
        chunk_id = str(row.get("chunk_id", ""))
        if chunk_id:
            store.chunk_search_documents[chunk_id] = row

    if corpus_pg.enabled():
        corpus_pg.persist_ingest_result(
            {
                "documents": [document],
                "pages": pages,
                "paragraphs": paragraphs,
                "chunk_search_documents": projection.get("chunk_search_documents", []),
                "relation_edges": [],
            }
        )

    return {
        "case_chunk_facets_count": len(projection.get("case_chunk_facets", [])),
        "chunk_search_documents_count": len(projection.get("chunk_search_documents", [])),
    }


@router.post("/import-zip", status_code=202)
def import_zip(payload: dict) -> dict:
    required = {"blob_url", "parse_policy", "dedupe_enabled"}
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=f"missing fields: {sorted(missing)}",
        )
    return _run_import(
        project_id=payload.get("project_id"),
        blob_url=str(payload["blob_url"]),
        parse_policy=payload["parse_policy"],
        dedupe_enabled=bool(payload["dedupe_enabled"]),
    )


@router.post("/import-upload", status_code=202)
def import_upload(
    project_id: Optional[str] = Form(None),
    parse_policy: str = Form("balanced"),
    dedupe_enabled: bool = Form(True),
    file: UploadFile = File(...),
) -> dict:
    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="file must be a .zip")
    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="empty zip payload")

    upload_dir = _resolve_upload_dir()
    safe_name = _sanitize_filename(filename)
    target = upload_dir / f"{uuid4()}_{safe_name}"
    with target.open("wb") as out:
        out.write(payload)

    return _run_import(
        project_id=project_id,
        blob_url=str(target),
        parse_policy=parse_policy,
        dedupe_enabled=bool(dedupe_enabled),
    )


@router.get("/processing-results")
def processing_results(project_id: Optional[str] = None, limit: int = 20) -> dict:
    if corpus_pg.enabled():
        return corpus_pg.processing_results(project_id=project_id, limit=limit)

    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    def _project_match(item: Dict[str, Any]) -> bool:
        if not str(project_id or "").strip():
            return True
        return matches_corpus_scope(item.get("project_id"), project_id)

    jobs = [j for j in store.import_jobs.values() if _project_match(j)]
    jobs.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    latest_job = jobs[0] if jobs else None

    docs = [d for d in store.documents.values() if _project_match(d)]
    pages = [p for p in store.pages.values() if _project_match(p)]
    paragraphs = [p for p in store.paragraphs.values() if _project_match(p)]
    enrichment_jobs = [j for j in store.corpus_enrichment_jobs.values() if _project_match(j)]
    enrichment_jobs.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)

    by_doc_type: Dict[str, int] = {}
    duplicate_count = 0
    for doc in docs:
        doc_type = str(doc.get("doc_type", "other"))
        by_doc_type[doc_type] = by_doc_type.get(doc_type, 0) + 1
        if doc.get("duplicate_group_id"):
            duplicate_count += 1

    docs_sorted = sorted(docs, key=lambda x: str(x.get("document_id", "")))[:limit]
    serialized_docs = [DocumentManifest(**d).model_dump(mode="json") for d in docs_sorted]
    processing_documents: List[Dict[str, Any]] = []
    processing_status_counts: Dict[str, int] = {}
    for doc in docs_sorted:
        processing = doc.get("processing") if isinstance(doc.get("processing"), dict) else {}
        processing_status, processing_note = _derive_processing_status(doc.get("status"), processing)
        processing_status_counts[processing_status] = processing_status_counts.get(processing_status, 0) + 1
        processing_documents.append(
            {
                "document_id": doc.get("document_id"),
                "project_id": doc.get("project_id"),
                "pdf_id": doc.get("pdf_id"),
                "doc_type": doc.get("doc_type", "other"),
                "title": doc.get("title"),
                "status": doc.get("status"),
                "effective_start_date": doc.get("effective_start_date"),
                "effective_end_date": doc.get("effective_end_date"),
                "is_current_version": doc.get("is_current_version"),
                "page_count": doc.get("page_count"),
                "classification_confidence": processing.get("classification_confidence"),
                "text_quality_score": processing.get("text_quality_score"),
                "parse_warning": processing.get("parse_warning"),
                "parse_error": processing.get("parse_error"),
                "compact_summary": processing.get("compact_summary"),
                "llm_document_status": processing.get("llm_document_status"),
                "llm_document_model": processing.get("llm_document_model"),
                "processing_profile_version": processing.get("processing_profile_version"),
                "enrichment_status": ((processing.get("agentic_enrichment") or {}) if isinstance(processing.get("agentic_enrichment"), dict) else {}).get("status"),
                "agent_assertion_count": ((processing.get("agentic_enrichment") or {}) if isinstance(processing.get("agentic_enrichment"), dict) else {}).get("assertion_count", 0),
                "candidate_ontology_count": ((processing.get("agentic_enrichment") or {}) if isinstance(processing.get("agentic_enrichment"), dict) else {}).get("candidate_entry_count", 0),
                "active_ontology_count": ((processing.get("agentic_enrichment") or {}) if isinstance(processing.get("agentic_enrichment"), dict) else {}).get("active_entry_count", 0),
                "agent_chunk_coverage_ratio": ((processing.get("agentic_enrichment") or {}) if isinstance(processing.get("agentic_enrichment"), dict) else {}).get("chunk_coverage_ratio", 0.0),
                "processing_status": processing_status,
                "processing_note": processing_note,
                "tags": processing.get("tags", []),
                "ontology": processing.get("ontology", {}),
                "entities": processing.get("entities", []),
                "article_refs": processing.get("article_refs", []),
                "law_refs": processing.get("law_refs", []),
                "case_refs": processing.get("case_refs", []),
                "dates": processing.get("dates", []),
                "money_mentions": processing.get("money_mentions", []),
            }
        )

    return {
        "project_id": project_id,
        "latest_job": latest_job,
        "jobs": jobs[:limit],
        "summary": {
            "documents": len(docs),
            "pages": len(pages),
            "paragraphs": len(paragraphs),
            "duplicate_documents": duplicate_count,
            "enrichment_jobs": len(enrichment_jobs),
            "ontology_candidate_entries": sum(
                int(job.get("candidate_entry_count", 0) or 0)
                for job in enrichment_jobs[:1]
            ),
            "ontology_active_entries": sum(
                int(job.get("active_entry_count", 0) or 0)
                for job in enrichment_jobs[:1]
            ),
            "by_doc_type": by_doc_type,
            "processing_status_counts": processing_status_counts,
        },
        "documents": serialized_docs,
        "processing_documents": processing_documents,
        "enrichment_jobs": enrichment_jobs[:limit],
    }


@router.get("/enrichment-jobs")
def list_enrichment_jobs(project_id: Optional[str] = None, limit: int = 20) -> dict:
    if corpus_pg.enabled():
        jobs = corpus_pg.list_enrichment_jobs(project_id=project_id, limit=limit)
    else:
        jobs = list(store.corpus_enrichment_jobs.values())
        if project_id:
            jobs = [job for job in jobs if matches_corpus_scope(job.get("project_id"), project_id)]
        jobs = sorted(jobs, key=lambda item: str(item.get("updated_at", "")), reverse=True)[:limit]
    return {"items": jobs}


@router.post("/enrichment-jobs/{jobId}/retry")
def retry_enrichment_job(jobId: str, payload: Dict[str, Any]) -> dict:
    target_type = str(payload.get("target_type", "")).strip().lower()
    target_ids = payload.get("target_ids")
    if target_type not in {"chunk", "document"}:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="target_type must be chunk or document")
    if not isinstance(target_ids, list) or not target_ids:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="target_ids must be a non-empty list")

    if corpus_pg.enabled():
        jobs = {str(job.get("job_id")): job for job in corpus_pg.list_enrichment_jobs(limit=200)}
        existing_job = jobs.get(jobId)
    else:
        existing_job = store.corpus_enrichment_jobs.get(jobId)
    if not isinstance(existing_job, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="enrichment job not found")

    project_id = str(existing_job.get("project_id", "")).strip()
    import_job_id = str(existing_job.get("import_job_id", "")).strip()
    snapshot = _current_corpus_snapshot(project_id)
    retried = retry_agentic_corpus_enrichment(
        project_id=project_id,
        import_job_id=import_job_id,
        documents=snapshot["documents"],
        pages=snapshot["pages"],
        paragraphs=snapshot["paragraphs"],
        chunk_search_documents=snapshot["chunk_search_documents"],
        relation_edges=snapshot["relation_edges"],
        existing_registry_entries=snapshot["registry_entries"],
        target_type=target_type,
        target_ids=[str(item) for item in target_ids if str(item).strip()],
    )
    merged_snapshot = {
        "documents": snapshot["documents"],
        "pages": snapshot["pages"],
        "paragraphs": snapshot["paragraphs"],
        "chunk_search_documents": snapshot["chunk_search_documents"],
        "relation_edges": snapshot["relation_edges"],
    }
    _merge_enrichment_into_result(merged_snapshot, retried)
    if corpus_pg.enabled():
        corpus_pg.persist_ingest_result(merged_snapshot)
    for document in retried.get("updated_documents", {}).values():
        if isinstance(document, dict):
            store.documents[str(document.get("document_id"))] = document
    for paragraph in retried.get("updated_paragraphs", {}).values():
        if isinstance(paragraph, dict):
            store.paragraphs[str(paragraph.get("paragraph_id"))] = paragraph
    for chunk_projection in retried.get("updated_chunk_projections", {}).values():
        if isinstance(chunk_projection, dict):
            store.chunk_search_documents[str(chunk_projection.get("chunk_id"))] = chunk_projection
    for edge in retried.get("projected_relation_edges", []):
        if isinstance(edge, dict):
            store.relation_edges[str(edge.get("edge_id"))] = edge
    _persist_enrichment_artifacts(retried)
    return {"status": "accepted", "job": retried.get("job", {})}


@router.get("/documents")
def list_documents(project_id: Optional[str] = None, limit: Optional[int] = None) -> dict:
    if limit is not None and limit < 1:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="limit must be >= 1")
    if limit is not None and limit > 5000:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="limit too large")

    if corpus_pg.enabled():
        rows = corpus_pg.list_documents(limit=limit, project_id=project_id)
        return {
            "items": [DocumentManifest(**d).model_dump(mode="json") for d in rows],
            "total": len(rows),
        }

    rows = list(store.documents.values())
    if project_id:
        rows = [d for d in rows if matches_corpus_scope(d.get("project_id"), project_id)]
    rows = sorted(rows, key=lambda d: str(d.get("document_id", "")))
    if limit is not None:
        rows = rows[:limit]
    return {
        "items": [DocumentManifest(**d).model_dump(mode="json") for d in rows],
        "total": len(rows),
    }


@router.post("/documents/{documentId}/reingest", status_code=202)
def reingest_document(documentId: str) -> dict:
    if corpus_pg.enabled():
        document = corpus_pg.get_document_with_processing(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        processing = document.get("processing", {}) if isinstance(document.get("processing"), dict) else {}
    else:
        document = store.documents.get(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        processing = document.get("processing", {}) if isinstance(document.get("processing"), dict) else {}

    source_file_path = _document_source_file_path(document, processing)
    if not source_file_path:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="source_pdf_path is missing")

    source_path = Path(source_file_path)
    if not source_path.exists():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="source pdf not found")

    parse_policy = str(processing.get("parse_policy", "balanced") or "balanced")
    dedupe_enabled = bool(processing.get("dedupe_enabled", True))
    project_id = document.get("project_id")
    pdf_id = str(document.get("pdf_id", "")).strip() or _sanitize_filename(source_path.stem)
    member_name = f"{_sanitize_filename(pdf_id)}.pdf"

    temp_zip_path = Path(tempfile.gettempdir()) / f"reingest_{uuid4().hex}.zip"
    try:
        with zipfile.ZipFile(temp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(source_path, arcname=member_name)
        return _run_import(
            project_id=project_id,
            blob_url=str(temp_zip_path),
            parse_policy=parse_policy,
            dedupe_enabled=dedupe_enabled,
        )
    finally:
        try:
            temp_zip_path.unlink(missing_ok=True)
        except Exception:
            pass


@router.get("/documents/{documentId}")
def get_document(documentId: str) -> dict:
    if corpus_pg.enabled():
        d = corpus_pg.get_document(documentId)
        if not d:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        return DocumentManifest(**d).model_dump(mode="json")

    if documentId not in store.documents:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
    d = store.documents[documentId]
    return DocumentManifest(**d).model_dump(mode="json")


@router.get("/documents/{documentId}/file")
def get_document_file(documentId: str) -> FileResponse:
    if corpus_pg.enabled():
        document = corpus_pg.get_document_with_processing(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        processing = document.get("processing", {}) if isinstance(document.get("processing"), dict) else {}
    else:
        document = store.documents.get(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        processing = document.get("processing", {}) if isinstance(document.get("processing"), dict) else {}

    source_file_path = _document_source_file_path(document, processing)
    if not source_file_path:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document file not found")
    path = Path(source_file_path)
    if not path.exists():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document file not found")
    filename = f"{document.get('pdf_id', documentId)}.pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get("/documents/{documentId}/detail")
def get_document_detail(documentId: str) -> dict:
    if corpus_pg.enabled():
        document_row = corpus_pg.get_document_with_processing(documentId)
        document = dict(document_row or {})
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        pages = corpus_pg.list_pages(document_id=documentId)
        chunks = corpus_pg.list_paragraphs(document_id=documentId)
        document_processing = document.pop("processing", {})
        document_ontology_view = corpus_pg.get_document_ontology_view(documentId) or {}
        chunk_assertions = corpus_pg.list_chunk_ontology_assertions(document_id=documentId)
    else:
        document = store.documents.get(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        document_processing = document.get("processing", {}) if isinstance(document.get("processing"), dict) else {}
        document_ontology_view = store.document_ontology_views.get(documentId, {})
        chunk_assertions = [
            row
            for row in store.chunk_ontology_assertions.values()
            if row.get("document_id") == documentId
        ]
        pages = [
            p
            for p in store.pages.values()
            if p.get("document_id") == documentId
        ]
        pages = sorted(
            pages,
            key=lambda p: (
                int(p.get("page_num", 0) or 0),
                str(p.get("page_id", "")),
            ),
        )
        chunks = [
            p
            for p in store.paragraphs.values()
            if p.get("document_id") == documentId
        ]
        chunks = sorted(
            chunks,
            key=lambda p: (
                int(p.get("paragraph_index", 0) or 0),
                str(p.get("paragraph_id", "")),
            ),
        )

    chunks_by_page: Dict[str, List[Dict[str, Any]]] = {}
    llm_status_counts: Dict[str, int] = {}
    assertions_by_page: Dict[str, List[Dict[str, Any]]] = {}
    for assertion in chunk_assertions:
        page_id = str(assertion.get("page_id", ""))
        assertions_by_page.setdefault(page_id, []).append(assertion)
    for chunk in chunks:
        page_id = str(chunk.get("page_id", ""))
        chunks_by_page.setdefault(page_id, []).append(ParagraphChunk(**chunk).model_dump(mode="json"))
        status = str(chunk.get("llm_status", "pending") or "pending")
        llm_status_counts[status] = llm_status_counts.get(status, 0) + 1

    page_items: List[Dict[str, Any]] = []
    for page in pages:
        page_id = str(page.get("page_id"))
        page_items.append(
            {
                "page_id": page_id,
                "source_page_id": page.get("source_page_id"),
                "page_num": page.get("page_num", 0),
                "text": page.get("text", ""),
                "chunks": chunks_by_page.get(page_id, []),
                "chunk_count": len(chunks_by_page.get(page_id, [])),
                "ontology_assertions": assertions_by_page.get(page_id, []),
            }
        )

    return {
        "document": DocumentManifest(**document).model_dump(mode="json"),
        "document_processing": document_processing,
        "document_ontology_view": document_ontology_view,
        "summary": {
            "page_count": len(page_items),
            "chunk_count": len(chunks),
            "llm_status_counts": llm_status_counts,
            "ontology_assertion_count": len(chunk_assertions),
        },
        "pages": page_items,
        "file_url": f"/v1/corpus/documents/{documentId}/file",
    }


@router.post("/documents/{documentId}/process-chunks-llm")
async def process_chunks_llm(documentId: str, payload: Dict[str, Any]) -> dict:
    force = bool(payload.get("force", False))
    reclassify_document = bool(payload.get("reclassify_document", True))

    if corpus_pg.enabled():
        document_row = corpus_pg.get_document_with_processing(documentId)
        document = dict(document_row or {})
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        chunks = corpus_pg.list_paragraphs(document_id=documentId)
        _ = document.pop("processing", {})
    else:
        document = store.documents.get(documentId)
        if not document:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document not found")
        chunks = [
            p
            for p in store.paragraphs.values()
            if p.get("document_id") == documentId
        ]
        chunks = sorted(
            chunks,
            key=lambda p: (
                int(p.get("paragraph_index", 0) or 0),
                str(p.get("paragraph_id", "")),
            ),
        )

    if not chunks:
        return {
            "document_id": documentId,
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "reason": "no_chunks",
        }

    model_name = chunk_llm_client.config.deployment or "azure-openai"
    if not chunk_llm_client.config.enabled:
        raise HTTPException(status_code=422, detail="azure llm is not configured")

    processed = 0
    skipped = 0
    failed = 0
    document_processed = False
    document_failed = False
    prompt_tokens = 0
    completion_tokens = 0

    if reclassify_document:
        context_text = _document_context_from_chunks(chunks)
        if context_text.strip():
            try:
                doc_result = await _run_document_llm(document, context_text)
                usage = doc_result.get("usage", {})
                prompt_tokens += int(usage.get("prompt_tokens", 0))
                completion_tokens += int(usage.get("completion_tokens", 0))
                if corpus_pg.enabled():
                    corpus_pg.update_document_llm(
                        documentId,
                        status="completed",
                        llm_payload=doc_result.get("payload", {}),
                        model=model_name,
                        error=None,
                    )
                else:
                    processing = document.setdefault("processing", {})
                    if not isinstance(processing, dict):
                        processing = {}
                        document["processing"] = processing
                    processing["llm_document_status"] = "completed"
                    processing["llm_document_model"] = model_name
                    processing["llm_document"] = doc_result.get("payload", {})
                document_processed = True
            except Exception as exc:
                document_failed = True
                if corpus_pg.enabled():
                    corpus_pg.update_document_llm(
                        documentId,
                        status="failed",
                        llm_payload={},
                        model=model_name,
                        error=str(exc)[:300],
                    )
                else:
                    processing = document.setdefault("processing", {})
                    if not isinstance(processing, dict):
                        processing = {}
                        document["processing"] = processing
                    processing["llm_document_status"] = "failed"
                    processing["llm_document_error"] = str(exc)[:300]

    for chunk in chunks:
        paragraph_id = str(chunk.get("paragraph_id"))
        status = str(chunk.get("llm_status", "pending") or "pending")
        if not force and status == "completed":
            skipped += 1
            continue
        text = str(chunk.get("text", "") or "").strip()
        if not text:
            failed += 1
            if corpus_pg.enabled():
                corpus_pg.update_paragraph_llm(
                    paragraph_id,
                    status="failed",
                    error="empty_text",
                    payload={},
                    model=model_name,
                )
            else:
                chunk["llm_status"] = "failed"
                chunk["llm_error"] = "empty_text"
                chunk["llm_model"] = model_name
                chunk["llm_payload"] = {}
            continue
        try:
            result = await _run_chunk_llm(text)
            usage = result.get("usage", {})
            prompt_tokens += int(usage.get("prompt_tokens", 0))
            completion_tokens += int(usage.get("completion_tokens", 0))
            if corpus_pg.enabled():
                corpus_pg.update_paragraph_llm(
                    paragraph_id,
                    status="completed",
                    summary=str(result.get("summary", "")),
                    section_type=str(result.get("section_type", "other")),
                    tags=list(result.get("tags", [])),
                    payload=result.get("payload", {}),
                    model=model_name,
                    error=None,
                )
            else:
                chunk["llm_status"] = "completed"
                chunk["llm_summary"] = str(result.get("summary", ""))
                chunk["llm_section_type"] = str(result.get("section_type", "other"))
                chunk["llm_tags"] = list(result.get("tags", []))
                chunk["llm_payload"] = result.get("payload", {})
                chunk["llm_model"] = model_name
                chunk["llm_error"] = None
            processed += 1
        except Exception as exc:
            failed += 1
            if corpus_pg.enabled():
                corpus_pg.update_paragraph_llm(
                    paragraph_id,
                    status="failed",
                    error=str(exc)[:300],
                    payload={},
                    model=model_name,
                )
            else:
                chunk["llm_status"] = "failed"
                chunk["llm_error"] = str(exc)[:300]
                chunk["llm_model"] = model_name
                chunk["llm_payload"] = {}

    return {
        "document_id": documentId,
        "document_reclassified": document_processed,
        "document_failed": document_failed,
        "total": len(chunks),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "model": model_name,
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


@router.get("/pages/{pageId}")
def get_page(pageId: str) -> dict:
    if corpus_pg.enabled():
        page = corpus_pg.get_page(pageId)
        if not page:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="page not found")
        return {
            "page_id": page["page_id"],
            "text": page["text"],
            "page_class": page.get("page_class", "body"),
            "entities": page.get("entities", []),
            "source_page_id": page.get("source_page_id"),
        }

    if pageId not in store.pages:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="page not found")
    page = store.pages[pageId]
    return {
        "page_id": page["page_id"],
        "text": page["text"],
        "page_class": page.get("page_class", "body"),
        "entities": page.get("entities", []),
        "source_page_id": page.get("source_page_id"),
    }


@router.get("/paragraphs/{paragraphId}")
def get_paragraph(paragraphId: str) -> dict:
    if corpus_pg.enabled():
        para = corpus_pg.get_paragraph(paragraphId)
        if not para:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="paragraph not found")
        return ParagraphChunk(**para).model_dump(mode="json")

    if paragraphId not in store.paragraphs:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="paragraph not found")
    para = store.paragraphs[paragraphId]
    return ParagraphChunk(**para).model_dump(mode="json")


@router.get("/chunks")
def list_chunks(
    project_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    if limit is not None and limit < 1:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="limit must be >= 1")
    if limit is not None and limit > 50000:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="limit too large")

    if corpus_pg.enabled():
        rows = corpus_pg.list_paragraphs(project_id=project_id, document_id=document_id, limit=limit)
    else:
        rows = list(store.paragraphs.values())
        if project_id:
            rows = [p for p in rows if matches_corpus_scope(p.get("project_id"), project_id)]
        if document_id:
            rows = [p for p in rows if p.get("document_id") == document_id]
        rows = sorted(
            rows,
            key=lambda p: (
                str(p.get("document_id", "")),
                int(p.get("paragraph_index", 0) or 0),
                str(p.get("paragraph_id", "")),
            ),
        )
        if limit is not None:
            rows = rows[:limit]

    return {
        "project_id": project_id,
        "document_id": document_id,
        "items": [ParagraphChunk(**p).model_dump(mode="json") for p in rows],
        "total": len(rows),
    }


@router.post("/case-judgment/router-runs", status_code=202)
def run_case_judgment_router(payload: Dict[str, Any]) -> dict:
    document_id = str(payload.get("document_id", "")).strip()
    if not document_id:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="document_id is required")

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    run_id = str(payload.get("run_id") or uuid4())
    document, pages, _paragraphs = _load_case_document_context(document_id)
    routing = run_case_judgment_router_pipeline(
        document=document,
        pages=pages,
        metadata=metadata,
        llm_client=chunk_llm_client,
    )
    model_name, reasoning_effort = choose_router_model()
    run_row = _case_create_run(
        {
            "run_id": run_id,
            "document_id": document_id,
            "pipeline_name": CASE_ROUTER_PIPELINE_NAME,
            "pipeline_version": CASE_ROUTER_PIPELINE_VERSION,
            "schema_version": CASE_JUDGMENT_SCHEMA_VERSION,
            "prompt_version": CASE_ROUTER_PROMPT_VERSION,
            "model_name": model_name,
            "model_reasoning_effort": reasoning_effort,
            "parser_version": CASE_ROUTER_PIPELINE_VERSION,
            "source": str(payload.get("source", "pipeline")),
            "status": "completed",
            "route_status": routing.get("route_status", "routed"),
            "token_input": int(routing.get("token_usage", {}).get("prompt_tokens", 0) or 0),
            "token_output": int(routing.get("token_usage", {}).get("completion_tokens", 0) or 0),
            "llm_calls": int(routing.get("llm_calls", 0) or 0),
            "source_document_revision": str(document.get("content_hash") or document.get("canonical_doc_id") or ""),
            "completed_at": None,
            "metadata": {"routing": routing},
        }
    )
    return {
        "status": "accepted",
        "run": run_row,
        "routing": routing,
    }


@router.post("/case-judgment/extraction-runs", status_code=202)
def run_case_judgment_extraction(payload: Dict[str, Any]) -> dict:
    document_id = str(payload.get("document_id", "")).strip()
    if not document_id:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="document_id is required")
    use_llm = bool(payload.get("use_llm", True))
    auto_promote = bool(payload.get("auto_promote", False))
    max_chunks_raw = payload.get("max_chunks")
    max_chunks = int(max_chunks_raw) if isinstance(max_chunks_raw, int) and max_chunks_raw > 0 else None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    document, pages, paragraphs = _load_case_document_context(document_id)
    extraction = run_case_judgment_extraction_pipeline(
        document=document,
        pages=pages,
        paragraphs=paragraphs,
        metadata=metadata,
        use_llm=use_llm,
        llm_client=chunk_llm_client,
        max_chunks=max_chunks,
    )

    run_id = str(payload.get("run_id") or uuid4())
    artifact_version = _next_case_artifact_version(document_id, CASE_JUDGMENT_SCHEMA_VERSION)
    qc_blocking = bool(extraction.get("qc", {}).get("blocking_failed", False))
    doc_validation = str(extraction.get("document_extraction", {}).get("validation_status", "failed"))
    chunk_validation = str(extraction.get("chunk_extraction", {}).get("validation_status", "failed"))

    run_status = "completed"
    if qc_blocking:
        run_status = "qc_failed"
    elif doc_validation == "failed" or chunk_validation == "failed":
        run_status = "partial"

    document_model, document_reasoning = choose_document_model()
    chunk_model, chunk_reasoning = choose_chunk_model()
    run_row = _case_create_run(
        {
            "run_id": run_id,
            "document_id": document_id,
            "pipeline_name": CASE_DOCUMENT_PIPELINE_NAME,
            "pipeline_version": CASE_DOCUMENT_PIPELINE_VERSION,
            "schema_version": CASE_JUDGMENT_SCHEMA_VERSION,
            "prompt_version": f"{CASE_DOCUMENT_PROMPT_VERSION}+{CASE_CHUNK_PROMPT_VERSION}",
            "model_name": f"document:{document_model};chunk:{chunk_model}",
            "model_reasoning_effort": f"document:{document_reasoning};chunk:{chunk_reasoning}",
            "parser_version": CASE_DOCUMENT_PIPELINE_VERSION,
            "source": str(payload.get("source", "pipeline")),
            "status": run_status,
            "route_status": str(extraction.get("routing", {}).get("route_status", "unknown")),
            "token_input": int(extraction.get("token_usage", {}).get("prompt_tokens", 0) or 0),
            "token_output": int(extraction.get("token_usage", {}).get("completion_tokens", 0) or 0),
            "llm_calls": int(extraction.get("llm_calls", 0) or 0),
            "source_document_revision": str(document.get("content_hash") or document.get("canonical_doc_id") or ""),
            "metadata": {
                "routing": extraction.get("routing", {}),
                "document_validation_errors": extraction.get("document_extraction", {}).get("validation_errors", []),
                "chunk_validation_errors_count": len(extraction.get("chunk_extraction", {}).get("validation_errors", [])),
                "qc_blocking_failed": qc_blocking,
            },
        }
    )

    document_extraction_id = str(payload.get("document_extraction_id") or uuid4())
    document_payload = extraction.get("document_extraction", {}).get("payload", {})
    if not isinstance(document_payload, dict):
        document_payload = {}

    document_row = _case_upsert_document_extraction(
        {
            "document_extraction_id": document_extraction_id,
            "run_id": run_id,
            "document_id": document_id,
            "schema_version": CASE_JUDGMENT_SCHEMA_VERSION,
            "artifact_version": artifact_version,
            "is_active": False,
            "supersedes_document_extraction_id": None,
            "document_subtype": document_payload.get("document_subtype"),
            "proceeding_no": document_payload.get("proceeding_no"),
            "case_cluster_id": document_payload.get("case_cluster_id"),
            "court_name": document_payload.get("court_name"),
            "court_level": document_payload.get("court_level"),
            "decision_date": document_payload.get("decision_date"),
            "page_count": document_payload.get("page_count"),
            "confidence_score": extraction.get("document_extraction", {}).get("confidence_score"),
            "validation_status": extraction.get("document_extraction", {}).get("validation_status", "failed"),
            "payload": document_payload,
        }
    )

    paragraph_by_id = {str(item.get("paragraph_id", "")): item for item in paragraphs}
    chunk_rows: List[Dict[str, Any]] = []
    for chunk_payload in extraction.get("chunk_extraction", {}).get("chunks", []):
        if not isinstance(chunk_payload, dict):
            continue
        chunk_external_id = str(chunk_payload.get("chunk_id", "")).strip()
        paragraph = paragraph_by_id.get(chunk_external_id, {})
        chunk_rows.append(
            {
                "chunk_extraction_id": str(uuid4()),
                "run_id": run_id,
                "document_extraction_id": document_extraction_id,
                "paragraph_id": paragraph.get("paragraph_id") or chunk_external_id or None,
                "page_id": paragraph.get("page_id") or chunk_payload.get("page_id_internal") or None,
                "document_id": document_id,
                "schema_version": CASE_JUDGMENT_SCHEMA_VERSION,
                "artifact_version": artifact_version,
                "chunk_external_id": chunk_external_id or str(uuid4()),
                "chunk_type": chunk_payload.get("chunk_type"),
                "section_kind_case": chunk_payload.get("section_kind_case"),
                "paragraph_no": chunk_payload.get("paragraph_no"),
                "page_number_1": chunk_payload.get("page_number_1"),
                "order_effect_label": chunk_payload.get("order_effect_label"),
                "ground_owner": chunk_payload.get("ground_owner"),
                "ground_no": chunk_payload.get("ground_no"),
                "confidence_score": 1.0 if extraction.get("chunk_extraction", {}).get("validation_status") == "passed" else 0.5,
                "validation_status": extraction.get("chunk_extraction", {}).get("validation_status", "failed"),
                "payload": chunk_payload,
            }
        )
    persisted_chunks = _case_upsert_chunk_extractions(chunk_rows)

    qc_rows: List[Dict[str, Any]] = []
    for item in extraction.get("qc", {}).get("checks", []):
        if not isinstance(item, dict):
            continue
        qc_rows.append(
            {
                "qc_result_id": str(item.get("qc_result_id") or uuid4()),
                "run_id": run_id,
                "document_id": document_id,
                "qc_stage": item.get("qc_stage", "unknown"),
                "status": item.get("status", "warning"),
                "severity": item.get("severity", "medium"),
                "message": item.get("message", "qc check"),
                "details": item.get("details", {}),
            }
        )
    persisted_qc = _case_upsert_qc_results(qc_rows)

    projection_summary: Dict[str, Any] = {}
    promoted = False
    if auto_promote and not qc_blocking and doc_validation != "failed" and chunk_validation != "failed":
        _case_activate_document_extraction(document_extraction_id)
        promoted = True
        projection_summary = _persist_case_projection(
            document_id=document_id,
            chunk_payloads=[row.get("payload", {}) for row in persisted_chunks if isinstance(row.get("payload"), dict)],
            document_payload=document_payload,
        )

    return {
        "status": "accepted",
        "run": run_row,
        "document_extraction": document_row,
        "chunks_count": len(persisted_chunks),
        "qc_count": len(persisted_qc),
        "qc_blocking_failed": qc_blocking,
        "auto_promoted": promoted,
        "projection_summary": projection_summary,
    }


@router.get("/case-judgment/runs/{runId}")
def get_case_judgment_run(runId: str) -> dict:
    run = _case_get_run(runId)
    if not isinstance(run, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="case extraction run not found")
    documents = _case_list_document_extractions(run_id=runId, limit=200)
    chunks_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for row in documents:
        document_extraction_id = str(row.get("document_extraction_id", ""))
        chunks_by_doc[document_extraction_id] = _case_list_chunk_extractions(
            document_extraction_id=document_extraction_id,
            limit=10000,
        )
    qc = _case_list_qc_results(run_id=runId, limit=1000)
    return {
        "run": run,
        "documents": documents,
        "chunks_by_document_extraction_id": chunks_by_doc,
        "qc_results": qc,
    }


@router.post("/case-judgment/document-extractions/{documentExtractionId}/promote")
def promote_case_document_extraction(documentExtractionId: str, payload: Dict[str, Any]) -> dict:
    force = bool(payload.get("force", False))
    document_row = _case_get_document_extraction(documentExtractionId)
    if not isinstance(document_row, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document extraction not found")

    run_id = str(document_row.get("run_id", ""))
    document_id = str(document_row.get("document_id", ""))
    qc_rows = _case_list_qc_results(run_id=run_id, limit=1000)
    blocking = [
        row
        for row in qc_rows
        if str(row.get("status", "")) == "failed" and str(row.get("severity", "")) in {"high", "critical"}
    ]
    if blocking and not force:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="blocking QC failures present; set force=true to override",
        )

    activated = _case_activate_document_extraction(documentExtractionId)
    if not isinstance(activated, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document extraction not found")
    chunks = _case_list_chunk_extractions(document_extraction_id=documentExtractionId, limit=20000)
    projection_summary = _persist_case_projection(
        document_id=document_id,
        chunk_payloads=[row.get("payload", {}) for row in chunks if isinstance(row.get("payload"), dict)],
        document_payload=document_row.get("payload") if isinstance(document_row.get("payload"), dict) else None,
    )
    return {
        "status": "ok",
        "active_document_extraction_id": documentExtractionId,
        "projection_summary": projection_summary,
        "blocking_qc_count": len(blocking),
    }


@router.post("/case-judgment/document-extractions/{documentExtractionId}/revert")
def revert_case_document_extraction(documentExtractionId: str, payload: Dict[str, Any]) -> dict:
    target_document_extraction_id = str(payload.get("target_document_extraction_id", "")).strip()
    if not target_document_extraction_id:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="target_document_extraction_id is required",
        )
    current = _case_get_document_extraction(documentExtractionId)
    target = _case_get_document_extraction(target_document_extraction_id)
    if not isinstance(current, dict) or not isinstance(target, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="document extraction not found")
    if str(current.get("document_id", "")) != str(target.get("document_id", "")):
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="target document mismatch")
    if str(current.get("schema_version", "")) != str(target.get("schema_version", "")):
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="target schema mismatch")

    activated = _case_activate_document_extraction(target_document_extraction_id)
    if not isinstance(activated, dict):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="target document extraction not found")
    chunks = _case_list_chunk_extractions(document_extraction_id=target_document_extraction_id, limit=20000)
    projection_summary = _persist_case_projection(
        document_id=str(target.get("document_id", "")),
        chunk_payloads=[row.get("payload", {}) for row in chunks if isinstance(row.get("payload"), dict)],
        document_payload=target.get("payload") if isinstance(target.get("payload"), dict) else None,
    )
    return {
        "status": "ok",
        "active_document_extraction_id": target_document_extraction_id,
        "projection_summary": projection_summary,
    }


def _matches_filters(chunk_projection: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
    if not filters:
        return True
    for key, value in filters.items():
        if value is None:
            continue
        if key == "edge_type":
            edge_types = chunk_projection.get("edge_types", [])
            if value not in edge_types:
                return False
            continue
        projected = chunk_projection.get(key)
        if isinstance(projected, list):
            if value not in projected:
                return False
            continue
        if projected != value:
            return False
    return True


@router.post("/search")
def search(payload: CorpusSearchRequest) -> dict:
    filters = payload.filters.model_dump(exclude_none=True) if payload.filters else None
    query = payload.query
    top_k = payload.top_k
    project_id = payload.project_id

    if corpus_pg.enabled():
        return {"items": corpus_pg.search(project_id=project_id, query=query, top_k=top_k, filters=filters)}

    scored_rows: List[Dict[str, Any]] = []
    if store.feature_flags.get("canonical_chunk_model_v1", True) and store.chunk_search_documents:
        for chunk_projection in store.chunk_search_documents.values():
            paragraph = store.paragraphs.get(chunk_projection["chunk_id"])
            if not paragraph:
                continue
            if not matches_corpus_scope(paragraph.get("project_id"), project_id):
                continue
            if not _matches_filters(chunk_projection, filters):
                continue
            score = score_candidate(query, chunk_projection.get("retrieval_text", chunk_projection.get("text_clean", "")))
            if score <= 0:
                continue
            scored_rows.append({"projection": chunk_projection, "paragraph": paragraph, "score": score})
    else:
        for paragraph in store.paragraphs.values():
            if not matches_corpus_scope(paragraph.get("project_id"), project_id):
                continue
            pseudo_projection = {
                "chunk_id": paragraph.get("paragraph_id"),
                "document_id": paragraph.get("document_id"),
                "page_id": paragraph.get("page_id"),
                "page_number": 0,
                "doc_type": "other",
                "text_clean": paragraph.get("text", ""),
                "retrieval_text": paragraph.get("text", ""),
                "edge_types": [],
            }
            if not _matches_filters(pseudo_projection, filters):
                continue
            score = score_candidate(query, paragraph.get("text", ""))
            if score <= 0:
                continue
            scored_rows.append({"projection": pseudo_projection, "paragraph": paragraph, "score": score})

    # Backward-compatible fallback for low-quality corpora with no lexical match.
    if not scored_rows:
        for paragraph in store.paragraphs.values():
            if not matches_corpus_scope(paragraph.get("project_id"), project_id):
                continue
            projection = store.chunk_search_documents.get(paragraph.get("paragraph_id"), {})
            if projection and not _matches_filters(projection, filters):
                continue
            scored_rows.append({"projection": projection, "paragraph": paragraph, "score": 0.01})
            if len(scored_rows) >= top_k:
                break

    scored_rows.sort(key=lambda row: row["score"], reverse=True)
    items = []
    for row in scored_rows[:top_k]:
        projection = row["projection"]
        paragraph = row["paragraph"]
        page_id = paragraph["page_id"]
        page = store.pages.get(page_id, {})
        source_page_id = page.get("source_page_id", "unknown_0")
        source_page_ref = source_page_id.split("_")
        pdf_id = source_page_ref[0]
        page_num = int(source_page_ref[1]) if len(source_page_ref) > 1 and source_page_ref[1].isdigit() else 0
        items.append(
            {
                "paragraph_id": paragraph["paragraph_id"],
                "page_id": page_id,
                "score": round(float(row["score"]), 4),
                "snippet": projection.get("text_clean", paragraph.get("text", ""))[:180],
                "source_page_id": source_page_id,
                "pdf_id": pdf_id,
                "page_num": page_num,
                "document_id": paragraph.get("document_id"),
                "chunk_projection": projection,
            }
        )
    return {"items": items}
