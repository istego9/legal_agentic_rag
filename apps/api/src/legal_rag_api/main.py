"""Application entrypoint for Legal Agentic RAG API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from legal_rag_api import corpus_pg, runtime_pg  # noqa: E402
from legal_rag_api.otel import get_otel_status, setup_fastapi_otel  # noqa: E402
from legal_rag_api.state import competition_mode_enabled, is_contest_safe_store, load_persisted_state  # noqa: E402
from legal_rag_api.routers import (  # noqa: E402
    corpus as corpus_router,
    qa as qa_router,
    runs as runs_router,
    eval as eval_router,
    gold as gold_router,
    synth as synth_router,
    config as config_router,
    experiments as experiments_router,
)


app = FastAPI(
    title="Legal Agentic RAG API",
    version="0.1.0",
    description="Contract-first API for the extracted Legal Agentic RAG platform.",
)
setup_fastapi_otel(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_load_runtime_state() -> None:
    if competition_mode_enabled():
        if not is_contest_safe_store():
            raise RuntimeError(
                "COMPETITION_MODE=1 requires non-in-memory state binding. "
                "Reload process with contest-safe store configuration."
            )
        if not runtime_pg.enabled():
            raise RuntimeError(
                "COMPETITION_MODE=1 requires runtime PostgreSQL backing store "
                "(set DATABASE_URL and install psycopg)."
            )
        if not corpus_pg.enabled():
            raise RuntimeError(
                "COMPETITION_MODE=1 requires corpus PostgreSQL backing store "
                "(set DATABASE_URL and install psycopg)."
            )
        runtime_pg.ensure_schema()
        corpus_pg.ensure_schema()
        return

    last_error: Exception | None = None
    for _ in range(15):
        try:
            if runtime_pg.enabled():
                runtime_pg.ensure_schema()
            if corpus_pg.enabled():
                corpus_pg.ensure_schema()
            load_persisted_state()
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    if last_error is not None:
        raise RuntimeError("startup persistence bootstrap failed after retries") from last_error


app.include_router(corpus_router.router)
app.include_router(qa_router.router)
app.include_router(runs_router.router)
app.include_router(eval_router.router)
app.include_router(gold_router.router)
app.include_router(synth_router.router)
app.include_router(config_router.router)
app.include_router(experiments_router.router)


@app.get("/v1/health")
def health() -> dict[str, str]:
    otel_status = get_otel_status()
    return {
        "status": "ok",
        "version": "0.1.0",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "otel_enabled": "true" if bool(otel_status.get("enabled")) else "false",
        "otel_reason": str(otel_status.get("reason", "")),
    }


@app.get("/v1")
def root() -> dict[str, str]:
    return {"name": "legal-agentic-rag-api", "status": "ok"}
