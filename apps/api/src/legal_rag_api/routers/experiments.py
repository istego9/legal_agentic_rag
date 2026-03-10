from __future__ import annotations

import os
from datetime import datetime, timezone
from http import HTTPStatus

from fastapi import APIRouter, HTTPException, Query

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import (
    ExperimentCompareRequest,
    ExperimentCreateRequest,
    ExperimentProfileCreate,
    ExperimentRunCreateRequest,
)
from legal_rag_api.state import store
from services.experiments.engine import compare_experiment_runs, execute_experiment, experiment_analysis

router = APIRouter(prefix="/v1/experiments", tags=["Experiments"])


def _enabled() -> bool:
    env = os.getenv("EXPERIMENT_PLATFORM_V1", "1")
    env_enabled = env not in {"0", "false", "False", "off", "OFF"}
    mem_enabled = store.feature_flags.get("experiment_platform_v1", True)
    return bool(env_enabled and mem_enabled)


def _ensure_enabled() -> None:
    if not _enabled():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="experiment platform disabled")


def _append_ops_log(
    actor: str,
    command_name: str,
    target: str | None,
    status: str,
    payload: dict,
    *,
    idempotency_key: str | None = None,
    error_message: str | None = None,
) -> None:
    started_at = datetime.now(timezone.utc)
    if runtime_pg.enabled():
        runtime_pg.append_exp_ops_log(
            actor=actor,
            command_name=command_name,
            target=target,
            status=status,
            payload=payload,
            idempotency_key=idempotency_key,
            error_message=error_message,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
    else:
        store.append_exp_ops_log(
            actor=actor,
            command_name=command_name,
            target=target,
            status=status,
            payload=payload,
            idempotency_key=idempotency_key,
            error_message=error_message,
        )


def _get_profile(profile_id: str) -> dict | None:
    if runtime_pg.enabled():
        return runtime_pg.get_exp_profile(profile_id)
    return store.exp_profiles.get(profile_id)


def _get_experiment(experiment_id: str) -> dict | None:
    if runtime_pg.enabled():
        return runtime_pg.get_experiment(experiment_id)
    return store.exp_experiments.get(experiment_id)


@router.post("/profiles")
def create_profile(payload: ExperimentProfileCreate) -> dict:
    _ensure_enabled()
    gold_id = payload.gold_dataset_id
    if runtime_pg.enabled():
        if not runtime_pg.get_gold_dataset(gold_id):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        profile = runtime_pg.create_exp_profile(payload.model_dump(mode="json"))
    else:
        if gold_id not in store.gold_datasets:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        profile = store.create_exp_profile(payload.model_dump(mode="json"))
    _append_ops_log("ui", "experiment_profile_create", profile.get("profile_id"), "completed", payload.model_dump(mode="json"))
    return profile


@router.get("/profiles")
def list_profiles(limit: int = Query(default=50, ge=1, le=1000)) -> dict:
    _ensure_enabled()
    if runtime_pg.enabled():
        items = runtime_pg.list_exp_profiles(limit=limit)
    else:
        values = list(store.exp_profiles.values())
        values.sort(key=lambda row: str(row.get("updated_at", "")), reverse=True)
        items = values[:limit]
    return {"items": items, "total": len(items)}


@router.post("")
def create_experiment_endpoint(payload: ExperimentCreateRequest) -> dict:
    _ensure_enabled()
    profile = _get_profile(payload.profile_id)
    if not profile:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="profile not found")
    gold_dataset_id = payload.gold_dataset_id or str(profile.get("gold_dataset_id", ""))
    if runtime_pg.enabled():
        if not runtime_pg.get_gold_dataset(gold_dataset_id):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        experiment = runtime_pg.create_experiment(
            {
                **payload.model_dump(mode="json"),
                "gold_dataset_id": gold_dataset_id,
                "status": "active",
            }
        )
    else:
        if gold_dataset_id not in store.gold_datasets:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        experiment = store.create_experiment(
            {
                **payload.model_dump(mode="json"),
                "gold_dataset_id": gold_dataset_id,
                "status": "active",
            }
        )
    _append_ops_log("ui", "experiment_create", experiment.get("experiment_id"), "completed", payload.model_dump(mode="json"))
    return experiment


@router.get("/leaderboard")
def leaderboard(
    limit: int = Query(default=50, ge=1, le=1000),
    stage_type: str | None = Query(default=None),
    experiment_id: str | None = Query(default=None),
) -> dict:
    _ensure_enabled()
    if runtime_pg.enabled():
        items = runtime_pg.list_exp_leaderboard(limit=limit, stage_type=stage_type, experiment_id=experiment_id)
    else:
        items = store.list_exp_leaderboard(limit=limit, stage_type=stage_type, experiment_id=experiment_id)
    return {"items": items, "total": len(items)}


@router.get("/{experimentId}")
def get_experiment_endpoint(experimentId: str) -> dict:
    _ensure_enabled()
    experiment = _get_experiment(experimentId)
    if not experiment:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="experiment not found")
    if runtime_pg.enabled():
        runs = runtime_pg.list_experiment_runs(experimentId, limit=100)
    else:
        runs = [
            run
            for run in store.exp_runs.values()
            if run.get("experiment_id") == experimentId
        ]
        runs.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    return {**experiment, "runs": runs}


@router.post("/{experimentId}/runs", status_code=202)
async def run_experiment_endpoint(experimentId: str, payload: ExperimentRunCreateRequest) -> dict:
    _ensure_enabled()
    experiment = _get_experiment(experimentId)
    if not experiment:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="experiment not found")
    profile = _get_profile(str(experiment.get("profile_id")))
    if not profile:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="experiment profile not found")
    actor = payload.actor or ("agent" if payload.agent_mode else "ui")
    try:
        result = await execute_experiment(experiment, profile, payload)
        _append_ops_log(
            actor,
            "experiment_run",
            str(result.get("experiment_run_id")),
            "completed",
            payload.model_dump(mode="json"),
            idempotency_key=payload.idempotency_key,
        )
        return result
    except Exception as exc:
        _append_ops_log(
            actor,
            "experiment_run",
            experimentId,
            "failed",
            payload.model_dump(mode="json"),
            idempotency_key=payload.idempotency_key,
            error_message=str(exc),
        )
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs/{experimentRunId}")
def get_run_endpoint(experimentRunId: str) -> dict:
    _ensure_enabled()
    if runtime_pg.enabled():
        run = runtime_pg.get_experiment_run(experimentRunId)
    else:
        run = store.exp_runs.get(experimentRunId)
    if not run:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="experiment run not found")
    return run


@router.get("/runs/{experimentRunId}/analysis")
def get_run_analysis(experimentRunId: str) -> dict:
    _ensure_enabled()
    try:
        return experiment_analysis(experimentRunId)
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc


@router.post("/compare")
def compare_runs(payload: ExperimentCompareRequest) -> dict:
    _ensure_enabled()
    try:
        return compare_experiment_runs(payload.left_experiment_run_id, payload.right_experiment_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
