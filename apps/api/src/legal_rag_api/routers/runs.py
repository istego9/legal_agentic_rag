from __future__ import annotations

from pathlib import Path
from datetime import datetime
from http import HTTPStatus
import json

from fastapi import APIRouter, HTTPException

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import (
    ExportRequest,
    OfficialSubmissionExportRequest,
    RunSummary,
    export_used_source_page_ids,
)
from legal_rag_api.official_submission import (
    DEFAULT_ARCHITECTURE_SUMMARY,
    build_official_submission_answers,
    submission_preflight_report,
)
from legal_rag_api.state import store

router = APIRouter(prefix="/v1/runs", tags=["Runs"])
REPORTS_DIR = Path(__file__).resolve().parents[5] / "reports"
LOCKED_DATASET_ERROR_DETAIL = "gold dataset is locked and immutable"
PROJECT_MISMATCH_ERROR_DETAIL = "gold dataset project does not match run project"


def _submission_contract_preflight_or_raise(run_id: str, questions: dict[str, object]) -> dict:
    preflight = submission_preflight_report(questions)
    if preflight.get("blocking_failed"):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "submission_contract_preflight_failed",
                "run_id": run_id,
                "preflight": preflight,
            },
        )
    return preflight


def _artifact_project_id(artifact: object) -> str:
    if artifact is None:
        return ""
    if hasattr(artifact, "document_viewer"):
        document_viewer = getattr(artifact, "document_viewer")
    elif isinstance(artifact, dict):
        document_viewer = artifact.get("document_viewer")
    else:
        document_viewer = None
    if isinstance(document_viewer, dict):
        return str(document_viewer.get("project_id", "")).strip()
    return ""


@router.get("/{runId}")
def get_run(runId: str) -> dict:
    if runtime_pg.enabled():
        run = runtime_pg.get_run(runId)
        if not run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
    else:
        if runId not in store.runs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        run = store.runs[runId]
    return RunSummary(
        run_id=run["run_id"],
        dataset_id=run["dataset_id"],
        status=run["status"],
        question_count=run["question_count"],
        created_at=run["created_at"] if isinstance(run["created_at"], datetime) else datetime.fromisoformat(run["created_at"]),
    ).model_dump(mode="json")


@router.get("/{runId}/questions/{questionId}")
def get_question_in_run(runId: str, questionId: str) -> dict:
    if runtime_pg.enabled():
        response = runtime_pg.get_run_question(runId, questionId)
        if not response:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="answer not found")
        return response.model_dump(mode="json")
    if runId not in store.run_questions or questionId not in store.run_questions[runId]:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="answer not found")
    return store.run_questions[runId][questionId].model_dump(mode="json")


@router.get("/{runId}/questions/{questionId}/detail")
def get_question_detail_in_run(runId: str, questionId: str) -> dict:
    if runtime_pg.enabled():
        artifact = runtime_pg.get_run_question_review(runId, questionId)
        if not artifact:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run question detail not found")
        return artifact.model_dump(mode="json")
    artifact = store.get_run_question_review(runId, questionId)
    if not artifact:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run question detail not found")
    return artifact.model_dump(mode="json")


@router.post("/{runId}/questions/{questionId}/promote-to-gold")
def promote_question_to_gold(runId: str, questionId: str, payload: dict) -> dict:
    gold_dataset_id = str(payload.get("gold_dataset_id", "")).strip()
    if not gold_dataset_id:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="gold_dataset_id is required")

    if runtime_pg.enabled():
        artifact = runtime_pg.get_run_question_review(runId, questionId)
        if not artifact:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run question detail not found")
        dataset = runtime_pg.get_gold_dataset(gold_dataset_id)
        if not dataset:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        if dataset.status == "locked":
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=LOCKED_DATASET_ERROR_DETAIL)
        artifact_project_id = _artifact_project_id(artifact)
        if artifact_project_id and dataset.project_id != artifact_project_id:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=PROJECT_MISMATCH_ERROR_DETAIL)
        promotion_preview = artifact.promotion_preview if isinstance(artifact.promotion_preview, dict) else {}
        source_sets = promotion_preview.get("source_sets") or []
        if not isinstance(source_sets, list) or not source_sets:
            raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="run question has no used sources to promote")
        question = runtime_pg.add_gold_question(
            gold_dataset_id,
            {
                "question_id": questionId,
                "canonical_answer": artifact.response.answer,
                "answer_type": artifact.response.answer_type,
                "source_sets": source_sets,
                "notes": (source_sets[0] or {}).get("notes"),
            },
        )
    else:
        artifact = store.get_run_question_review(runId, questionId)
        if not artifact:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run question detail not found")
        dataset = store.gold_datasets.get(gold_dataset_id)
        if not dataset:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        if dataset.status == "locked":
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=LOCKED_DATASET_ERROR_DETAIL)
        artifact_project_id = _artifact_project_id(artifact)
        if artifact_project_id and dataset.project_id != artifact_project_id:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=PROJECT_MISMATCH_ERROR_DETAIL)
        promotion_preview = artifact.promotion_preview if isinstance(artifact.promotion_preview, dict) else {}
        source_sets = promotion_preview.get("source_sets") or []
        if not isinstance(source_sets, list) or not source_sets:
            raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="run question has no used sources to promote")
        question = store.add_gold_question(
            gold_dataset_id,
            {
                "question_id": questionId,
                "canonical_answer": artifact.response.answer,
                "answer_type": artifact.response.answer_type,
                "source_sets": source_sets,
                "notes": (source_sets[0] or {}).get("notes"),
            },
        )
    return {
        "status": "promoted",
        "gold_dataset_id": gold_dataset_id,
        "gold_question_id": question.gold_question_id,
    }


@router.post("/{runId}/export-submission")
def export_submission(runId: str, payload: ExportRequest) -> dict:
    if runtime_pg.enabled():
        run = runtime_pg.get_run(runId)
        if not run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        qs = runtime_pg.list_run_questions(runId)
    else:
        if runId not in store.runs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        run = store.runs[runId]
        qs = store.run_questions.get(runId, {})
    preflight = _submission_contract_preflight_or_raise(runId, qs)
    answers = []
    for qid, pred in qs.items():
        answers.append(
            {
                "question_id": qid,
                "answer": pred.answer,
                "sources": export_used_source_page_ids(pred.sources),
                "telemetry": pred.telemetry.model_dump(mode="json"),
            }
        )
    out = {
        "run_id": runId,
        "question_count": len(answers),
        "created_at": run["created_at"],
        "artifact": {"items": answers},
    }
    path = REPORTS_DIR / f"submission_{runId}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": answers}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "artifact_url": path.as_uri(),
        "question_count": len(answers),
        "preflight": preflight,
    }


@router.post("/{runId}/export-submission-official")
def export_submission_official(runId: str, payload: OfficialSubmissionExportRequest) -> dict:
    if runtime_pg.enabled():
        run = runtime_pg.get_run(runId)
        if not run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        qs = runtime_pg.list_run_questions(runId)
    else:
        if runId not in store.runs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        run = store.runs[runId]
        qs = store.run_questions.get(runId, {})

    preflight = _submission_contract_preflight_or_raise(runId, qs)
    architecture_summary = str(payload.architecture_summary or "").strip() or DEFAULT_ARCHITECTURE_SUMMARY
    answers = build_official_submission_answers(
        qs,
        default_page_index_base=int(payload.page_index_base),
    )
    official_payload = {
        "architecture_summary": architecture_summary,
        "answers": answers,
    }
    path = REPORTS_DIR / f"submission_official_{runId}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(official_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "artifact_url": path.as_uri(),
        "question_count": len(answers),
        "preflight": preflight,
        "format": "official_starter_kit_v1",
        "run_id": runId,
        "created_at": run["created_at"],
    }
