"""PostgreSQL persistence for QA/Runs/Eval/Gold/Synth/Config state."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import BaseModel

from legal_rag_api.contracts import (
    RunQuestionReviewArtifact,
    EvalRun,
    GoldDataset,
    GoldQuestion,
    QueryResponse,
    ScoringPolicy,
)

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


def enabled() -> bool:
    return bool(DATABASE_URL and psycopg is not None)


def _connect():
    if not enabled():
        raise RuntimeError("runtime postgres storage disabled")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or not enabled():
        return
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_datasets (
                dataset_id TEXT PRIMARY KEY,
                project_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_dataset_questions (
                dataset_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (dataset_id, question_id)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_runs (
                run_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                status TEXT NOT NULL,
                question_count INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_run_questions (
                run_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (run_id, question_id)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_run_question_reviews (
                run_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (run_id, question_id)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                eval_run_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                gold_dataset_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gold_datasets (
                gold_dataset_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gold_questions (
                gold_question_id TEXT PRIMARY KEY,
                gold_dataset_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                review_status TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS synth_jobs (
                job_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS synth_candidates (
                candidate_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scoring_policies (
                policy_version TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config_versions (
                config_key TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS question_telemetry (
                question_id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                audit_id BIGSERIAL PRIMARY KEY,
                event TEXT NOT NULL,
                target TEXT,
                at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                payload JSONB NOT NULL
            );
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exp_stage_cache (
                stage_type TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                experiment_run_id TEXT NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (stage_type, cache_key)
            );
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exp_artifacts (
                artifact_id TEXT PRIMARY KEY,
                experiment_run_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_url TEXT,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
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
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_dataset_project ON qa_datasets(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_run_dataset ON qa_runs(dataset_id, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_run_question_reviews_run ON qa_run_question_reviews(run_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_eval_run_run_id ON eval_runs(run_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_gold_question_dataset ON gold_questions(gold_dataset_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_synth_candidates_job ON synth_candidates(job_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exp_runs_experiment_created ON exp_runs(experiment_id, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exp_scores_overall ON exp_scores(overall_score DESC);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_question_metrics_run_question ON exp_question_metrics(experiment_run_id, question_id);"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_exp_stage_cache_stage_key ON exp_stage_cache(stage_type, cache_key);"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exp_ops_log_started_actor_command ON exp_ops_log(started_at DESC, actor, command_name);")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_exp_runs_experiment_idempotency ON exp_runs(experiment_id, idempotency_key) WHERE idempotency_key IS NOT NULL;"
        )
    _SCHEMA_READY = True
    ensure_default_scoring_policy()


def ensure_default_scoring_policy() -> None:
    if not enabled():
        return
    policy = ScoringPolicy(
        policy_version="contest_v2026_public_rules_v1",
        policy_type="contest_emulation",
        beta=2.5,
        ttft_curve={
            "mode": "piecewise_linear_avg_ttft",
            "best_seconds": 1.0,
            "best_factor": 1.05,
            "worst_seconds": 5.0,
            "worst_factor": 0.85,
        },
        telemetry_policy="run_level_factor",
    )
    upsert_scoring_policy(policy)


def append_audit(event: str, target: Optional[str], payload: Dict[str, Any]) -> None:
    if not enabled():
        return
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (event, target, payload) VALUES (%s, %s, %s)",
            (event, target, Json(payload)),
        )


def upsert_dataset(dataset_id: str, project_id: str) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_datasets (dataset_id, project_id, created_at, updated_at)
            VALUES (%s, %s, NOW(), NOW())
            ON CONFLICT (dataset_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                updated_at = NOW()
            """,
            (dataset_id, project_id or None),
        )


def upsert_dataset_questions(dataset_id: str, project_id: str, questions: List[Dict[str, Any]]) -> int:
    ensure_schema()
    upsert_dataset(dataset_id, project_id)
    imported = 0
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        for question in questions:
            qid = str(question.get("id"))
            cur.execute(
                "SELECT 1 FROM qa_dataset_questions WHERE dataset_id = %s AND question_id = %s",
                (dataset_id, qid),
            )
            existed = cur.fetchone() is not None
            cur.execute(
                """
                INSERT INTO qa_dataset_questions (dataset_id, question_id, payload, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (dataset_id, question_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (dataset_id, qid, Json(question)),
            )
            if not existed:
                imported += 1
    return imported


def list_dataset_questions(dataset_id: str, limit: int) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT dataset_id, project_id FROM qa_datasets WHERE dataset_id = %s", (dataset_id,))
        ds = cur.fetchone()
        if not ds:
            return {}
        cur.execute(
            """
            SELECT payload
            FROM qa_dataset_questions
            WHERE dataset_id = %s
            ORDER BY question_id
            LIMIT %s
            """,
            (dataset_id, limit),
        )
        items = [row["payload"] for row in (cur.fetchall() or [])]
        cur.execute("SELECT COUNT(*) AS c FROM qa_dataset_questions WHERE dataset_id = %s", (dataset_id,))
        total = int((cur.fetchone() or {}).get("c", 0))
    return {"dataset_id": dataset_id, "project_id": ds.get("project_id"), "items": items, "total": total}


def get_question_payload(dataset_id: str, question_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM qa_dataset_questions WHERE dataset_id = %s AND question_id = %s",
            (dataset_id, question_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def create_run(dataset_id: str, question_count: int, status: str = "queued") -> Dict[str, Any]:
    ensure_schema()
    run_id = str(uuid4())
    now = _utcnow()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_runs (run_id, dataset_id, status, question_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (run_id, dataset_id, status, question_count, now, now),
        )
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "status": status,
        "question_count": question_count,
        "created_at": now,
        "updated_at": now,
    }


def set_run_status(run_id: str, status: str) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE qa_runs SET status = %s, updated_at = NOW() WHERE run_id = %s",
            (status, run_id),
        )


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT run_id, dataset_id, status, question_count, created_at, updated_at FROM qa_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_run_question(run_id: str, question_id: str, response: QueryResponse) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_run_questions (run_id, question_id, payload, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (run_id, question_id) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (run_id, question_id, Json(response.model_dump(mode="json"))),
        )
        cur.execute(
            """
            UPDATE qa_runs
            SET question_count = (
                SELECT COUNT(*)::int FROM qa_run_questions WHERE run_id = %s
            ),
            updated_at = NOW()
            WHERE run_id = %s
            """,
            (run_id, run_id),
        )


def get_run_question(run_id: str, question_id: str) -> Optional[QueryResponse]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM qa_run_questions WHERE run_id = %s AND question_id = %s",
            (run_id, question_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return QueryResponse(**payload)


def upsert_run_question_review(run_id: str, question_id: str, artifact: RunQuestionReviewArtifact) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_run_question_reviews (run_id, question_id, payload, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (run_id, question_id) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (run_id, question_id, Json(artifact.model_dump(mode="json"))),
        )


def get_run_question_review(run_id: str, question_id: str) -> Optional[RunQuestionReviewArtifact]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM qa_run_question_reviews WHERE run_id = %s AND question_id = %s",
            (run_id, question_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return RunQuestionReviewArtifact(**payload)


def list_run_questions(run_id: str) -> Dict[str, QueryResponse]:
    ensure_schema()
    out: Dict[str, QueryResponse] = {}
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT question_id, payload FROM qa_run_questions WHERE run_id = %s ORDER BY question_id",
            (run_id,),
        )
        rows = cur.fetchall() or []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out[str(row.get("question_id"))] = QueryResponse(**payload)
    return out


def upsert_question_telemetry(question_id: str, payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO question_telemetry (question_id, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (question_id) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (question_id, Json(payload)),
        )


def create_gold_dataset(payload: Dict[str, Any]) -> GoldDataset:
    ensure_schema()
    now = _utcnow()
    ds = GoldDataset(
        gold_dataset_id=str(uuid4()),
        project_id=payload["project_id"],
        name=payload["name"],
        version=payload["version"],
        status="draft",
        base_dataset_id=payload.get("base_dataset_id"),
        question_count=0,
        created_at=now,
        updated_at=now,
    )
    upsert_gold_dataset(ds)
    append_audit("gold_dataset_created", ds.gold_dataset_id, payload)
    return ds


def upsert_gold_dataset(dataset: GoldDataset) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gold_datasets (gold_dataset_id, project_id, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (gold_dataset_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                dataset.gold_dataset_id,
                dataset.project_id,
                dataset.status,
                Json(dataset.model_dump(mode="json")),
            ),
        )


def get_gold_dataset(gold_dataset_id: str) -> Optional[GoldDataset]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM gold_datasets WHERE gold_dataset_id = %s", (gold_dataset_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return GoldDataset(**payload)


def add_gold_question(dataset_id: str, question: Dict[str, Any]) -> GoldQuestion:
    ensure_schema()
    payload = GoldQuestion(
        gold_question_id=str(uuid4()),
        question_id=question["question_id"],
        gold_dataset_id=dataset_id,
        canonical_answer=question["canonical_answer"],
        acceptable_answers=question.get("acceptable_answers", []),
        answer_type=question["answer_type"],
        source_sets=question["source_sets"],
        review_status=question.get("review_status", "draft"),
        reviewers=question.get("reviewers", []),
        notes=question.get("notes"),
    )
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gold_questions (gold_question_id, gold_dataset_id, question_id, review_status, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (gold_question_id) DO UPDATE SET
                gold_dataset_id = EXCLUDED.gold_dataset_id,
                question_id = EXCLUDED.question_id,
                review_status = EXCLUDED.review_status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                payload.gold_question_id,
                payload.gold_dataset_id,
                payload.question_id,
                payload.review_status,
                Json(payload.model_dump(mode="json")),
            ),
        )
    _refresh_gold_dataset_count(dataset_id)
    append_audit("gold_question_created", payload.gold_question_id, {"dataset_id": dataset_id})
    return payload


def _refresh_gold_dataset_count(dataset_id: str) -> None:
    ds = get_gold_dataset(dataset_id)
    if not ds:
        return
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT COUNT(*) AS c FROM gold_questions WHERE gold_dataset_id = %s", (dataset_id,))
        count = int((cur.fetchone() or {}).get("c", 0))
    ds.question_count = count
    ds.updated_at = _utcnow()
    upsert_gold_dataset(ds)


def list_gold_questions(dataset_id: str) -> Dict[str, GoldQuestion]:
    ensure_schema()
    out: Dict[str, GoldQuestion] = {}
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT gold_question_id, payload FROM gold_questions WHERE gold_dataset_id = %s ORDER BY gold_question_id",
            (dataset_id,),
        )
        rows = cur.fetchall() or []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out[str(row.get("gold_question_id"))] = GoldQuestion(**payload)
    return out


def find_gold_question(gold_question_id: str) -> Optional[Tuple[str, GoldQuestion]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT gold_dataset_id, payload FROM gold_questions WHERE gold_question_id = %s",
            (gold_question_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return str(row.get("gold_dataset_id")), GoldQuestion(**payload)


def upsert_gold_question(question: GoldQuestion) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gold_questions (gold_question_id, gold_dataset_id, question_id, review_status, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (gold_question_id) DO UPDATE SET
                gold_dataset_id = EXCLUDED.gold_dataset_id,
                question_id = EXCLUDED.question_id,
                review_status = EXCLUDED.review_status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (
                question.gold_question_id,
                question.gold_dataset_id,
                question.question_id,
                question.review_status,
                Json(question.model_dump(mode="json")),
            ),
        )


def set_gold_question_review(
    gold_question_id: str,
    dataset_id: str,
    decision: str,
    comment: Optional[str] = None,
) -> Optional[GoldQuestion]:
    found = find_gold_question(gold_question_id)
    if not found:
        return None
    _, question = found
    if decision == "approve":
        question.review_status = "reviewed"
    elif decision == "lock":
        question.review_status = "locked"
    elif decision == "changes_requested":
        question.review_status = "draft"
    if comment:
        question.notes = f"{question.notes or ''}{('\\n' if question.notes else '')}{comment}"
    upsert_gold_question(question)
    append_audit("gold_question_review", gold_question_id, {"decision": decision, "dataset_id": dataset_id})
    return question


def lock_gold_dataset(gold_dataset_id: str) -> None:
    ds = get_gold_dataset(gold_dataset_id)
    if not ds:
        return
    ds.status = "locked"
    ds.updated_at = _utcnow()
    upsert_gold_dataset(ds)
    append_audit("gold_dataset_locked", gold_dataset_id, {})


def create_eval_run(eval_run: EvalRun) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval_runs (eval_run_id, run_id, gold_dataset_id, status, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (eval_run_id) DO UPDATE SET
                run_id = EXCLUDED.run_id,
                gold_dataset_id = EXCLUDED.gold_dataset_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload
            """,
            (
                eval_run.eval_run_id,
                eval_run.run_id,
                eval_run.gold_dataset_id,
                eval_run.status,
                Json(eval_run.model_dump(mode="json")),
            ),
        )


def get_eval_run(eval_run_id: str) -> Optional[EvalRun]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM eval_runs WHERE eval_run_id = %s", (eval_run_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return EvalRun(**payload)


def create_synth_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    now = _utcnow().isoformat()
    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "project_id": payload["project_id"],
        "status": "queued",
        "source_scope": payload["source_scope"],
        "generation_policy": payload["generation_policy"],
        "candidates": [],
        "created_at": now,
        "updated_at": now,
    }
    upsert_synth_job(job)
    append_audit("synth_job_created", job_id, {"project_id": payload["project_id"]})
    return job


def upsert_synth_job(job: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO synth_jobs (job_id, project_id, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (job_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (job["job_id"], job["project_id"], job.get("status", "queued"), Json(job)),
        )


def get_synth_job(job_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM synth_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def upsert_synth_candidate(job_id: str, candidate: Dict[str, Any]) -> None:
    ensure_schema()
    status = str(candidate.get("status", "generated"))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO synth_candidates (candidate_id, job_id, status, payload, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (candidate_id) DO UPDATE SET
                job_id = EXCLUDED.job_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (candidate["candidate_id"], job_id, status, Json(candidate)),
        )


def list_synth_candidates(job_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        if limit is None:
            cur.execute(
                "SELECT payload FROM synth_candidates WHERE job_id = %s ORDER BY candidate_id",
                (job_id,),
            )
        else:
            cur.execute(
                "SELECT payload FROM synth_candidates WHERE job_id = %s ORDER BY candidate_id LIMIT %s",
                (job_id, limit),
            )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out.append(payload)
    return out


def find_synth_candidate(candidate_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT job_id, payload FROM synth_candidates WHERE candidate_id = %s",
            (candidate_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return str(row.get("job_id")), payload


def list_scoring_policies() -> List[ScoringPolicy]:
    ensure_schema()
    out: List[ScoringPolicy] = []
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM scoring_policies ORDER BY policy_version")
        rows = cur.fetchall() or []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out.append(ScoringPolicy(**payload))
    return out


def upsert_scoring_policy(policy: ScoringPolicy) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scoring_policies (policy_version, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (policy_version) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (policy.policy_version, Json(policy.model_dump(mode="json"))),
        )


def get_config_version(config_key: str) -> Dict[str, Any] | None:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM config_versions WHERE config_key = %s",
            (config_key,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


def upsert_config_version(config_key: str, payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO config_versions (config_key, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (config_key) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (config_key, Json(payload)),
        )


def create_exp_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    now = _utcnow()
    profile = {
        "profile_id": str(uuid4()),
        "name": str(payload["name"]),
        "project_id": str(payload["project_id"]),
        "dataset_id": str(payload["dataset_id"]),
        "gold_dataset_id": str(payload["gold_dataset_id"]),
        "endpoint_target": str(payload.get("endpoint_target", "local")),
        "active": bool(payload.get("active", True)),
        "processing_profile": payload.get("processing_profile", {}),
        "retrieval_profile": payload.get("retrieval_profile", {}),
        "runtime_policy": payload.get("runtime_policy"),
        "created_at": now,
        "updated_at": now,
    }
    upsert_exp_profile(profile)
    return profile


def upsert_exp_profile(profile: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        created_at = profile.get("created_at") or _utcnow()
        updated_at = profile.get("updated_at") or _utcnow()
        payload = {
            **profile,
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at),
        }
        cur.execute(
            """
            INSERT INTO exp_profiles (
                profile_id, name, project_id, dataset_id, gold_dataset_id, endpoint_target, active, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (profile_id) DO UPDATE SET
                name = EXCLUDED.name,
                project_id = EXCLUDED.project_id,
                dataset_id = EXCLUDED.dataset_id,
                gold_dataset_id = EXCLUDED.gold_dataset_id,
                endpoint_target = EXCLUDED.endpoint_target,
                active = EXCLUDED.active,
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            (
                profile["profile_id"],
                profile["name"],
                profile["project_id"],
                profile["dataset_id"],
                profile["gold_dataset_id"],
                profile.get("endpoint_target", "local"),
                bool(profile.get("active", True)),
                Json(payload),
                created_at,
                updated_at,
            ),
        )


def list_exp_profiles(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM exp_profiles ORDER BY updated_at DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out.append(payload)
    return out


def get_exp_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM exp_profiles WHERE profile_id = %s", (profile_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def create_experiment(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    now = _utcnow()
    experiment = {
        "experiment_id": str(uuid4()),
        "name": str(payload["name"]),
        "profile_id": str(payload["profile_id"]),
        "gold_dataset_id": str(payload["gold_dataset_id"]),
        "baseline_experiment_run_id": payload.get("baseline_experiment_run_id"),
        "status": str(payload.get("status", "active")),
        "metadata": payload.get("metadata", {}),
        "created_at": now,
        "updated_at": now,
    }
    upsert_experiment(experiment)
    return experiment


def upsert_experiment(experiment: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        created_at = experiment.get("created_at") or _utcnow()
        updated_at = experiment.get("updated_at") or _utcnow()
        payload = {
            **experiment,
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at),
        }
        cur.execute(
            """
            INSERT INTO exp_experiments (
                experiment_id, profile_id, name, gold_dataset_id, baseline_experiment_run_id, status, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (experiment_id) DO UPDATE SET
                profile_id = EXCLUDED.profile_id,
                name = EXCLUDED.name,
                gold_dataset_id = EXCLUDED.gold_dataset_id,
                baseline_experiment_run_id = EXCLUDED.baseline_experiment_run_id,
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            (
                experiment["experiment_id"],
                experiment["profile_id"],
                experiment["name"],
                experiment["gold_dataset_id"],
                experiment.get("baseline_experiment_run_id"),
                experiment.get("status", "active"),
                Json(payload),
                created_at,
                updated_at,
            ),
        )


def get_experiment(experiment_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM exp_experiments WHERE experiment_id = %s", (experiment_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def create_experiment_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    run_id = str(uuid4())
    now = _utcnow()
    run = {
        "experiment_run_id": run_id,
        "experiment_id": str(payload["experiment_id"]),
        "profile_id": str(payload["profile_id"]),
        "gold_dataset_id": str(payload["gold_dataset_id"]),
        "stage_type": str(payload.get("stage_type", "proxy")),
        "status": str(payload.get("status", "queued")),
        "gate_passed": payload.get("gate_passed"),
        "idempotency_key": payload.get("idempotency_key"),
        "qa_run_id": payload.get("qa_run_id"),
        "eval_run_id": payload.get("eval_run_id"),
        "sample_size": int(payload.get("sample_size", 0)),
        "question_count": int(payload.get("question_count", 0)),
        "baseline_experiment_run_id": payload.get("baseline_experiment_run_id"),
        "metrics": payload.get("metrics", {}),
        "created_at": now,
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "error_message": payload.get("error_message"),
    }
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_runs (
                experiment_run_id, experiment_id, profile_id, gold_dataset_id, stage_type, status, gate_passed,
                idempotency_key, qa_run_id, eval_run_id, sample_size, question_count, baseline_experiment_run_id,
                metrics, payload, created_at, started_at, completed_at, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run["experiment_run_id"],
                run["experiment_id"],
                run["profile_id"],
                run["gold_dataset_id"],
                run["stage_type"],
                run["status"],
                run.get("gate_passed"),
                run.get("idempotency_key"),
                run.get("qa_run_id"),
                run.get("eval_run_id"),
                run.get("sample_size", 0),
                run.get("question_count", 0),
                run.get("baseline_experiment_run_id"),
                Json(run.get("metrics", {})),
                Json(
                    {
                        **run,
                        "created_at": now.isoformat(),
                        "started_at": run["started_at"].isoformat() if isinstance(run.get("started_at"), datetime) else run.get("started_at"),
                        "completed_at": run["completed_at"].isoformat() if isinstance(run.get("completed_at"), datetime) else run.get("completed_at"),
                    }
                ),
                now,
                run.get("started_at"),
                run.get("completed_at"),
                run.get("error_message"),
            ),
        )
    return run


def update_experiment_run(experiment_run_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ensure_schema()
    current = get_experiment_run(experiment_run_id)
    if not current:
        return None
    merged = {**current, **patch}
    created_at = merged.get("created_at")
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            created_at = _utcnow()
    if not isinstance(created_at, datetime):
        created_at = _utcnow()
    payload = {
        **merged,
        "created_at": created_at.isoformat(),
        "started_at": merged["started_at"].isoformat() if isinstance(merged.get("started_at"), datetime) else merged.get("started_at"),
        "completed_at": merged["completed_at"].isoformat() if isinstance(merged.get("completed_at"), datetime) else merged.get("completed_at"),
    }
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE exp_runs
            SET
                status = %s,
                gate_passed = %s,
                qa_run_id = %s,
                eval_run_id = %s,
                sample_size = %s,
                question_count = %s,
                baseline_experiment_run_id = %s,
                metrics = %s,
                payload = %s,
                started_at = %s,
                completed_at = %s,
                error_message = %s
            WHERE experiment_run_id = %s
            """,
            (
                merged.get("status"),
                merged.get("gate_passed"),
                merged.get("qa_run_id"),
                merged.get("eval_run_id"),
                int(merged.get("sample_size", 0)),
                int(merged.get("question_count", 0)),
                merged.get("baseline_experiment_run_id"),
                Json(merged.get("metrics", {})),
                Json(payload),
                merged.get("started_at"),
                merged.get("completed_at"),
                merged.get("error_message"),
                experiment_run_id,
            ),
        )
    return get_experiment_run(experiment_run_id)


def get_experiment_run(experiment_run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM exp_runs WHERE experiment_run_id = %s", (experiment_run_id,))
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def find_experiment_run_by_idempotency(experiment_id: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM exp_runs WHERE experiment_id = %s AND idempotency_key = %s ORDER BY created_at DESC LIMIT 1",
            (experiment_id, idempotency_key),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else None


def list_experiment_runs(experiment_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM exp_runs WHERE experiment_id = %s ORDER BY created_at DESC LIMIT %s",
            (experiment_id, limit),
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out.append(payload)
    return out


def upsert_exp_stage_cache(stage_type: str, cache_key: str, experiment_run_id: str, payload: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_stage_cache (stage_type, cache_key, experiment_run_id, payload, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (stage_type, cache_key) DO UPDATE SET
                experiment_run_id = EXCLUDED.experiment_run_id,
                payload = EXCLUDED.payload
            """,
            (stage_type, cache_key, experiment_run_id, Json(payload)),
        )


def get_exp_stage_cache(stage_type: str, cache_key: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT stage_type, cache_key, experiment_run_id, payload, created_at FROM exp_stage_cache WHERE stage_type = %s AND cache_key = %s",
            (stage_type, cache_key),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "stage_type": row.get("stage_type"),
        "cache_key": row.get("cache_key"),
        "experiment_run_id": row.get("experiment_run_id"),
        "payload": row.get("payload") if isinstance(row.get("payload"), dict) else {},
        "created_at": row.get("created_at"),
    }


def upsert_exp_score(
    experiment_run_id: str,
    experiment_id: str,
    stage_type: str,
    metrics: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_schema()
    score = {
        "score_id": str(uuid4()),
        "experiment_run_id": experiment_run_id,
        "experiment_id": experiment_id,
        "stage_type": stage_type,
        "answer_score_mean": float(metrics.get("answer_score_mean", 0.0)),
        "grounding_score_mean": float(metrics.get("grounding_score_mean", 0.0)),
        "telemetry_factor": float(metrics.get("telemetry_factor", 0.0)),
        "ttft_factor": float(metrics.get("ttft_factor", 0.0)),
        "overall_score": float(metrics.get("overall_score", 0.0)),
        "payload": payload or metrics,
    }
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_scores (
                score_id, experiment_run_id, experiment_id, stage_type, answer_score_mean, grounding_score_mean,
                telemetry_factor, ttft_factor, overall_score, payload, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (experiment_run_id) DO UPDATE SET
                experiment_id = EXCLUDED.experiment_id,
                stage_type = EXCLUDED.stage_type,
                answer_score_mean = EXCLUDED.answer_score_mean,
                grounding_score_mean = EXCLUDED.grounding_score_mean,
                telemetry_factor = EXCLUDED.telemetry_factor,
                ttft_factor = EXCLUDED.ttft_factor,
                overall_score = EXCLUDED.overall_score,
                payload = EXCLUDED.payload
            """,
            (
                score["score_id"],
                score["experiment_run_id"],
                score["experiment_id"],
                score["stage_type"],
                score["answer_score_mean"],
                score["grounding_score_mean"],
                score["telemetry_factor"],
                score["ttft_factor"],
                score["overall_score"],
                Json(score["payload"]),
            ),
        )
    return get_exp_score(experiment_run_id) or score


def get_exp_score(experiment_run_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT score_id, experiment_run_id, experiment_id, stage_type, answer_score_mean, grounding_score_mean,
                   telemetry_factor, ttft_factor, overall_score, payload, created_at
            FROM exp_scores
            WHERE experiment_run_id = %s
            """,
            (experiment_run_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return {
        "score_id": row.get("score_id"),
        "experiment_run_id": row.get("experiment_run_id"),
        "experiment_id": row.get("experiment_id"),
        "stage_type": row.get("stage_type"),
        "answer_score_mean": float(row.get("answer_score_mean") or 0.0),
        "grounding_score_mean": float(row.get("grounding_score_mean") or 0.0),
        "telemetry_factor": float(row.get("telemetry_factor") or 0.0),
        "ttft_factor": float(row.get("ttft_factor") or 0.0),
        "overall_score": float(row.get("overall_score") or 0.0),
        "payload": payload,
        "created_at": row.get("created_at"),
    }


def upsert_exp_question_metric(experiment_run_id: str, question_id: str, metric: Dict[str, Any]) -> None:
    ensure_schema()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_question_metrics (
                experiment_run_id, question_id, answer_score, grounding_score, telemetry_factor,
                ttft_factor, overall_score, route_name, segment, delta_vs_baseline, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (experiment_run_id, question_id) DO UPDATE SET
                answer_score = EXCLUDED.answer_score,
                grounding_score = EXCLUDED.grounding_score,
                telemetry_factor = EXCLUDED.telemetry_factor,
                ttft_factor = EXCLUDED.ttft_factor,
                overall_score = EXCLUDED.overall_score,
                route_name = EXCLUDED.route_name,
                segment = EXCLUDED.segment,
                delta_vs_baseline = EXCLUDED.delta_vs_baseline,
                payload = EXCLUDED.payload
            """,
            (
                experiment_run_id,
                question_id,
                float(metric.get("answer_score", 0.0)),
                float(metric.get("grounding_score", 0.0)),
                float(metric.get("telemetry_factor", 0.0)),
                float(metric.get("ttft_factor", 0.0)),
                float(metric.get("overall_score", 0.0)),
                metric.get("route_name"),
                metric.get("segment"),
                metric.get("delta_vs_baseline"),
                Json(metric),
            ),
        )


def list_exp_question_metrics(experiment_run_id: str, limit: int = 100000) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT payload FROM exp_question_metrics WHERE experiment_run_id = %s ORDER BY question_id LIMIT %s",
            (experiment_run_id, limit),
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            out.append(payload)
    return out


def upsert_exp_artifact(
    experiment_run_id: str,
    artifact_type: str,
    artifact_url: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_schema()
    artifact_id = str(uuid4())
    artifact = {
        "artifact_id": artifact_id,
        "experiment_run_id": experiment_run_id,
        "artifact_type": artifact_type,
        "artifact_url": artifact_url,
        "payload": payload or {},
    }
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_artifacts (artifact_id, experiment_run_id, artifact_type, artifact_url, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (
                artifact["artifact_id"],
                artifact["experiment_run_id"],
                artifact["artifact_type"],
                artifact["artifact_url"],
                Json(artifact["payload"]),
            ),
        )
    return artifact


def list_exp_artifacts(experiment_run_id: str) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT artifact_id, experiment_run_id, artifact_type, artifact_url, payload, created_at
            FROM exp_artifacts
            WHERE experiment_run_id = %s
            ORDER BY created_at ASC
            """,
            (experiment_run_id,),
        )
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "artifact_id": row.get("artifact_id"),
                "experiment_run_id": row.get("experiment_run_id"),
                "artifact_type": row.get("artifact_type"),
                "artifact_url": row.get("artifact_url"),
                "payload": row.get("payload") if isinstance(row.get("payload"), dict) else {},
                "created_at": row.get("created_at"),
            }
        )
    return out


def append_exp_ops_log(
    actor: str,
    command_name: str,
    target: Optional[str],
    status: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    idempotency_key: Optional[str] = None,
    error_message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> str:
    ensure_schema()
    op_id = str(uuid4())
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exp_ops_log (
                op_id, started_at, finished_at, actor, command_name, target, status, payload, idempotency_key, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                op_id,
                started_at or _utcnow(),
                finished_at,
                actor,
                command_name,
                target,
                status,
                Json(payload or {}),
                idempotency_key,
                error_message,
            ),
        )
    return op_id


def list_exp_leaderboard(
    *,
    limit: int = 50,
    stage_type: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where = ["r.status = 'completed'"]
    params: List[Any] = []
    if stage_type:
        where.append("s.stage_type = %s")
        params.append(stage_type)
    if experiment_id:
        where.append("s.experiment_id = %s")
        params.append(experiment_id)
    params.append(limit)
    where_clause = " AND ".join(where)
    query = f"""
        SELECT
            s.experiment_run_id,
            s.experiment_id,
            e.name AS experiment_name,
            s.stage_type,
            s.overall_score,
            s.answer_score_mean,
            s.grounding_score_mean,
            s.telemetry_factor,
            s.ttft_factor,
            r.created_at
        FROM exp_scores s
        JOIN exp_runs r ON r.experiment_run_id = s.experiment_run_id
        JOIN exp_experiments e ON e.experiment_id = s.experiment_id
        WHERE {where_clause}
        ORDER BY s.overall_score DESC, r.created_at DESC
        LIMIT %s
    """
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "experiment_run_id": row.get("experiment_run_id"),
                "experiment_id": row.get("experiment_id"),
                "experiment_name": row.get("experiment_name"),
                "stage_type": row.get("stage_type"),
                "overall_score": float(row.get("overall_score") or 0.0),
                "answer_score_mean": float(row.get("answer_score_mean") or 0.0),
                "grounding_score_mean": float(row.get("grounding_score_mean") or 0.0),
                "telemetry_factor": float(row.get("telemetry_factor") or 0.0),
                "ttft_factor": float(row.get("ttft_factor") or 0.0),
                "created_at": row.get("created_at"),
            }
        )
    return out
