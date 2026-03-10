"""PostgreSQL persistence for corpus ingestion artifacts."""

from __future__ import annotations

import os
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4

from packages.contracts.corpus_scope import (
    corpus_scope_ids,
    normalize_corpus_record_project_id,
    resolve_corpus_import_project_id,
)
from packages.retrieval.search import score_candidate

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except Exception:  # pragma: no cover - graceful fallback when dependency missing
    psycopg = None
    dict_row = None
    Json = None


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_SCHEMA_READY = False
_SCHEMA_LOCK = Lock()


def enabled() -> bool:
    return bool(DATABASE_URL and psycopg is not None)


def _connect():
    if not enabled():
        raise RuntimeError("postgres corpus storage is not enabled")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _sanitize_pg_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_pg_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_pg_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_pg_value(item) for key, item in value.items()}
    return value


def _scope_filter_clause(column: str, project_id: Optional[str], params: List[Any]) -> str:
    normalized = str(project_id or "").strip()
    if not normalized:
        return ""
    params.append(list(corpus_scope_ids(normalized)))
    return f"{column} = ANY(%s)"


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


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or not enabled():
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY or not enabled():
            return
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_import_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    blob_url TEXT NOT NULL,
                    parse_policy TEXT NOT NULL,
                    dedupe_enabled BOOLEAN NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_documents (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    pdf_id TEXT NOT NULL,
                    canonical_doc_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    title TEXT,
                    citation_title TEXT,
                    law_number TEXT,
                    case_id TEXT,
                    year INTEGER,
                    edition_date TEXT,
                    page_count INTEGER NOT NULL,
                    duplicate_group_id TEXT,
                    status TEXT NOT NULL,
                    processing JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_pages (
                    page_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    pdf_id TEXT NOT NULL,
                    source_page_id TEXT NOT NULL,
                    page_num INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    page_class TEXT NOT NULL,
                    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_paragraphs (
                    paragraph_id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    paragraph_index INTEGER NOT NULL,
                    heading_path JSONB NOT NULL DEFAULT '[]'::jsonb,
                    text TEXT NOT NULL,
                    summary_tag TEXT,
                    paragraph_class TEXT NOT NULL,
                    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
                    article_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    law_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    case_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    dates JSONB NOT NULL DEFAULT '[]'::jsonb,
                    money_mentions JSONB NOT NULL DEFAULT '[]'::jsonb,
                    version_lineage_id TEXT,
                    embedding_vector_id TEXT,
                    llm_status TEXT,
                    llm_summary TEXT,
                    llm_section_type TEXT,
                    llm_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    llm_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    llm_model TEXT,
                    llm_error TEXT,
                    llm_updated_at TIMESTAMPTZ
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_enrichment_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    import_job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_ontology_registry (
                    entry_id TEXT PRIMARY KEY,
                    entry_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_chunk_ontology_assertions (
                    assertion_id TEXT PRIMARY KEY,
                    paragraph_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source_page_id TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_document_ontology_views (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_chunk_search_documents (
                    chunk_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS corpus_relation_edges (
                    edge_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_document_id TEXT,
                    source_object_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_documents_project
                ON corpus_documents(project_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_pages_project
                ON corpus_pages(project_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_paragraphs_project
                ON corpus_paragraphs(project_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_jobs_project
                ON corpus_import_jobs(project_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_enrichment_jobs_project
                ON corpus_enrichment_jobs(project_id, updated_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_chunk_ontology_assertions_doc
                ON corpus_chunk_ontology_assertions(document_id, page_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_chunk_search_documents_project
                ON corpus_chunk_search_documents(project_id, document_id, page_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_corpus_relation_edges_project
                ON corpus_relation_edges(project_id, source_document_id, edge_type);
                """
            )
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_status TEXT;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_summary TEXT;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_section_type TEXT;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_tags JSONB NOT NULL DEFAULT '[]'::jsonb;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_payload JSONB NOT NULL DEFAULT '{}'::jsonb;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_model TEXT;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_error TEXT;")
            cur.execute("ALTER TABLE corpus_paragraphs ADD COLUMN IF NOT EXISTS llm_updated_at TIMESTAMPTZ;")
        _SCHEMA_READY = True


def create_import_job(
    project_id: str,
    blob_url: str,
    parse_policy: str,
    dedupe_enabled: bool,
    job_id: Optional[str] = None,
) -> str:
    ensure_schema()
    project_id = resolve_corpus_import_project_id(project_id)
    if not job_id:
        job_id = str(uuid4())
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO corpus_import_jobs (
                job_id, project_id, blob_url, parse_policy, dedupe_enabled, status
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                blob_url = EXCLUDED.blob_url,
                parse_policy = EXCLUDED.parse_policy,
                dedupe_enabled = EXCLUDED.dedupe_enabled
            """,
            (job_id, project_id, blob_url, parse_policy, dedupe_enabled, "queued"),
        )
    return job_id


def update_import_job_status(job_id: str, status: str) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corpus_import_jobs SET status = %s WHERE job_id = %s",
            (status, job_id),
        )


def persist_ingest_result(result: Dict[str, Any]) -> None:
    ensure_schema()
    docs = result.get("documents", [])
    pages = result.get("pages", [])
    paragraphs = result.get("paragraphs", [])
    chunk_search_documents = result.get("chunk_search_documents", [])
    relation_edges = result.get("relation_edges", [])
    document_project_map = {
        str(item.get("document_id", "")): normalize_corpus_record_project_id(item.get("project_id"))
        for item in docs
        if str(item.get("document_id", "")).strip()
    }
    page_project_map = {
        str(item.get("page_id", "")): normalize_corpus_record_project_id(item.get("project_id"))
        for item in pages
        if str(item.get("page_id", "")).strip()
    }
    page_document_map = {
        str(item.get("page_id", "")): str(item.get("document_id", "")).strip()
        for item in pages
        if str(item.get("page_id", "")).strip()
    }
    paragraph_project_map = {
        str(item.get("paragraph_id", "")): normalize_corpus_record_project_id(item.get("project_id"))
        for item in paragraphs
        if str(item.get("paragraph_id", "")).strip()
    }
    paragraph_document_map = {
        str(item.get("paragraph_id", "")): str(item.get("document_id", "")).strip()
        for item in paragraphs
        if str(item.get("paragraph_id", "")).strip()
    }
    default_project_id = next(
        (
            candidate
            for candidate in [
                *document_project_map.values(),
                *page_project_map.values(),
                *paragraph_project_map.values(),
            ]
            if candidate
        ),
        resolve_corpus_import_project_id(),
    )
    with _connect() as conn, conn.cursor() as cur:
        for doc in docs:
            cur.execute(
                """
                INSERT INTO corpus_documents (
                    document_id, project_id, pdf_id, canonical_doc_id, content_hash, doc_type,
                    title, citation_title, law_number, case_id, year, edition_date, page_count,
                    duplicate_group_id, status, processing
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (document_id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    pdf_id = EXCLUDED.pdf_id,
                    canonical_doc_id = EXCLUDED.canonical_doc_id,
                    content_hash = EXCLUDED.content_hash,
                    doc_type = EXCLUDED.doc_type,
                    title = EXCLUDED.title,
                    citation_title = EXCLUDED.citation_title,
                    law_number = EXCLUDED.law_number,
                    case_id = EXCLUDED.case_id,
                    year = EXCLUDED.year,
                    edition_date = EXCLUDED.edition_date,
                    page_count = EXCLUDED.page_count,
                    duplicate_group_id = EXCLUDED.duplicate_group_id,
                    status = EXCLUDED.status,
                    processing = EXCLUDED.processing
                """,
                (
                    _sanitize_pg_value(doc.get("document_id")),
                    normalize_corpus_record_project_id(doc.get("project_id")),
                    _sanitize_pg_value(doc.get("pdf_id")),
                    _sanitize_pg_value(doc.get("canonical_doc_id")),
                    _sanitize_pg_value(doc.get("content_hash")),
                    _sanitize_pg_value(doc.get("doc_type", "other")),
                    _sanitize_pg_value(doc.get("title")),
                    _sanitize_pg_value(doc.get("citation_title")),
                    _sanitize_pg_value(doc.get("law_number")),
                    _sanitize_pg_value(doc.get("case_id")),
                    doc.get("year"),
                    _sanitize_pg_value(doc.get("edition_date")),
                    int(doc.get("page_count", 1) or 1),
                    _sanitize_pg_value(doc.get("duplicate_group_id")),
                    _sanitize_pg_value(doc.get("status", "parsed")),
                    Json(_sanitize_pg_value(_json_obj(doc.get("processing")))),
                ),
            )

        for page in pages:
            cur.execute(
                """
                INSERT INTO corpus_pages (
                    page_id, document_id, project_id, pdf_id, source_page_id, page_num,
                    text, page_class, entities, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (page_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    project_id = EXCLUDED.project_id,
                    pdf_id = EXCLUDED.pdf_id,
                    source_page_id = EXCLUDED.source_page_id,
                    page_num = EXCLUDED.page_num,
                    text = EXCLUDED.text,
                    page_class = EXCLUDED.page_class,
                    entities = EXCLUDED.entities,
                    created_at = EXCLUDED.created_at
                """,
                (
                    _sanitize_pg_value(page.get("page_id")),
                    _sanitize_pg_value(page.get("document_id")),
                    normalize_corpus_record_project_id(page.get("project_id")),
                    _sanitize_pg_value(page.get("pdf_id")),
                    _sanitize_pg_value(page.get("source_page_id")),
                    int(page.get("page_num", 0) or 0),
                    _sanitize_pg_value(page.get("text", "")),
                    _sanitize_pg_value(page.get("page_class", "body")),
                    Json(_sanitize_pg_value(_json_list(page.get("entities")))),
                    _sanitize_pg_value(page.get("created_at")),
                ),
            )

        for para in paragraphs:
            cur.execute(
                """
                INSERT INTO corpus_paragraphs (
                    paragraph_id, page_id, document_id, project_id, paragraph_index, heading_path,
                    text, summary_tag, paragraph_class, entities, article_refs, law_refs, case_refs,
                    dates, money_mentions, version_lineage_id, embedding_vector_id,
                    llm_status, llm_summary, llm_section_type, llm_tags, llm_payload, llm_model, llm_error, llm_updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (paragraph_id) DO UPDATE SET
                    page_id = EXCLUDED.page_id,
                    document_id = EXCLUDED.document_id,
                    project_id = EXCLUDED.project_id,
                    paragraph_index = EXCLUDED.paragraph_index,
                    heading_path = EXCLUDED.heading_path,
                    text = EXCLUDED.text,
                    summary_tag = EXCLUDED.summary_tag,
                    paragraph_class = EXCLUDED.paragraph_class,
                    entities = EXCLUDED.entities,
                    article_refs = EXCLUDED.article_refs,
                    law_refs = EXCLUDED.law_refs,
                    case_refs = EXCLUDED.case_refs,
                    dates = EXCLUDED.dates,
                    money_mentions = EXCLUDED.money_mentions,
                    version_lineage_id = EXCLUDED.version_lineage_id,
                    embedding_vector_id = EXCLUDED.embedding_vector_id,
                    llm_status = EXCLUDED.llm_status,
                    llm_summary = EXCLUDED.llm_summary,
                    llm_section_type = EXCLUDED.llm_section_type,
                    llm_tags = EXCLUDED.llm_tags,
                    llm_payload = EXCLUDED.llm_payload,
                    llm_model = EXCLUDED.llm_model,
                    llm_error = EXCLUDED.llm_error,
                    llm_updated_at = EXCLUDED.llm_updated_at
                """,
                (
                    _sanitize_pg_value(para.get("paragraph_id")),
                    _sanitize_pg_value(para.get("page_id")),
                    _sanitize_pg_value(para.get("document_id")),
                    normalize_corpus_record_project_id(para.get("project_id")),
                    int(para.get("paragraph_index", 0) or 0),
                    Json(_sanitize_pg_value(_json_list(para.get("heading_path")))),
                    _sanitize_pg_value(para.get("text", "")),
                    _sanitize_pg_value(para.get("summary_tag")),
                    _sanitize_pg_value(para.get("paragraph_class", "body")),
                    Json(_sanitize_pg_value(_json_list(para.get("entities")))),
                    Json(_sanitize_pg_value(_json_list(para.get("article_refs")))),
                    Json(_sanitize_pg_value(_json_list(para.get("law_refs")))),
                    Json(_sanitize_pg_value(_json_list(para.get("case_refs")))),
                    Json(_sanitize_pg_value(_json_list(para.get("dates")))),
                    Json(_sanitize_pg_value(_json_list(para.get("money_mentions")))),
                    _sanitize_pg_value(para.get("version_lineage_id")),
                    _sanitize_pg_value(para.get("embedding_vector_id")),
                    _sanitize_pg_value(para.get("llm_status", "pending")),
                    _sanitize_pg_value(para.get("llm_summary")),
                    _sanitize_pg_value(para.get("llm_section_type")),
                    Json(_sanitize_pg_value(_json_list(para.get("llm_tags")))),
                    Json(_sanitize_pg_value(_json_obj(para.get("llm_payload")))),
                    _sanitize_pg_value(para.get("llm_model")),
                    _sanitize_pg_value(para.get("llm_error")),
                    _sanitize_pg_value(para.get("llm_updated_at")),
                ),
            )

        for chunk_projection in chunk_search_documents:
            chunk_id = str(chunk_projection.get("chunk_id", "")).strip()
            document_id = str(chunk_projection.get("document_id", "")).strip()
            page_id = str(chunk_projection.get("page_id", "")).strip()
            project_id = (
                normalize_corpus_record_project_id(chunk_projection.get("project_id"))
                or document_project_map.get(document_id, "")
                or page_project_map.get(page_id, "")
                or paragraph_project_map.get(chunk_id, "")
                or default_project_id
            )
            if not all([chunk_id, document_id, page_id, project_id]):
                continue
            cur.execute(
                """
                INSERT INTO corpus_chunk_search_documents (
                    chunk_id, project_id, document_id, page_id, doc_type, payload, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (chunk_id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    document_id = EXCLUDED.document_id,
                    page_id = EXCLUDED.page_id,
                    doc_type = EXCLUDED.doc_type,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (
                    _sanitize_pg_value(chunk_id),
                    project_id,
                    _sanitize_pg_value(document_id),
                    _sanitize_pg_value(page_id),
                    _sanitize_pg_value(chunk_projection.get("doc_type", "other")),
                    Json(_sanitize_pg_value(_json_obj(chunk_projection))),
                ),
            )

        for edge in relation_edges:
            edge_id = str(edge.get("edge_id", "")).strip()
            source_object_id = str(edge.get("source_object_id", "")).strip()
            source_object_type = str(edge.get("source_object_type", "")).strip().lower()
            source_document_id = ""
            if source_object_type == "document":
                source_document_id = source_object_id
            elif source_object_type in {"chunk", "paragraph"}:
                source_document_id = paragraph_document_map.get(source_object_id, "")
            elif source_object_type == "page":
                source_document_id = page_document_map.get(source_object_id, "")
            project_id = (
                document_project_map.get(source_document_id, "")
                or paragraph_project_map.get(source_object_id, "")
                or page_project_map.get(source_object_id, "")
                or default_project_id
            )
            if not all([edge_id, source_object_id, project_id]):
                continue
            cur.execute(
                """
                INSERT INTO corpus_relation_edges (
                    edge_id, project_id, source_document_id, source_object_id, edge_type, payload, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (edge_id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    source_document_id = EXCLUDED.source_document_id,
                    source_object_id = EXCLUDED.source_object_id,
                    edge_type = EXCLUDED.edge_type,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (
                    _sanitize_pg_value(edge_id),
                    project_id,
                    _sanitize_pg_value(source_document_id or None),
                    _sanitize_pg_value(source_object_id),
                    _sanitize_pg_value(str(edge.get("edge_type", "")).strip() or "refers_to"),
                    Json(_sanitize_pg_value(_json_obj(edge))),
                ),
            )


def _processing_result_for_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for doc in docs:
        processing = _json_obj(doc.get("processing"))
        processing_status, processing_note = _derive_processing_status(doc.get("status"), processing)
        out.append(
            {
                "document_id": doc.get("document_id"),
                "project_id": doc.get("project_id"),
                "pdf_id": doc.get("pdf_id"),
                "doc_type": doc.get("doc_type", "other"),
                "title": doc.get("title"),
                "status": doc.get("status"),
                "page_count": doc.get("page_count"),
                "classification_confidence": processing.get("classification_confidence"),
                "text_quality_score": processing.get("text_quality_score"),
                "parse_warning": processing.get("parse_warning"),
                "parse_error": processing.get("parse_error"),
                "compact_summary": processing.get("compact_summary"),
                "llm_document_status": processing.get("llm_document_status"),
                "llm_document_model": processing.get("llm_document_model"),
                "processing_profile_version": processing.get("processing_profile_version"),
                "enrichment_status": _json_obj(processing.get("agentic_enrichment")).get("status"),
                "agent_assertion_count": _json_obj(processing.get("agentic_enrichment")).get("assertion_count", 0),
                "candidate_ontology_count": _json_obj(processing.get("agentic_enrichment")).get("candidate_entry_count", 0),
                "active_ontology_count": _json_obj(processing.get("agentic_enrichment")).get("active_entry_count", 0),
                "agent_chunk_coverage_ratio": _json_obj(processing.get("agentic_enrichment")).get("chunk_coverage_ratio", 0.0),
                "processing_status": processing_status,
                "processing_note": processing_note,
                "tags": _json_list(processing.get("tags")),
                "ontology": _json_obj(processing.get("ontology")),
                "entities": _json_list(processing.get("entities")),
                "article_refs": _json_list(processing.get("article_refs")),
                "law_refs": _json_list(processing.get("law_refs")),
                "case_refs": _json_list(processing.get("case_refs")),
                "dates": _json_list(processing.get("dates")),
                "money_mentions": _json_list(processing.get("money_mentions")),
            }
        )
    return out


def processing_results(project_id: Optional[str], limit: int) -> Dict[str, Any]:
    ensure_schema()
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    where = ""
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where = f"WHERE {scope_filter}"

    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT job_id, status, project_id, blob_url, parse_policy, dedupe_enabled, created_at
            FROM corpus_import_jobs
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params + [limit],
        )
        jobs = [
            {k: _iso(v) for k, v in row.items()}
            for row in (cur.fetchall() or [])
        ]
        latest_job = jobs[0] if jobs else None

        cur.execute(f"SELECT COUNT(*) AS c FROM corpus_documents {where}", params)
        documents_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute(f"SELECT COUNT(*) AS c FROM corpus_pages {where}", params)
        pages_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute(f"SELECT COUNT(*) AS c FROM corpus_paragraphs {where}", params)
        paragraphs_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute(
            f"SELECT COUNT(*) AS c FROM corpus_documents {where + (' AND ' if where else 'WHERE ')}duplicate_group_id IS NOT NULL",
            params,
        )
        duplicate_count = int((cur.fetchone() or {}).get("c", 0))

        by_doc_type: Dict[str, int] = {}
        cur.execute(
            f"""
            SELECT doc_type, COUNT(*) AS c
            FROM corpus_documents
            {where}
            GROUP BY doc_type
            """,
            params,
        )
        for row in cur.fetchall() or []:
            by_doc_type[str(row.get("doc_type", "other"))] = int(row.get("c", 0))

        cur.execute(
            f"""
            SELECT *
            FROM corpus_documents
            {where}
            ORDER BY document_id
            LIMIT %s
            """,
            params + [limit],
        )
        docs = cur.fetchall() or []
        serialized_docs = []
        for row in docs:
            item = dict(row)
            item.pop("processing", None)
            item["created_at"] = _iso(item.get("created_at"))
            serialized_docs.append(item)
        processing_documents = _processing_result_for_docs([dict(r) for r in docs])
        processing_status_counts: Dict[str, int] = {}
        for item in processing_documents:
            status = str(item.get("processing_status", "unknown"))
            processing_status_counts[status] = processing_status_counts.get(status, 0) + 1
        enrichment_jobs = list_enrichment_jobs(project_id=project_id, limit=limit)

    return {
        "project_id": project_id,
        "latest_job": latest_job,
        "jobs": jobs,
        "summary": {
            "documents": documents_count,
            "pages": pages_count,
            "paragraphs": paragraphs_count,
            "duplicate_documents": duplicate_count,
            "enrichment_jobs": len(enrichment_jobs),
            "ontology_candidate_entries": sum(int(job.get("candidate_entry_count", 0) or 0) for job in enrichment_jobs[:1]),
            "ontology_active_entries": sum(int(job.get("active_entry_count", 0) or 0) for job in enrichment_jobs[:1]),
            "by_doc_type": by_doc_type,
            "processing_status_counts": processing_status_counts,
        },
        "documents": serialized_docs,
        "processing_documents": processing_documents,
        "enrichment_jobs": enrichment_jobs,
    }


def list_documents(
    limit: Optional[int] = None,
    project_id: Optional[str] = None,
    *,
    include_processing: bool = False,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where = ""
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where = f"WHERE {scope_filter}"
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT * FROM corpus_documents {where} ORDER BY document_id {limit_clause}",
            params,
        )
        rows = cur.fetchall() or []
    out = []
    for row in rows:
        item = dict(row)
        if include_processing:
            item["processing"] = _json_obj(item.get("processing"))
        else:
            item.pop("processing", None)
        item["created_at"] = _iso(item.get("created_at"))
        out.append(item)
    return out


def get_document(document_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM corpus_documents WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    item.pop("processing", None)
    item["created_at"] = _iso(item.get("created_at"))
    return item


def get_document_with_processing(document_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM corpus_documents WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    item["processing"] = _json_obj(item.get("processing"))
    item["created_at"] = _iso(item.get("created_at"))
    return item


def upsert_enrichment_job(payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO corpus_enrichment_jobs (job_id, project_id, import_job_id, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (job_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                import_job_id = EXCLUDED.import_job_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                _sanitize_pg_value(payload.get("job_id")),
                normalize_corpus_record_project_id(payload.get("project_id")),
                _sanitize_pg_value(payload.get("import_job_id")),
                _sanitize_pg_value(payload.get("status")),
                Json(_sanitize_pg_value(payload)),
            ),
        )


def list_enrichment_jobs(project_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_schema()
    where = ""
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where = f"WHERE {scope_filter}"
    params.append(limit)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT payload
            FROM corpus_enrichment_jobs
            {where}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall() or []
    return [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]


def upsert_ontology_registry_entry(payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO corpus_ontology_registry (entry_id, entry_key, kind, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (entry_id) DO UPDATE SET
                entry_key = EXCLUDED.entry_key,
                kind = EXCLUDED.kind,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                _sanitize_pg_value(payload.get("entry_id")),
                _sanitize_pg_value(payload.get("key")),
                _sanitize_pg_value(payload.get("kind")),
                _sanitize_pg_value(payload.get("status")),
                Json(_sanitize_pg_value(payload)),
            ),
        )


def list_ontology_registry_entries() -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM corpus_ontology_registry ORDER BY entry_key")
        rows = cur.fetchall() or []
    return [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]


def list_chunk_search_documents(
    *,
    project_id: Optional[str] = None,
    document_id: Optional[str] = None,
    chunk_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where_parts: List[str] = []
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where_parts.append(scope_filter)
    if document_id:
        where_parts.append("document_id = %s")
        params.append(document_id)
    if chunk_ids:
        normalized_ids = [str(item).strip() for item in chunk_ids if str(item).strip()]
        if normalized_ids:
            where_parts.append("chunk_id = ANY(%s)")
            params.append(normalized_ids)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT payload
            FROM corpus_chunk_search_documents
            {where}
            ORDER BY document_id, page_id, chunk_id
            {limit_clause}
            """,
            params,
        )
        rows = cur.fetchall() or []
    return [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]


def list_relation_edges(
    *,
    project_id: Optional[str] = None,
    document_id: Optional[str] = None,
    source_object_id: Optional[str] = None,
    edge_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where_parts: List[str] = []
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where_parts.append(scope_filter)
    if document_id:
        where_parts.append("source_document_id = %s")
        params.append(document_id)
    if source_object_id:
        where_parts.append("source_object_id = %s")
        params.append(source_object_id)
    if edge_type:
        where_parts.append("edge_type = %s")
        params.append(edge_type)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT payload
            FROM corpus_relation_edges
            {where}
            ORDER BY source_document_id, source_object_id, edge_id
            """,
            params,
        )
        rows = cur.fetchall() or []
    return [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]


def upsert_chunk_ontology_assertion(payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO corpus_chunk_ontology_assertions (
                assertion_id, paragraph_id, page_id, document_id, source_page_id, payload, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (assertion_id) DO UPDATE SET
                paragraph_id = EXCLUDED.paragraph_id,
                page_id = EXCLUDED.page_id,
                document_id = EXCLUDED.document_id,
                source_page_id = EXCLUDED.source_page_id,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                _sanitize_pg_value(payload.get("assertion_id")),
                _sanitize_pg_value(payload.get("paragraph_id")),
                _sanitize_pg_value(payload.get("page_id")),
                _sanitize_pg_value(payload.get("document_id")),
                _sanitize_pg_value(payload.get("source_page_id")),
                Json(_sanitize_pg_value(payload)),
            ),
        )


def list_chunk_ontology_assertions(
    *,
    document_id: Optional[str] = None,
    page_id: Optional[str] = None,
    paragraph_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where_parts: List[str] = []
    params: List[Any] = []
    if document_id:
        where_parts.append("document_id = %s")
        params.append(document_id)
    if page_id:
        where_parts.append("page_id = %s")
        params.append(page_id)
    if paragraph_id:
        where_parts.append("paragraph_id = %s")
        params.append(paragraph_id)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT payload
            FROM corpus_chunk_ontology_assertions
            {where}
            ORDER BY paragraph_id, assertion_id
            """,
            params,
        )
        rows = cur.fetchall() or []
    return [row.get("payload") for row in rows if isinstance(row.get("payload"), dict)]


def upsert_document_ontology_view(payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO corpus_document_ontology_views (document_id, project_id, payload, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (document_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                _sanitize_pg_value(payload.get("document_id")),
                normalize_corpus_record_project_id(payload.get("project_id")),
                Json(_sanitize_pg_value(payload)),
            ),
        )


def get_document_ontology_view(document_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM corpus_document_ontology_views WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
    payload = (row or {}).get("payload")
    return payload if isinstance(payload, dict) else None


def update_document_llm(
    document_id: str,
    *,
    status: str,
    llm_payload: Optional[Dict[str, Any]],
    model: Optional[str],
    error: Optional[str] = None,
) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT processing FROM corpus_documents WHERE document_id = %s", (document_id,))
        row = cur.fetchone()
        processing = _json_obj((row or {}).get("processing"))
        processing["llm_document_status"] = status
        processing["llm_document_model"] = model
        processing["llm_document_error"] = error
        processing["llm_document_updated_at"] = _iso(datetime.utcnow())
        processing["llm_document"] = _json_obj(llm_payload)

        extracted = _json_obj(llm_payload)
        raw_doc_type = str(extracted.get("doc_type", "")).strip().lower()
        doc_type = raw_doc_type if raw_doc_type in {"law", "regulation", "enactment_notice", "case", "other"} else None
        title = str(extracted.get("title", "")).strip() or None
        citation_title = str(extracted.get("citation_title", "")).strip() or None
        law_number = str(extracted.get("law_number", "")).strip() or None
        case_id = str(extracted.get("case_id", "")).strip() or None
        issued_date = str(extracted.get("issued_date", "")).strip() or None
        effective_start_date = str(extracted.get("effective_start_date", "")).strip() or None
        effective_end_date = str(extracted.get("effective_end_date", "")).strip() or None
        language = str(extracted.get("language", "")).strip() or None
        jurisdiction = str(extracted.get("jurisdiction", "")).strip() or None
        year = extracted.get("year")
        try:
            normalized_year = int(year) if year is not None else None
        except Exception:
            normalized_year = None

        cur.execute(
            """
            UPDATE corpus_documents
            SET processing = %s,
                doc_type = COALESCE(%s, doc_type),
                title = COALESCE(%s, title),
                citation_title = COALESCE(%s, citation_title),
                law_number = COALESCE(%s, law_number),
                case_id = COALESCE(%s, case_id),
                year = COALESCE(%s, year),
                edition_date = COALESCE(%s, edition_date)
            WHERE document_id = %s
            """,
            (
                Json(_sanitize_pg_value(processing)),
                _sanitize_pg_value(doc_type),
                _sanitize_pg_value(title),
                _sanitize_pg_value(citation_title),
                _sanitize_pg_value(law_number),
                _sanitize_pg_value(case_id),
                normalized_year,
                _sanitize_pg_value(issued_date),
                _sanitize_pg_value(document_id),
            ),
        )

        if any([effective_start_date, effective_end_date, language, jurisdiction]):
            processing = _json_obj(processing)
            if effective_start_date:
                processing["effective_start_date"] = effective_start_date
            if effective_end_date:
                processing["effective_end_date"] = effective_end_date
            if language:
                processing["language"] = language
            if jurisdiction:
                processing["jurisdiction"] = jurisdiction
            cur.execute(
                "UPDATE corpus_documents SET processing = %s WHERE document_id = %s",
                (Json(_sanitize_pg_value(processing)), _sanitize_pg_value(document_id)),
            )


def get_page(page_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM corpus_pages WHERE page_id = %s", (page_id,))
        row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    item["entities"] = _json_list(item.get("entities"))
    item["created_at"] = _iso(item.get("created_at"))
    return item


def list_pages(
    document_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where_parts: List[str] = []
    params: List[Any] = []
    if document_id:
        where_parts.append("document_id = %s")
        params.append(document_id)
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where_parts.append(scope_filter)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT *
            FROM corpus_pages
            {where}
            ORDER BY page_num, page_id
            {limit_clause}
            """,
            params,
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["entities"] = _json_list(item.get("entities"))
        item["created_at"] = _iso(item.get("created_at"))
        out.append(item)
    return out


def get_paragraph(paragraph_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM corpus_paragraphs WHERE paragraph_id = %s", (paragraph_id,))
        row = cur.fetchone()
    if not row:
        return None
    item = dict(row)
    item["heading_path"] = _json_list(item.get("heading_path"))
    item["entities"] = _json_list(item.get("entities"))
    item["article_refs"] = _json_list(item.get("article_refs"))
    item["law_refs"] = _json_list(item.get("law_refs"))
    item["case_refs"] = _json_list(item.get("case_refs"))
    item["dates"] = _json_list(item.get("dates"))
    item["money_mentions"] = _json_list(item.get("money_mentions"))
    item["llm_tags"] = _json_list(item.get("llm_tags"))
    item["llm_payload"] = _json_obj(item.get("llm_payload"))
    item["llm_updated_at"] = _iso(item.get("llm_updated_at"))
    return item


def list_paragraphs(
    project_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where_parts: List[str] = []
    params: List[Any] = []
    scope_filter = _scope_filter_clause("project_id", project_id, params)
    if scope_filter:
        where_parts.append(scope_filter)
    if document_id:
        where_parts.append("document_id = %s")
        params.append(document_id)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT *
            FROM corpus_paragraphs
            {where}
            ORDER BY document_id, paragraph_index, paragraph_id
            {limit_clause}
            """,
            params,
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["heading_path"] = _json_list(item.get("heading_path"))
        item["entities"] = _json_list(item.get("entities"))
        item["article_refs"] = _json_list(item.get("article_refs"))
        item["law_refs"] = _json_list(item.get("law_refs"))
        item["case_refs"] = _json_list(item.get("case_refs"))
        item["dates"] = _json_list(item.get("dates"))
        item["money_mentions"] = _json_list(item.get("money_mentions"))
        item["llm_tags"] = _json_list(item.get("llm_tags"))
        item["llm_payload"] = _json_obj(item.get("llm_payload"))
        item["llm_updated_at"] = _iso(item.get("llm_updated_at"))
        out.append(item)
    return out


def update_paragraph_llm(
    paragraph_id: str,
    *,
    status: str,
    summary: Optional[str] = None,
    section_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE corpus_paragraphs
            SET llm_status = %s,
                llm_summary = %s,
                llm_section_type = %s,
                llm_tags = %s,
                llm_payload = %s,
                llm_model = %s,
                llm_error = %s,
                llm_updated_at = NOW()
            WHERE paragraph_id = %s
            """,
            (
                _sanitize_pg_value(status),
                _sanitize_pg_value(summary),
                _sanitize_pg_value(section_type),
                Json(_sanitize_pg_value(tags or [])),
                Json(_sanitize_pg_value(payload or {})),
                _sanitize_pg_value(model),
                _sanitize_pg_value(error),
                _sanitize_pg_value(paragraph_id),
            ),
        )


def _matches_search_filters(chunk_projection: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
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


def search_candidates(
    *,
    project_id: str,
    query: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    paragraph_rows = list_paragraphs(project_id=project_id)
    page_rows = list_pages(project_id=project_id)
    projection_rows = list_chunk_search_documents(project_id=project_id)
    page_map = {str(row.get("page_id")): row for row in page_rows}
    paragraph_map = {str(row.get("paragraph_id")): row for row in paragraph_rows}

    scored_rows: List[Dict[str, Any]] = []
    for chunk_projection in projection_rows:
        paragraph = paragraph_map.get(str(chunk_projection.get("chunk_id", "")))
        if not paragraph:
            continue
        if not _matches_search_filters(chunk_projection, filters):
            continue
        score = score_candidate(
            query,
            str(chunk_projection.get("retrieval_text", chunk_projection.get("text_clean", ""))),
        )
        if score <= 0:
            continue
        page = page_map.get(str(paragraph.get("page_id", "")), {})
        scored_rows.append(
            {
                "paragraph": paragraph,
                "page": page,
                "chunk_projection": chunk_projection,
                "score": float(score),
            }
        )

    if not scored_rows:
        for paragraph in paragraph_rows:
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
            if not _matches_search_filters(pseudo_projection, filters):
                continue
            score = score_candidate(query, str(paragraph.get("text", "")))
            if score <= 0:
                continue
            page = page_map.get(str(paragraph.get("page_id", "")), {})
            scored_rows.append(
                {
                    "paragraph": paragraph,
                    "page": page,
                    "chunk_projection": pseudo_projection,
                    "score": float(score),
                }
            )

    if not scored_rows:
        fallback_rows = projection_rows or [
            {
                "chunk_id": paragraph.get("paragraph_id"),
                "document_id": paragraph.get("document_id"),
                "page_id": paragraph.get("page_id"),
                "page_number": 0,
                "doc_type": "other",
                "text_clean": paragraph.get("text", ""),
                "retrieval_text": paragraph.get("text", ""),
                "edge_types": [],
            }
            for paragraph in paragraph_rows
        ]
        for chunk_projection in fallback_rows:
            paragraph = paragraph_map.get(str(chunk_projection.get("chunk_id", "")))
            if not paragraph:
                continue
            if not _matches_search_filters(chunk_projection, filters):
                continue
            page = page_map.get(str(paragraph.get("page_id", "")), {})
            scored_rows.append(
                {
                    "paragraph": paragraph,
                    "page": page,
                    "chunk_projection": chunk_projection,
                    "score": 0.01,
                }
            )
            if len(scored_rows) >= top_k:
                break

    scored_rows.sort(key=lambda row: row["score"], reverse=True)
    return scored_rows[:top_k]


def search(project_id: str, query: str, top_k: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for row in search_candidates(project_id=project_id, query=query, top_k=top_k, filters=filters):
        paragraph = row.get("paragraph", {}) if isinstance(row.get("paragraph"), dict) else {}
        page = row.get("page", {}) if isinstance(row.get("page"), dict) else {}
        projection = row.get("chunk_projection", {}) if isinstance(row.get("chunk_projection"), dict) else {}
        source_page_id = str(page.get("source_page_id", "unknown_0"))
        source_page_ref = source_page_id.split("_")
        pdf_id = source_page_ref[0]
        page_num = int(source_page_ref[1]) if len(source_page_ref) > 1 and source_page_ref[1].isdigit() else 0
        items.append(
            {
                "paragraph_id": paragraph.get("paragraph_id"),
                "page_id": paragraph.get("page_id"),
                "score": round(float(row.get("score", 0.0) or 0.0), 4),
                "snippet": str(projection.get("text_clean", paragraph.get("text", "")))[:180],
                "source_page_id": source_page_id,
                "pdf_id": pdf_id,
                "page_num": page_num,
                "document_id": paragraph.get("document_id"),
                "chunk_projection": projection,
            }
        )
    return items
