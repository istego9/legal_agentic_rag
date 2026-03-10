from __future__ import annotations

from pathlib import Path
from http import HTTPStatus
import json

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import ReviewRequest, SourceSetCreate
from legal_rag_api.state import store
from services.eval.engine import build_gold_export_compatibility_assertions
from services.gold.engine import add_source_set, lock_dataset

router = APIRouter(prefix="/v1/gold", tags=["Gold"])
REPORTS_DIR = Path(__file__).resolve().parents[5] / "reports"
LOCKED_DATASET_ERROR_DETAIL = "gold dataset is locked and immutable"
LOCKED_MUTATION_AUDIT_EVENT = "gold_dataset_mutation_rejected_locked"


def _append_locked_mutation_audit(*, dataset_id: str, operation: str, target: str | None) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "dataset_id": dataset_id,
        "operation": operation,
        "at": timestamp,
    }
    audit_target = target or dataset_id
    if runtime_pg.enabled():
        runtime_pg.append_audit(LOCKED_MUTATION_AUDIT_EVENT, audit_target, payload)
    else:
        store.audit_log.append(
            {
                "event": LOCKED_MUTATION_AUDIT_EVENT,
                "target": audit_target,
                **payload,
            }
        )


def _ensure_dataset_mutable(*, dataset_id: str, operation: str, target: str | None = None) -> None:
    if runtime_pg.enabled():
        ds = runtime_pg.get_gold_dataset(dataset_id)
    else:
        ds = store.gold_datasets.get(dataset_id)

    if not ds:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
    if ds.status == "locked":
        _append_locked_mutation_audit(dataset_id=dataset_id, operation=operation, target=target)
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=LOCKED_DATASET_ERROR_DETAIL)


@router.post("/datasets")
def create_dataset(payload: dict) -> dict:
    required = {"project_id", "name", "version"}
    missing = required - payload.keys()
    if missing:
        raise HTTPException(status_code=422, detail=f"missing fields: {sorted(missing)}")
    if runtime_pg.enabled():
        ds = runtime_pg.create_gold_dataset(payload)
    else:
        ds = store.create_gold_dataset(payload)
    return ds.model_dump(mode="json")


@router.get("/datasets/{goldDatasetId}")
def get_dataset(goldDatasetId: str) -> dict:
    if runtime_pg.enabled():
        ds = runtime_pg.get_gold_dataset(goldDatasetId)
        if not ds:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
    else:
        if goldDatasetId not in store.gold_datasets:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        ds = store.gold_datasets[goldDatasetId]
    return ds.model_dump(mode="json")


@router.post("/datasets/{goldDatasetId}/questions")
def create_question(goldDatasetId: str, payload: dict) -> dict:
    _ensure_dataset_mutable(dataset_id=goldDatasetId, operation="create_question")
    if "question_id" not in payload:
        raise HTTPException(status_code=422, detail="question_id is required")
    if "canonical_answer" not in payload:
        raise HTTPException(status_code=422, detail="canonical_answer is required")
    if "answer_type" not in payload:
        raise HTTPException(status_code=422, detail="answer_type is required")
    if "source_sets" not in payload:
        raise HTTPException(status_code=422, detail="source_sets is required")
    if not isinstance(payload["source_sets"], list) or not payload["source_sets"]:
        raise HTTPException(status_code=422, detail="source_sets must be non-empty list")
    if runtime_pg.enabled():
        q = runtime_pg.add_gold_question(goldDatasetId, payload)
    else:
        q = store.add_gold_question(goldDatasetId, payload)
    return q.model_dump(mode="json")


@router.patch("/questions/{goldQuestionId}")
def update_question(goldQuestionId: str, payload: dict) -> dict:
    if runtime_pg.enabled():
        found = runtime_pg.find_gold_question(goldQuestionId)
        if not found:
            raise HTTPException(status_code=404, detail="gold question not found")
        dataset_id, q = found
        _ensure_dataset_mutable(dataset_id=dataset_id, operation="update_question", target=goldQuestionId)
        for key, value in payload.items():
            if hasattr(q, key):
                setattr(q, key, value)
        runtime_pg.upsert_gold_question(q)
        runtime_pg.append_audit(
            "gold_question_updated",
            goldQuestionId,
            {"at": datetime.now(timezone.utc).isoformat()},
        )
        return q.model_dump(mode="json")

    # locate dataset
    for dataset_id, questions in store.gold_questions.items():
        if goldQuestionId in questions:
            _ensure_dataset_mutable(dataset_id=dataset_id, operation="update_question", target=goldQuestionId)
            q = questions[goldQuestionId]
            for key, value in payload.items():
                if hasattr(q, key):
                    setattr(q, key, value)
            questions[goldQuestionId] = q
            store.audit_log.append(
                {
                    "event": "gold_question_updated",
                    "target": goldQuestionId,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return q.model_dump(mode="json")
    raise HTTPException(status_code=404, detail="gold question not found")


@router.post("/questions/{goldQuestionId}/source-sets")
def add_source_set_endpoint(goldQuestionId: str, payload: SourceSetCreate) -> dict:
    if runtime_pg.enabled():
        found = runtime_pg.find_gold_question(goldQuestionId)
        if not found:
            raise HTTPException(status_code=404, detail="gold question not found")
        dataset_id, question = found
        _ensure_dataset_mutable(dataset_id=dataset_id, operation="add_source_set", target=goldQuestionId)
        source_set_id = str(uuid4())
        source_sets = list(question.source_sets or [])
        source_sets.append(
            {
                "source_set_id": source_set_id,
                "is_primary": payload.is_primary,
                "page_ids": payload.page_ids,
                "notes": payload.notes,
            }
        )
        question.source_sets = source_sets
        runtime_pg.upsert_gold_question(question)
        runtime_pg.append_audit("gold_source_set_added", goldQuestionId, {"dataset_id": dataset_id})
        return {"source_set_id": source_set_id}
    for dataset_id, questions in store.gold_questions.items():
        if goldQuestionId in questions:
            _ensure_dataset_mutable(dataset_id=dataset_id, operation="add_source_set", target=goldQuestionId)
            return add_source_set(store, goldQuestionId, dataset_id, payload.model_dump())
    raise HTTPException(status_code=404, detail="gold question not found")


@router.post("/questions/{goldQuestionId}/review")
def review_question(goldQuestionId: str, payload: ReviewRequest) -> dict:
    if runtime_pg.enabled():
        found = runtime_pg.find_gold_question(goldQuestionId)
        if not found:
            raise HTTPException(status_code=404, detail="gold question not found")
        dataset_id, _ = found
        _ensure_dataset_mutable(dataset_id=dataset_id, operation="review_question", target=goldQuestionId)
        q = runtime_pg.set_gold_question_review(goldQuestionId, dataset_id, payload.decision, payload.comment)
        if not q:
            raise HTTPException(status_code=404, detail="gold question not found")
        return {"status": q.review_status}
    for dataset_id, questions in store.gold_questions.items():
        if goldQuestionId in questions:
            _ensure_dataset_mutable(dataset_id=dataset_id, operation="review_question", target=goldQuestionId)
            q = store.set_gold_question_review(goldQuestionId, dataset_id, payload.decision, payload.comment)
            return {"status": q.review_status}
    raise HTTPException(status_code=404, detail="gold question not found")


@router.post("/datasets/{goldDatasetId}/lock")
def lock_dataset_endpoint(goldDatasetId: str, payload: dict) -> dict:
    if runtime_pg.enabled():
        ds = runtime_pg.get_gold_dataset(goldDatasetId)
        if not ds:
            raise HTTPException(status_code=404, detail="gold dataset not found")
        if ds.status == "locked":
            return {"status": "already_locked"}
        runtime_pg.lock_gold_dataset(goldDatasetId)
        return {"status": "locked"}
    if goldDatasetId not in store.gold_datasets:
        raise HTTPException(status_code=404, detail="gold dataset not found")
    if store.gold_datasets[goldDatasetId].status == "locked":
        return {"status": "already_locked"}
    lock_dataset(store, goldDatasetId)
    return {"status": "locked"}


@router.get("/datasets/{goldDatasetId}/export")
def export_dataset(goldDatasetId: str) -> dict:
    if runtime_pg.enabled():
        if not runtime_pg.get_gold_dataset(goldDatasetId):
            raise HTTPException(status_code=404, detail="gold dataset not found")
        qs = [q.model_dump(mode="json") for q in runtime_pg.list_gold_questions(goldDatasetId).values()]
    else:
        if goldDatasetId not in store.gold_datasets:
            raise HTTPException(status_code=404, detail="gold dataset not found")
        qs = [q.model_dump(mode="json") for q in store.gold_questions.get(goldDatasetId, {}).values()]
    eval_export_compatibility = build_gold_export_compatibility_assertions(qs)
    path = REPORTS_DIR / f"gold_{goldDatasetId}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "items": qs,
                "eval_export_compatibility": eval_export_compatibility,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "artifact_url": path.as_uri(),
        "artifact_count": len(qs),
        "eval_export_compatibility": eval_export_compatibility,
    }
