BEGIN;

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
    token_input INTEGER NOT NULL DEFAULT 0 CHECK (token_input >= 0),
    token_output INTEGER NOT NULL DEFAULT 0 CHECK (token_output >= 0),
    llm_calls INTEGER NOT NULL DEFAULT 0 CHECK (llm_calls >= 0),
    source_document_revision TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'partial', 'qc_failed')),
    CHECK (route_status IN ('unknown', 'routed', 'fallback_used', 'fallback_failed', 'not_required'))
);

CREATE TABLE IF NOT EXISTS case_document_extractions (
    document_extraction_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES case_extraction_runs(run_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK (artifact_version > 0),
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
    CHECK (validation_status IN ('pending', 'passed', 'failed', 'warning', 'needs_review')),
    UNIQUE (document_id, schema_version, artifact_version)
);

CREATE TABLE IF NOT EXISTS case_chunk_extractions (
    chunk_extraction_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES case_extraction_runs(run_id) ON DELETE CASCADE,
    document_extraction_id TEXT NOT NULL REFERENCES case_document_extractions(document_extraction_id) ON DELETE CASCADE,
    paragraph_id TEXT,
    page_id TEXT,
    document_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK (artifact_version > 0),
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
    CHECK (validation_status IN ('pending', 'passed', 'failed', 'warning', 'needs_review')),
    UNIQUE (document_extraction_id, chunk_external_id),
    UNIQUE (document_id, schema_version, artifact_version, chunk_external_id)
);

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
    CHECK (status IN ('passed', 'failed', 'warning')),
    CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_case_document_active_by_schema
    ON case_document_extractions (document_id, schema_version)
    WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_status
    ON case_extraction_runs (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_document
    ON case_extraction_runs (document_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_schema
    ON case_extraction_runs (schema_version, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_pipeline
    ON case_extraction_runs (pipeline_name, pipeline_version, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_route_status
    ON case_extraction_runs (route_status);
CREATE INDEX IF NOT EXISTS idx_case_extraction_runs_metadata_gin
    ON case_extraction_runs USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_case_document_extractions_run
    ON case_document_extractions (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_document_extractions_document
    ON case_document_extractions (document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_document_extractions_schema
    ON case_document_extractions (schema_version, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_document_extractions_validation
    ON case_document_extractions (validation_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_document_extractions_payload_gin
    ON case_document_extractions USING GIN (payload);

CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_run
    ON case_chunk_extractions (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_document
    ON case_chunk_extractions (document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_schema
    ON case_chunk_extractions (schema_version, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_validation
    ON case_chunk_extractions (validation_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_paragraph
    ON case_chunk_extractions (paragraph_id);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_page
    ON case_chunk_extractions (page_id);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_chunk_external
    ON case_chunk_extractions (chunk_external_id);
CREATE INDEX IF NOT EXISTS idx_case_chunk_extractions_payload_gin
    ON case_chunk_extractions USING GIN (payload);

CREATE INDEX IF NOT EXISTS idx_case_qc_results_run
    ON case_extraction_qc_results (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_qc_results_document
    ON case_extraction_qc_results (document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_qc_results_status
    ON case_extraction_qc_results (status, severity, created_at DESC);

COMMIT;
