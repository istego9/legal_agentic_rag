"""PostgreSQL persistence for case-judgment extraction pipelines."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except Exception:  # pragma: no cover
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
        raise RuntimeError("postgres case extraction storage is not enabled")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    return value


def _run_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("started_at", "completed_at", "created_at", "updated_at"):
        if key in out and isinstance(out[key], datetime):
            out[key] = out[key].isoformat()
    return out


def _doc_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key in ("decision_date", "created_at", "updated_at"):
        if key in out and isinstance(out[key], datetime):
            out[key] = out[key].isoformat()
        elif key in out and hasattr(out[key], "isoformat"):
            try:
                out[key] = out[key].isoformat()
            except Exception:
                pass
    return out


def _chunk_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    if isinstance(out.get("updated_at"), datetime):
        out["updated_at"] = out["updated_at"].isoformat()
    return out


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
                CREATE TABLE IF NOT EXISTS case_extraction_runs (
                    run_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    pipeline_name TEXT NOT NULL,
                    pipeline_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model_name TEXT,
                    model_reasoning_effort TEXT,
                    parser_version TEXT,
                    source TEXT NOT NULL DEFAULT 'pipeline',
                    status TEXT NOT NULL,
                    route_status TEXT NOT NULL DEFAULT 'unknown',
                    token_input INTEGER NOT NULL DEFAULT 0,
                    token_output INTEGER NOT NULL DEFAULT 0,
                    llm_calls INTEGER NOT NULL DEFAULT 0,
                    source_document_revision TEXT,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    error_message TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS case_document_extractions (
                    document_extraction_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES case_extraction_runs(run_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    artifact_version INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    supersedes_document_extraction_id TEXT REFERENCES case_document_extractions(document_extraction_id),
                    document_subtype TEXT,
                    proceeding_no TEXT,
                    case_cluster_id TEXT,
                    court_name TEXT,
                    court_level TEXT,
                    decision_date DATE,
                    page_count INTEGER,
                    confidence_score NUMERIC(6,5),
                    validation_status TEXT NOT NULL DEFAULT 'pending',
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (document_id, schema_version, artifact_version)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS case_chunk_extractions (
                    chunk_extraction_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES case_extraction_runs(run_id) ON DELETE CASCADE,
                    document_extraction_id TEXT NOT NULL REFERENCES case_document_extractions(document_extraction_id) ON DELETE CASCADE,
                    paragraph_id TEXT,
                    page_id TEXT,
                    document_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    artifact_version INTEGER NOT NULL,
                    chunk_external_id TEXT NOT NULL,
                    chunk_type TEXT,
                    section_kind_case TEXT,
                    paragraph_no INTEGER,
                    page_number_1 INTEGER,
                    order_effect_label TEXT,
                    ground_owner TEXT,
                    ground_no TEXT,
                    confidence_score NUMERIC(6,5),
                    validation_status TEXT NOT NULL DEFAULT 'pending',
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (document_extraction_id, chunk_external_id),
                    UNIQUE (document_id, schema_version, artifact_version, chunk_external_id)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS case_extraction_qc_results (
                    qc_result_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES case_extraction_runs(run_id) ON DELETE CASCADE,
                    document_id TEXT NOT NULL,
                    qc_stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_case_document_active_by_schema
                ON case_document_extractions (document_id, schema_version)
                WHERE is_active;
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_status
                ON case_extraction_runs (status, started_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_document
                ON case_extraction_runs (document_id, started_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_schema
                ON case_extraction_runs (schema_version, started_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_pipeline
                ON case_extraction_runs (pipeline_name, pipeline_version, started_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_route_status
                ON case_extraction_runs (route_status);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_metadata_gin
                ON case_extraction_runs USING GIN (metadata);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_document_extractions_run
                ON case_document_extractions (run_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_document_extractions_document
                ON case_document_extractions (document_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_document_extractions_schema
                ON case_document_extractions (schema_version, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_document_extractions_validation
                ON case_document_extractions (validation_status, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_document_extractions_payload_gin
                ON case_document_extractions USING GIN (payload);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_run
                ON case_chunk_extractions (run_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_document
                ON case_chunk_extractions (document_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_schema
                ON case_chunk_extractions (schema_version, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_validation
                ON case_chunk_extractions (validation_status, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_paragraph
                ON case_chunk_extractions (paragraph_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_page
                ON case_chunk_extractions (page_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_chunk_external
                ON case_chunk_extractions (chunk_external_id);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_payload_gin
                ON case_chunk_extractions USING GIN (payload);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_qc_results_run
                ON case_extraction_qc_results (run_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_qc_results_document
                ON case_extraction_qc_results (document_id, created_at DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_case_qc_results_status
                ON case_extraction_qc_results (status, severity, created_at DESC);
                """
            )
        _SCHEMA_READY = True


def create_case_extraction_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO case_extraction_runs (
                run_id, document_id, pipeline_name, pipeline_version, schema_version,
                prompt_version, model_name, model_reasoning_effort, parser_version,
                source, status, route_status, token_input, token_output, llm_calls,
                source_document_revision, started_at, completed_at, error_message, metadata
            ) VALUES (
                %(run_id)s, %(document_id)s, %(pipeline_name)s, %(pipeline_version)s, %(schema_version)s,
                %(prompt_version)s, %(model_name)s, %(model_reasoning_effort)s, %(parser_version)s,
                %(source)s, %(status)s, %(route_status)s, %(token_input)s, %(token_output)s, %(llm_calls)s,
                %(source_document_revision)s, %(started_at)s, %(completed_at)s, %(error_message)s, %(metadata)s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                pipeline_name = EXCLUDED.pipeline_name,
                pipeline_version = EXCLUDED.pipeline_version,
                schema_version = EXCLUDED.schema_version,
                prompt_version = EXCLUDED.prompt_version,
                model_name = EXCLUDED.model_name,
                model_reasoning_effort = EXCLUDED.model_reasoning_effort,
                parser_version = EXCLUDED.parser_version,
                source = EXCLUDED.source,
                status = EXCLUDED.status,
                route_status = EXCLUDED.route_status,
                token_input = EXCLUDED.token_input,
                token_output = EXCLUDED.token_output,
                llm_calls = EXCLUDED.llm_calls,
                source_document_revision = EXCLUDED.source_document_revision,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                error_message = EXCLUDED.error_message,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING *
            """,
            {
                "run_id": _sanitize(payload.get("run_id")),
                "document_id": _sanitize(payload.get("document_id")),
                "pipeline_name": _sanitize(payload.get("pipeline_name")),
                "pipeline_version": _sanitize(payload.get("pipeline_version")),
                "schema_version": _sanitize(payload.get("schema_version")),
                "prompt_version": _sanitize(payload.get("prompt_version")),
                "model_name": _sanitize(payload.get("model_name")),
                "model_reasoning_effort": _sanitize(payload.get("model_reasoning_effort")),
                "parser_version": _sanitize(payload.get("parser_version")),
                "source": _sanitize(payload.get("source") or "pipeline"),
                "status": _sanitize(payload.get("status")),
                "route_status": _sanitize(payload.get("route_status") or "unknown"),
                "token_input": int(payload.get("token_input", 0) or 0),
                "token_output": int(payload.get("token_output", 0) or 0),
                "llm_calls": int(payload.get("llm_calls", 0) or 0),
                "source_document_revision": _sanitize(payload.get("source_document_revision")),
                "started_at": payload.get("started_at") or datetime.now(timezone.utc),
                "completed_at": payload.get("completed_at"),
                "error_message": _sanitize(payload.get("error_message")),
                "metadata": Json(_sanitize(_json_obj(payload.get("metadata")))),
            },
        )
        row = cur.fetchone() or {}
    return _run_row(dict(row))


def update_case_extraction_run(run_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ensure_schema()
    assignments: List[str] = []
    values: List[Any] = []
    simple_fields = {
        "status",
        "route_status",
        "token_input",
        "token_output",
        "llm_calls",
        "completed_at",
        "error_message",
        "model_name",
        "model_reasoning_effort",
        "prompt_version",
        "pipeline_version",
        "parser_version",
        "source_document_revision",
    }
    for key in simple_fields:
        if key in patch:
            assignments.append(f"{key} = %s")
            values.append(_sanitize(patch.get(key)))
    if "metadata" in patch:
        assignments.append("metadata = %s")
        values.append(Json(_sanitize(_json_obj(patch.get("metadata")))))
    if not assignments:
        return get_case_extraction_run(run_id)
    assignments.append("updated_at = NOW()")
    values.append(run_id)
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"UPDATE case_extraction_runs SET {', '.join(assignments)} WHERE run_id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()
        if not row:
            return None
    return _run_row(dict(row))


def get_case_extraction_run(run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM case_extraction_runs WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
    return _run_row(dict(row))


def list_case_extraction_runs(
    *,
    document_id: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where: List[str] = []
    params: List[Any] = []
    if document_id:
        where.append("document_id = %s")
        params.append(document_id)
    if pipeline_name:
        where.append("pipeline_name = %s")
        params.append(pipeline_name)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT * FROM case_extraction_runs {where_clause} ORDER BY started_at DESC LIMIT %s",
            (*params, max(1, min(limit, 2000))),
        )
        rows = cur.fetchall() or []
    return [_run_row(dict(row)) for row in rows]


def upsert_case_document_extraction(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO case_document_extractions (
                document_extraction_id, run_id, document_id, schema_version, artifact_version,
                is_active, supersedes_document_extraction_id, document_subtype, proceeding_no,
                case_cluster_id, court_name, court_level, decision_date, page_count,
                confidence_score, validation_status, payload
            ) VALUES (
                %(document_extraction_id)s, %(run_id)s, %(document_id)s, %(schema_version)s, %(artifact_version)s,
                %(is_active)s, %(supersedes_document_extraction_id)s, %(document_subtype)s, %(proceeding_no)s,
                %(case_cluster_id)s, %(court_name)s, %(court_level)s, %(decision_date)s, %(page_count)s,
                %(confidence_score)s, %(validation_status)s, %(payload)s
            )
            ON CONFLICT (document_extraction_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                document_id = EXCLUDED.document_id,
                schema_version = EXCLUDED.schema_version,
                artifact_version = EXCLUDED.artifact_version,
                is_active = EXCLUDED.is_active,
                supersedes_document_extraction_id = EXCLUDED.supersedes_document_extraction_id,
                document_subtype = EXCLUDED.document_subtype,
                proceeding_no = EXCLUDED.proceeding_no,
                case_cluster_id = EXCLUDED.case_cluster_id,
                court_name = EXCLUDED.court_name,
                court_level = EXCLUDED.court_level,
                decision_date = EXCLUDED.decision_date,
                page_count = EXCLUDED.page_count,
                confidence_score = EXCLUDED.confidence_score,
                validation_status = EXCLUDED.validation_status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            RETURNING *
            """,
            {
                "document_extraction_id": _sanitize(payload.get("document_extraction_id")),
                "run_id": _sanitize(payload.get("run_id")),
                "document_id": _sanitize(payload.get("document_id")),
                "schema_version": _sanitize(payload.get("schema_version")),
                "artifact_version": int(payload.get("artifact_version", 1) or 1),
                "is_active": bool(payload.get("is_active", False)),
                "supersedes_document_extraction_id": _sanitize(payload.get("supersedes_document_extraction_id")),
                "document_subtype": _sanitize(payload.get("document_subtype")),
                "proceeding_no": _sanitize(payload.get("proceeding_no")),
                "case_cluster_id": _sanitize(payload.get("case_cluster_id")),
                "court_name": _sanitize(payload.get("court_name")),
                "court_level": _sanitize(payload.get("court_level")),
                "decision_date": payload.get("decision_date"),
                "page_count": payload.get("page_count"),
                "confidence_score": payload.get("confidence_score"),
                "validation_status": _sanitize(payload.get("validation_status") or "pending"),
                "payload": Json(_sanitize(_json_obj(payload.get("payload")))),
            },
        )
        row = cur.fetchone() or {}
    return _doc_row(dict(row))


def get_case_document_extraction(document_extraction_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM case_document_extractions WHERE document_extraction_id = %s",
            (document_extraction_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
    return _doc_row(dict(row))


def list_case_document_extractions(
    *,
    document_id: Optional[str] = None,
    run_id: Optional[str] = None,
    active_only: bool = False,
    schema_version: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where: List[str] = []
    params: List[Any] = []
    if document_id:
        where.append("document_id = %s")
        params.append(document_id)
    if run_id:
        where.append("run_id = %s")
        params.append(run_id)
    if schema_version:
        where.append("schema_version = %s")
        params.append(schema_version)
    if active_only:
        where.append("is_active = TRUE")
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT * FROM case_document_extractions {where_clause} ORDER BY created_at DESC LIMIT %s",
            (*params, max(1, min(limit, 5000))),
        )
        rows = cur.fetchall() or []
    return [_doc_row(dict(row)) for row in rows]


def activate_case_document_extraction(document_extraction_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    target = get_case_document_extraction(document_extraction_id)
    if not target:
        return None
    document_id = str(target.get("document_id", ""))
    schema_version = str(target.get("schema_version", ""))
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE case_document_extractions
            SET is_active = FALSE, updated_at = NOW()
            WHERE document_id = %s AND schema_version = %s
            """,
            (document_id, schema_version),
        )
        cur.execute(
            """
            UPDATE case_document_extractions
            SET is_active = TRUE, updated_at = NOW()
            WHERE document_extraction_id = %s
            RETURNING *
            """,
            (document_extraction_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
    return _doc_row(dict(row))


def upsert_case_chunk_extractions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ensure_schema()
    persisted: List[Dict[str, Any]] = []
    if not rows:
        return persisted
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        for payload in rows:
            cur.execute(
                """
                INSERT INTO case_chunk_extractions (
                    chunk_extraction_id, run_id, document_extraction_id, paragraph_id, page_id,
                    document_id, schema_version, artifact_version, chunk_external_id, chunk_type,
                    section_kind_case, paragraph_no, page_number_1, order_effect_label,
                    ground_owner, ground_no, confidence_score, validation_status, payload
                ) VALUES (
                    %(chunk_extraction_id)s, %(run_id)s, %(document_extraction_id)s, %(paragraph_id)s, %(page_id)s,
                    %(document_id)s, %(schema_version)s, %(artifact_version)s, %(chunk_external_id)s, %(chunk_type)s,
                    %(section_kind_case)s, %(paragraph_no)s, %(page_number_1)s, %(order_effect_label)s,
                    %(ground_owner)s, %(ground_no)s, %(confidence_score)s, %(validation_status)s, %(payload)s
                )
                ON CONFLICT (chunk_extraction_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    document_extraction_id = EXCLUDED.document_extraction_id,
                    paragraph_id = EXCLUDED.paragraph_id,
                    page_id = EXCLUDED.page_id,
                    document_id = EXCLUDED.document_id,
                    schema_version = EXCLUDED.schema_version,
                    artifact_version = EXCLUDED.artifact_version,
                    chunk_external_id = EXCLUDED.chunk_external_id,
                    chunk_type = EXCLUDED.chunk_type,
                    section_kind_case = EXCLUDED.section_kind_case,
                    paragraph_no = EXCLUDED.paragraph_no,
                    page_number_1 = EXCLUDED.page_number_1,
                    order_effect_label = EXCLUDED.order_effect_label,
                    ground_owner = EXCLUDED.ground_owner,
                    ground_no = EXCLUDED.ground_no,
                    confidence_score = EXCLUDED.confidence_score,
                    validation_status = EXCLUDED.validation_status,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                RETURNING *
                """,
                {
                    "chunk_extraction_id": _sanitize(payload.get("chunk_extraction_id")),
                    "run_id": _sanitize(payload.get("run_id")),
                    "document_extraction_id": _sanitize(payload.get("document_extraction_id")),
                    "paragraph_id": _sanitize(payload.get("paragraph_id")),
                    "page_id": _sanitize(payload.get("page_id")),
                    "document_id": _sanitize(payload.get("document_id")),
                    "schema_version": _sanitize(payload.get("schema_version")),
                    "artifact_version": int(payload.get("artifact_version", 1) or 1),
                    "chunk_external_id": _sanitize(payload.get("chunk_external_id")),
                    "chunk_type": _sanitize(payload.get("chunk_type")),
                    "section_kind_case": _sanitize(payload.get("section_kind_case")),
                    "paragraph_no": payload.get("paragraph_no"),
                    "page_number_1": payload.get("page_number_1"),
                    "order_effect_label": _sanitize(payload.get("order_effect_label")),
                    "ground_owner": _sanitize(payload.get("ground_owner")),
                    "ground_no": _sanitize(payload.get("ground_no")),
                    "confidence_score": payload.get("confidence_score"),
                    "validation_status": _sanitize(payload.get("validation_status") or "pending"),
                    "payload": Json(_sanitize(_json_obj(payload.get("payload")))),
                },
            )
            row = cur.fetchone()
            if row:
                persisted.append(_chunk_row(dict(row)))
    return persisted


def list_case_chunk_extractions(
    *,
    document_extraction_id: Optional[str] = None,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where: List[str] = []
    params: List[Any] = []
    if document_extraction_id:
        where.append("document_extraction_id = %s")
        params.append(document_extraction_id)
    if run_id:
        where.append("run_id = %s")
        params.append(run_id)
    if document_id:
        where.append("document_id = %s")
        params.append(document_id)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT * FROM case_chunk_extractions {where_clause} ORDER BY created_at ASC LIMIT %s",
            (*params, max(1, min(limit, 20000))),
        )
        rows = cur.fetchall() or []
    return [_chunk_row(dict(row)) for row in rows]


def upsert_case_qc_results(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ensure_schema()
    persisted: List[Dict[str, Any]] = []
    if not rows:
        return persisted
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        for payload in rows:
            cur.execute(
                """
                INSERT INTO case_extraction_qc_results (
                    qc_result_id, run_id, document_id, qc_stage, status,
                    severity, message, details
                ) VALUES (
                    %(qc_result_id)s, %(run_id)s, %(document_id)s, %(qc_stage)s, %(status)s,
                    %(severity)s, %(message)s, %(details)s
                )
                ON CONFLICT (qc_result_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    document_id = EXCLUDED.document_id,
                    qc_stage = EXCLUDED.qc_stage,
                    status = EXCLUDED.status,
                    severity = EXCLUDED.severity,
                    message = EXCLUDED.message,
                    details = EXCLUDED.details,
                    updated_at = NOW()
                RETURNING *
                """,
                {
                    "qc_result_id": _sanitize(payload.get("qc_result_id")),
                    "run_id": _sanitize(payload.get("run_id")),
                    "document_id": _sanitize(payload.get("document_id")),
                    "qc_stage": _sanitize(payload.get("qc_stage")),
                    "status": _sanitize(payload.get("status")),
                    "severity": _sanitize(payload.get("severity")),
                    "message": _sanitize(payload.get("message")),
                    "details": Json(_sanitize(_json_obj(payload.get("details")))),
                },
            )
            row = cur.fetchone()
            if row:
                item = dict(row)
                for key in ("created_at", "updated_at"):
                    if isinstance(item.get(key), datetime):
                        item[key] = item[key].isoformat()
                persisted.append(item)
    return persisted


def list_case_qc_results(
    *,
    run_id: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where: List[str] = []
    params: List[Any] = []
    if run_id:
        where.append("run_id = %s")
        params.append(run_id)
    if document_id:
        where.append("document_id = %s")
        params.append(document_id)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT * FROM case_extraction_qc_results {where_clause} ORDER BY created_at DESC LIMIT %s",
            (*params, max(1, min(limit, 5000))),
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("created_at", "updated_at"):
            if isinstance(item.get(key), datetime):
                item[key] = item[key].isoformat()
        out.append(item)
    return out


def delete_case_runs_by_source(*, source: str, pipeline_name: Optional[str] = None) -> int:
    ensure_schema()
    where = "source = %s"
    params: List[Any] = [source]
    if pipeline_name:
        where += " AND pipeline_name = %s"
        params.append(pipeline_name)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM case_extraction_runs WHERE {where}", tuple(params))
        return int(cur.rowcount or 0)
