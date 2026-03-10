from __future__ import annotations

from pathlib import Path
from http import HTTPStatus
import json

from fastapi import APIRouter, HTTPException

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import CandidateApproveRequest, SyntheticJob
from legal_rag_api.state import store
from services.synth.engine import apply_candidate_decision, build_candidates

router = APIRouter(prefix="/v1/synth", tags=["Synthetic"])
REPORTS_DIR = Path(__file__).resolve().parents[5] / "reports"


@router.post("/jobs")
def create_job(payload: SyntheticJob) -> dict:
    job_payload = {
        "project_id": payload.project_id,
        "source_scope": payload.source_scope,
        "generation_policy": payload.generation_policy,
    }
    if runtime_pg.enabled():
        job = runtime_pg.create_synth_job(job_payload)
    else:
        job = store.create_synth_job(job_payload)
    candidates = build_candidates(job, payload.generation_policy.get("target_count", 5))
    job["status"] = "review"
    job["candidates"] = [c["candidate_id"] for c in candidates]
    if runtime_pg.enabled():
        runtime_pg.upsert_synth_job(job)
        for c in candidates:
            runtime_pg.upsert_synth_candidate(job["job_id"], c)
    else:
        for c in candidates:
            store.synth_candidates[job["job_id"]][c["candidate_id"]] = c
    return job


@router.get("/jobs/{jobId}")
def get_job(jobId: str) -> dict:
    if runtime_pg.enabled():
        job = runtime_pg.get_synth_job(jobId)
        if not job:
            raise HTTPException(status_code=404, detail="synth job not found")
        return job
    if jobId not in store.synth_jobs:
        raise HTTPException(status_code=404, detail="synth job not found")
    return store.synth_jobs[jobId]


@router.post("/jobs/{jobId}/preview")
def preview(jobId: str, payload: dict) -> dict:
    if runtime_pg.enabled():
        job = runtime_pg.get_synth_job(jobId)
        if not job:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="synth job not found")
    else:
        if jobId not in store.synth_jobs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="synth job not found")
        job = store.synth_jobs[jobId]
    limit = int(payload.get("limit", 20))
    if runtime_pg.enabled():
        candidates = runtime_pg.list_synth_candidates(jobId, limit=limit)
    else:
        candidates = [
            candidate
            for candidate in store.synth_candidates.get(jobId, {}).values()
        ]
    return {"items": candidates[:limit]}


@router.post("/items/{candidateId}/approve")
def approve_item(candidateId: str, payload: CandidateApproveRequest) -> dict:
    if runtime_pg.enabled():
        found = runtime_pg.find_synth_candidate(candidateId)
        if not found:
            raise HTTPException(status_code=404, detail="candidate not found")
        job_id, candidate = found
        candidates = {candidateId: candidate}
        updated = apply_candidate_decision(candidates, candidateId, payload.decision, payload.model_dump(mode="json"))
        runtime_pg.upsert_synth_candidate(job_id, updated)
        return {"status": updated.get("status", "unknown")}

    # naive lookup across jobs (bootstrap only)
    for job_id, candidates in store.synth_candidates.items():
        if candidateId in candidates:
            updated = apply_candidate_decision(candidates, candidateId, payload.decision, payload.model_dump())
            return {"status": updated.get("status", "unknown")}
    raise HTTPException(status_code=404, detail="candidate not found")


@router.post("/jobs/{jobId}/publish")
def publish(jobId: str, payload: dict) -> dict:
    if runtime_pg.enabled():
        job = runtime_pg.get_synth_job(jobId)
        if not job:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="synth job not found")
        candidates = runtime_pg.list_synth_candidates(jobId)
        job["status"] = "published"
        runtime_pg.upsert_synth_job(job)
    else:
        if jobId not in store.synth_jobs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="synth job not found")
        candidates = [c for c in store.synth_candidates.get(jobId, {}).values()]
        store.synth_jobs[jobId]["status"] = "published"
    dataset_id = jobId
    path = REPORTS_DIR / f"synth_{jobId}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"dataset_id": dataset_id, "artifact_url": path.as_uri()}
