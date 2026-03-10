"""Synthetic dataset helpers."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4


def build_candidates(job_payload: Dict[str, Any], limit: int = 25) -> List[Dict[str, Any]]:
    answer_types = list(job_payload.get("generation_policy", {}).get("answer_type_mix", {}).keys()) or ["free_text"]
    candidates: List[Dict[str, Any]] = []
    for i in range(limit):
        answer_type = random.choice(answer_types)
        candidates.append(
            {
                "candidate_id": str(uuid4()),
                "question": f"Draft synthetic question #{i + 1}",
                "answer_type": answer_type,
                "status": "generated",
                "supporting_pages": job_payload.get("source_scope", {}).get("document_ids", []),
                "provenance": {
                    "template": "bootstrap_template",
                    "route": "article_lookup",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )
    return candidates


def apply_candidate_decision(candidates: Dict[str, Dict[str, Any]], candidate_id: str, decision: str, payload: Dict[str, Any]) -> Dict[str, str]:
    if candidate_id not in candidates:
        raise KeyError("candidate not found")
    item = candidates[candidate_id]
    if decision == "approve":
        item["status"] = "approved"
    elif decision == "reject":
        item["status"] = "rejected"
    elif decision == "edit":
        if payload.get("edited_question"):
            item["question"] = payload["edited_question"]
        if payload.get("edited_answer") is not None:
            item["canonical_answer"] = payload["edited_answer"]
        if payload.get("edited_source_pages") is not None:
            item["supporting_pages"] = payload["edited_source_pages"]
        item["status"] = "approved"
    return item

