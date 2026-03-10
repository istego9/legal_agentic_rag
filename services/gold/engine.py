"""Gold dataset service helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from legal_rag_api.storage import InMemoryStore


def lock_dataset(store: InMemoryStore, gold_dataset_id: str) -> None:
    ds = store.gold_datasets[gold_dataset_id]
    data = ds.model_dump()
    data["status"] = "locked"
    data["updated_at"] = datetime.now(timezone.utc)
    store.gold_datasets[gold_dataset_id] = ds.__class__(**data)
    store.audit_log.append(
        {
            "event": "gold_dataset_locked",
            "target": gold_dataset_id,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )


def add_source_set(store: InMemoryStore, gold_question_id: str, dataset_id: str, payload: Dict[str, Any]) -> Dict[str, str]:
    q = store.gold_questions[dataset_id][gold_question_id]
    source_set_id = payload.get("source_set_id") or "source-set"
    if q.source_sets is None:
        q.source_sets = []
    q.source_sets.append(
        {
            "source_set_id": source_set_id,
            "is_primary": payload["is_primary"],
            "page_ids": payload["page_ids"],
            "notes": payload.get("notes"),
        }
    )
    store.gold_questions[dataset_id][gold_question_id] = q
    store.audit_log.append(
        {
            "event": "gold_source_set_added",
            "target": gold_question_id,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"source_set_id": source_set_id}
