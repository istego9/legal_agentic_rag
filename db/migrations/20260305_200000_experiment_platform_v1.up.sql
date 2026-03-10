BEGIN;

CREATE TABLE IF NOT EXISTS exp_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    gold_dataset_id TEXT NOT NULL,
    endpoint_target TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exp_experiments (
    experiment_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    name TEXT NOT NULL,
    gold_dataset_id TEXT NOT NULL,
    baseline_experiment_run_id TEXT,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exp_runs (
    experiment_run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    gold_dataset_id TEXT NOT NULL,
    stage_type TEXT NOT NULL,
    status TEXT NOT NULL,
    gate_passed BOOLEAN,
    idempotency_key TEXT,
    qa_run_id TEXT,
    eval_run_id TEXT,
    sample_size INTEGER NOT NULL DEFAULT 0,
    question_count INTEGER NOT NULL DEFAULT 0,
    baseline_experiment_run_id TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS exp_stage_cache (
    stage_type TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    experiment_run_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stage_type, cache_key)
);

CREATE TABLE IF NOT EXISTS exp_scores (
    score_id TEXT PRIMARY KEY,
    experiment_run_id TEXT NOT NULL UNIQUE,
    experiment_id TEXT NOT NULL,
    stage_type TEXT NOT NULL,
    answer_score_mean DOUBLE PRECISION NOT NULL DEFAULT 0,
    grounding_score_mean DOUBLE PRECISION NOT NULL DEFAULT 0,
    telemetry_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
    ttft_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
    overall_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exp_question_metrics (
    experiment_run_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    answer_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    grounding_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    telemetry_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
    ttft_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
    overall_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    route_name TEXT,
    segment TEXT,
    delta_vs_baseline DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (experiment_run_id, question_id)
);

CREATE TABLE IF NOT EXISTS exp_artifacts (
    artifact_id TEXT PRIMARY KEY,
    experiment_run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_url TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exp_ops_log (
    op_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    actor TEXT NOT NULL,
    command_name TEXT NOT NULL,
    target TEXT,
    status TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_exp_runs_experiment_created
    ON exp_runs (experiment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exp_scores_overall
    ON exp_scores (overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_exp_question_metrics_run_question
    ON exp_question_metrics (experiment_run_id, question_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exp_stage_cache_stage_key
    ON exp_stage_cache (stage_type, cache_key);
CREATE INDEX IF NOT EXISTS idx_exp_ops_log_started_actor_command
    ON exp_ops_log (started_at DESC, actor, command_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exp_runs_experiment_idempotency
    ON exp_runs (experiment_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMIT;

