"""Global runtime state persistence in PostgreSQL."""

from __future__ import annotations

import os
from dataclasses import fields
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional

from pydantic import BaseModel

from legal_rag_api.contracts import EvalRun, GoldDataset, GoldQuestion, QueryResponse, ScoringPolicy
from legal_rag_api.storage import InMemoryStore

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None
    Json = None


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STATE_KEY = "global_store_v1"
_SCHEMA_READY = False
_SCHEMA_LOCK = Lock()

MODEL_MAP = {
    "QueryResponse": QueryResponse,
    "EvalRun": EvalRun,
    "GoldDataset": GoldDataset,
    "GoldQuestion": GoldQuestion,
    "ScoringPolicy": ScoringPolicy,
}


def enabled() -> bool:
    return bool(DATABASE_URL and psycopg is not None)


def _connect():
    if not enabled():
        raise RuntimeError("state postgres persistence disabled")
    return psycopg.connect(DATABASE_URL, autocommit=True)


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
                CREATE TABLE IF NOT EXISTS runtime_state (
                    state_key TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        _SCHEMA_READY = True


def _encode(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            "__kind__": "pydantic",
            "__class__": value.__class__.__name__,
            "data": _encode(value.model_dump(mode="json")),
        }
    if isinstance(value, datetime):
        return {"__kind__": "datetime", "value": value.isoformat()}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    marker = value.get("__kind__")
    if marker == "datetime":
        return datetime.fromisoformat(str(value.get("value")))
    if marker == "pydantic":
        cls_name = str(value.get("__class__", ""))
        data = _decode(value.get("data"))
        cls = MODEL_MAP.get(cls_name)
        if cls and isinstance(data, dict):
            return cls(**data)
        return data
    return {k: _decode(v) for k, v in value.items()}


def _coerce_models(store: InMemoryStore) -> None:
    eval_runs: Dict[str, Any] = {}
    for key, item in store.eval_runs.items():
        if isinstance(item, EvalRun):
            eval_runs[key] = item
        elif isinstance(item, dict):
            eval_runs[key] = EvalRun(**item)
    store.eval_runs = eval_runs

    gold_datasets: Dict[str, Any] = {}
    for key, item in store.gold_datasets.items():
        if isinstance(item, GoldDataset):
            gold_datasets[key] = item
        elif isinstance(item, dict):
            gold_datasets[key] = GoldDataset(**item)
    store.gold_datasets = gold_datasets

    gold_questions: Dict[str, Dict[str, GoldQuestion]] = {}
    for dataset_id, qs in store.gold_questions.items():
        question_map: Dict[str, GoldQuestion] = {}
        if isinstance(qs, dict):
            for qid, item in qs.items():
                if isinstance(item, GoldQuestion):
                    question_map[qid] = item
                elif isinstance(item, dict):
                    question_map[qid] = GoldQuestion(**item)
        gold_questions[dataset_id] = question_map
    store.gold_questions = gold_questions

    scoring_policies: Dict[str, ScoringPolicy] = {}
    for key, item in store.scoring_policies.items():
        if isinstance(item, ScoringPolicy):
            scoring_policies[key] = item
        elif isinstance(item, dict):
            scoring_policies[key] = ScoringPolicy(**item)
    store.scoring_policies = scoring_policies

    run_questions: Dict[str, Dict[str, QueryResponse]] = {}
    for run_id, responses in store.run_questions.items():
        response_map: Dict[str, QueryResponse] = {}
        if isinstance(responses, dict):
            for qid, item in responses.items():
                if isinstance(item, QueryResponse):
                    response_map[qid] = item
                elif isinstance(item, dict):
                    response_map[qid] = QueryResponse(**item)
        run_questions[run_id] = response_map
    store.run_questions = run_questions


def save_store(store: InMemoryStore) -> None:
    if not enabled():
        return
    ensure_schema()
    payload = {}
    for f in fields(store):
        payload[f.name] = _encode(getattr(store, f.name))
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runtime_state (state_key, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (state_key) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = NOW()
            """,
            (STATE_KEY, Json(payload)),
        )


def load_store(store: InMemoryStore) -> bool:
    if not enabled():
        return False
    ensure_schema()
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT payload FROM runtime_state WHERE state_key = %s", (STATE_KEY,))
        row = cur.fetchone()
    if not row or "payload" not in row:
        return False
    payload = _decode(row["payload"])
    if not isinstance(payload, dict):
        return False
    for f in fields(store):
        if f.name in payload:
            setattr(store, f.name, payload[f.name])
    _coerce_models(store)
    return True
