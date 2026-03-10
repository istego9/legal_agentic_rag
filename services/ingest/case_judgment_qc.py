"""Quality checks for case judgment extraction artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from uuid import uuid4


@dataclass
class CaseJudgmentQCResult:
    checks: List[Dict[str, Any]]
    blocking_failed: bool


def _check(
    *,
    qc_stage: str,
    status: str,
    severity: str,
    message: str,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "qc_result_id": str(uuid4()),
        "qc_stage": qc_stage,
        "status": status,
        "severity": severity,
        "message": message,
        "details": details or {},
    }


def evaluate_case_judgment_qc(
    *,
    document_payload: Dict[str, Any],
    chunk_payloads: List[Dict[str, Any]],
) -> CaseJudgmentQCResult:
    checks: List[Dict[str, Any]] = []
    blocking_failed = False

    document_subtype = str(document_payload.get("document_subtype", "") or "").strip()
    proceeding_no = str(document_payload.get("proceeding_no", "") or "").strip()
    case_cluster_id = str(document_payload.get("case_cluster_id", "") or "").strip()

    if not document_subtype or document_subtype == "unknown":
        blocking_failed = True
        checks.append(
            _check(
                qc_stage="document_anchor",
                status="failed",
                severity="high",
                message="document_subtype is missing or unknown",
                details={"document_subtype": document_subtype},
            )
        )
    else:
        checks.append(
            _check(
                qc_stage="document_anchor",
                status="passed",
                severity="info",
                message="document_subtype is present",
                details={"document_subtype": document_subtype},
            )
        )

    if not proceeding_no:
        blocking_failed = True
        checks.append(
            _check(
                qc_stage="document_anchor",
                status="failed",
                severity="high",
                message="proceeding_no is missing",
            )
        )

    if not case_cluster_id:
        checks.append(
            _check(
                qc_stage="document_anchor",
                status="warning",
                severity="medium",
                message="case_cluster_id is missing",
            )
        )

    has_order_chunks = any(str(row.get("chunk_type", "")) == "order_item" for row in chunk_payloads)
    has_reasoning_chunks = any(
        str(row.get("section_kind_case", "")).strip()
        in {
            "ground_reasoning",
            "analysis",
            "appellate_test_or_legal_standard",
            "ground_statement",
            "ground_conclusion",
        }
        or "reason" in str(row.get("section_kind_case", "")).lower()
        for row in chunk_payloads
    )

    if document_subtype == "order_with_reasons" and not has_order_chunks:
        blocking_failed = True
        checks.append(
            _check(
                qc_stage="subtype_expectation",
                status="failed",
                severity="critical",
                message="order_with_reasons must include operative order chunks",
            )
        )

    if document_subtype in {"order_with_reasons", "judgment"} and not has_reasoning_chunks:
        blocking_failed = True
        checks.append(
            _check(
                qc_stage="subtype_expectation",
                status="failed",
                severity="high",
                message="reasoning chunks are required for judgment/order_with_reasons",
            )
        )

    missing_page_refs = [
        str(chunk.get("chunk_id", ""))
        for chunk in chunk_payloads
        if int(chunk.get("page_number_1", 0) or 0) <= 0
    ]
    if missing_page_refs:
        blocking_failed = True
        checks.append(
            _check(
                qc_stage="chunk_grounding",
                status="failed",
                severity="high",
                message="one or more chunks have missing page_number_1",
                details={"chunk_ids": missing_page_refs[:20]},
            )
        )
    else:
        checks.append(
            _check(
                qc_stage="chunk_grounding",
                status="passed",
                severity="info",
                message="all chunks have page_number_1",
                details={"chunk_count": len(chunk_payloads)},
            )
        )

    return CaseJudgmentQCResult(checks=checks, blocking_failed=blocking_failed)
