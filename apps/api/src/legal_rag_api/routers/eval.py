from __future__ import annotations

import uuid
from http import HTTPStatus

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import EvalCompareRequest, EvalRequest
from packages.scorers.contracts import evaluate_query_response_contract, strict_competition_contracts_enabled
from legal_rag_api.state import store
from services.eval.engine import (
    aggregate_run,
    build_value_report,
    build_gold_export_compatibility_assertions,
    collect_scoring_policy_catalog,
    eval_answer_score,
    eval_grounding,
    eval_ttft_factor,
    resolve_scoring_policy_spec,
)
from legal_rag_api.contracts import EvalRun

router = APIRouter(prefix="/v1/eval", tags=["Evaluation"])


def _scoring_policy_items() -> list[object]:
    if runtime_pg.enabled():
        return list(runtime_pg.list_scoring_policies())
    return list(store.scoring_policies.values())


def _run_question_context(run_id: str, question_ids: list[str]) -> dict[str, dict]:
    context: dict[str, dict] = {}
    for question_id in question_ids:
        if runtime_pg.enabled():
            artifact = runtime_pg.get_run_question_review(run_id, question_id)
            payload = artifact.model_dump(mode="json") if artifact else {}
        else:
            artifact = store.get_run_question_review(run_id, question_id)
            payload = artifact.model_dump(mode="json") if artifact else {}
        evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else {}
        viewer = payload.get("document_viewer", {}) if isinstance(payload.get("document_viewer"), dict) else {}
        documents = viewer.get("documents", []) if isinstance(viewer.get("documents"), list) else []
        doc_types = sorted(
            {
                str(document.get("doc_type", "")).strip()
                for document in documents
                if str(document.get("doc_type", "")).strip()
            }
        )
        question_payload = payload.get("question", {}) if isinstance(payload.get("question"), dict) else {}
        route_family = str((payload.get("response") or {}).get("route_name", "")).strip() if isinstance(payload.get("response"), dict) else ""
        question_text = str(question_payload.get("question", "")).lower()
        if route_family == "history_lineage":
            temporal_scope = "history-lineage"
        elif any(token in question_text for token in ("current", "valid", "updated", "in force")):
            temporal_scope = "current-law"
        else:
            temporal_scope = "general"
        context[question_id] = {
            "document_scope": "multi-doc" if len(documents) > 1 else "single-doc" if len(documents) == 1 else "unknown",
            "corpus_domain": doc_types[0] if len(doc_types) == 1 else "mixed" if len(doc_types) > 1 else "unknown",
            "temporal_scope": temporal_scope,
            "retrieval_profile_id": str(evidence.get("retrieval_profile_id", "")).strip(),
            "candidate_count": int(evidence.get("candidate_count", 0) or 0),
            "used_page_count": len(evidence.get("used_page_ids", []) if isinstance(evidence.get("used_page_ids"), list) else []),
        }
    return context


@router.post("/runs", status_code=202)
def create_eval_run(payload: EvalRequest) -> dict:
    run_id = payload.run_id
    eval_run_id = str(uuid.uuid4())
    if runtime_pg.enabled():
        if not runtime_pg.get_run(run_id):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        if not runtime_pg.get_gold_dataset(payload.gold_dataset_id):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        predictions = list(runtime_pg.list_run_questions(run_id).values())
        gold_questions = [g.model_dump(mode="json") for g in runtime_pg.list_gold_questions(payload.gold_dataset_id).values()]
    else:
        if run_id not in store.runs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
        if payload.gold_dataset_id not in store.gold_datasets:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
        predictions = list(store.run_questions.get(run_id, {}).values())
        gold_ds = store.gold_questions.get(payload.gold_dataset_id, {})
        gold_questions = [g.model_dump(mode="json") for g in gold_ds.values()]

    export_compatibility = build_gold_export_compatibility_assertions(gold_questions)
    if not export_compatibility["compatible"]:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail={
                "code": "gold_export_incompatible_for_eval",
                "compatibility": export_compatibility,
            },
        )

    scoring_policy_catalog = collect_scoring_policy_catalog(_scoring_policy_items())
    scoring_policy = resolve_scoring_policy_spec(
        payload.scoring_policy_version,
        catalog=scoring_policy_catalog,
    )
    resolved_scoring_policy_version = str(
        scoring_policy.get("resolved_policy_version", payload.scoring_policy_version)
    ).strip() or payload.scoring_policy_version

    metrics = aggregate_run(
        EvalRun(
            eval_run_id=eval_run_id,
            run_id=run_id,
            gold_dataset_id=payload.gold_dataset_id,
            scoring_policy_version=resolved_scoring_policy_version,
            judge_policy_version=payload.judge_policy_version,
            status="completed",
            metrics={},
        ),
        predictions=predictions,
        gold_questions=gold_questions,
        scoring_policy_catalog=scoring_policy_catalog,
        question_context_by_id=_run_question_context(run_id, [pred.question_id for pred in predictions]),
    )
    result = EvalRun(
        eval_run_id=eval_run_id,
        run_id=run_id,
        gold_dataset_id=payload.gold_dataset_id,
        scoring_policy_version=resolved_scoring_policy_version,
        judge_policy_version=payload.judge_policy_version,
        status="completed",
        metrics=metrics,
    )
    if runtime_pg.enabled():
        runtime_pg.create_eval_run(result)
    else:
        store.eval_runs[eval_run_id] = result
    return result.model_dump(mode="json")


@router.get("/runs/{evalRunId}")
def get_eval_run(evalRunId: str) -> dict:
    if runtime_pg.enabled():
        eval_run = runtime_pg.get_eval_run(evalRunId)
        if not eval_run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="eval run not found")
        return eval_run.model_dump(mode="json")
    if evalRunId not in store.eval_runs:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="eval run not found")
    return store.eval_runs[evalRunId].model_dump(mode="json")


@router.get("/runs/{evalRunId}/report")
def get_eval_report(evalRunId: str) -> dict:
    if runtime_pg.enabled():
        eval_run = runtime_pg.get_eval_run(evalRunId)
        if not eval_run:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="eval run not found")
        run_predictions = list(runtime_pg.list_run_questions(eval_run.run_id).values())
        golds = runtime_pg.list_gold_questions(eval_run.gold_dataset_id)
        by_id = {g.question_id: g.model_dump(mode="json") for g in golds.values()}
    else:
        if evalRunId not in store.eval_runs:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="eval run not found")
        eval_run = store.eval_runs[evalRunId]
        run_predictions = list(store.run_questions.get(eval_run.run_id, {}).values())
        golds = store.gold_questions.get(eval_run.gold_dataset_id, {})
        by_id = {g.question_id: g.model_dump(mode="json") for g in golds.values()}

    scoring_policy_catalog = collect_scoring_policy_catalog(_scoring_policy_items())
    scoring_policy = resolve_scoring_policy_spec(
        eval_run.scoring_policy_version,
        catalog=scoring_policy_catalog,
    )
    beta = float(scoring_policy.get("beta", 2.5))
    ttft_curve = scoring_policy.get("ttft_curve", {})
    strict_mode = strict_competition_contracts_enabled()
    existing_items = eval_run.metrics.get("question_metrics", []) if isinstance(eval_run.metrics, dict) else []
    if isinstance(existing_items, list) and existing_items:
        return {
            "eval_run": eval_run.model_dump(mode="json"),
            "items": existing_items,
            "value_report": eval_run.metrics.get("value_report", {}),
            "scorer_summary": eval_run.metrics.get("scorer_summary", {}),
        }
    items = []
    for pred in run_predictions:
        gold = by_id.get(pred.question_id, {})
        answer_score = eval_answer_score(pred, gold)
        grounding_score = eval_grounding(pred, gold, beta=beta)
        telemetry_factor = 1.0 if pred.telemetry.telemetry_complete else 0.0
        ttft_factor = eval_ttft_factor(pred.telemetry.ttft_ms, ttft_curve=ttft_curve)
        overall = answer_score * grounding_score * telemetry_factor * ttft_factor
        gold_page_ids = []
        for source_set in gold.get("source_sets", []):
            if source_set.get("is_primary"):
                gold_page_ids.extend([str(item) for item in source_set.get("page_ids", []) if str(item).strip()])
        pred_page_ids = [str(item) for item in [source.source_page_id for source in pred.sources if source.used] if item]
        source_precision = 1.0 if not pred_page_ids and not gold_page_ids else (
            len(set(pred_page_ids).intersection(set(gold_page_ids))) / len(set(pred_page_ids))
            if pred_page_ids else 0.0
        )
        source_recall = 1.0 if not pred_page_ids and not gold_page_ids else (
            len(set(pred_page_ids).intersection(set(gold_page_ids))) / len(set(gold_page_ids))
            if gold_page_ids else 0.0
        )
        error_tags = []
        if answer_score < 1.0:
            error_tags.append("answer_mismatch")
        if source_recall < 1.0:
            error_tags.append("missing_primary_source")
        if source_precision < 1.0 and pred_page_ids:
            error_tags.append("overcited_sources")
        if not pred.telemetry.telemetry_complete:
            error_tags.append("telemetry_incomplete")
        if ttft_factor < 1.0:
            error_tags.append("ttft_slow")
        if pred.abstained != (gold.get("canonical_answer") is None):
            error_tags.append("abstain_mismatch")
        contract_checks = evaluate_query_response_contract(
            answer=pred.answer,
            answer_type=pred.answer_type,
            abstained=pred.abstained,
            confidence=float(pred.confidence),
            sources=pred.sources,
            telemetry=pred.telemetry,
        )
        blocking_contract_failures = [
            str(item).strip()
            for item in contract_checks.get("blocking_failures", [])
            if str(item).strip()
        ]
        competition_contract_valid = bool(contract_checks.get("competition_contract_valid", not blocking_contract_failures))
        prediction_valid_for_competition = competition_contract_valid
        invalid_reason_tags = []
        for failure in blocking_contract_failures:
            if failure.startswith("answer_schema:"):
                invalid_reason_tags.append("invalid_answer_schema")
            elif failure.startswith("source_page_id:"):
                invalid_reason_tags.append("invalid_source_page_id")
            elif failure.startswith("telemetry:"):
                invalid_reason_tags.append("invalid_telemetry_contract")
            elif failure.startswith("no_answer:"):
                invalid_reason_tags.append("invalid_no_answer_form")
            else:
                invalid_reason_tags.append("invalid_contract")
        invalid_reason_tags = sorted(set(invalid_reason_tags))
        if strict_mode and not competition_contract_valid:
            prediction_valid_for_competition = False
            overall = 0.0
            error_tags.append("blocking_contract_failure")
        items.append(
            {
                "question_id": pred.question_id,
                "answer_type": pred.answer_type,
                "route_family": pred.route_name,
                "answer_score": answer_score,
                "grounding_score": grounding_score,
                "source_precision": source_precision,
                "source_recall": source_recall,
                "telemetry_factor": telemetry_factor,
                "ttft_factor": ttft_factor,
                "overall_score": overall,
                "answer_schema_valid": bool(contract_checks.get("answer_schema_valid", False)),
                "source_page_id_valid": bool(contract_checks.get("source_page_id_valid", False)),
                "telemetry_contract_valid": bool(contract_checks.get("telemetry_contract_valid", False)),
                "no_answer_form_valid": bool(contract_checks.get("no_answer_form_valid", False)),
                "blocking_contract_failures": blocking_contract_failures,
                "competition_contract_valid": competition_contract_valid,
                "prediction_valid_for_competition": prediction_valid_for_competition,
                "invalid_reason_tags": invalid_reason_tags,
                "contract_checks": contract_checks,
                "error_tags": error_tags,
            }
        )
    return {
        "eval_run": eval_run.model_dump(mode="json"),
        "items": items,
        "value_report": build_value_report(items),
        "scorer_summary": eval_run.metrics.get("scorer_summary", {}),
    }


@router.post("/compare")
def compare_runs(payload: EvalCompareRequest) -> dict:
    if runtime_pg.enabled():
        left = runtime_pg.get_eval_run(payload.left_eval_run_id)
        right = runtime_pg.get_eval_run(payload.right_eval_run_id)
    else:
        left = store.eval_runs.get(payload.left_eval_run_id)
        right = store.eval_runs.get(payload.right_eval_run_id)
    if left is None or right is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="one or both eval runs not found",
        )
    left_report = get_eval_report(payload.left_eval_run_id)
    right_report = get_eval_report(payload.right_eval_run_id)
    left_overall = left.metrics.get("overall_score", 0.0)
    right_overall = right.metrics.get("overall_score", 0.0)
    left_map = {q["question_id"]: q for q in left_report["items"]}
    right_map = {q["question_id"]: q for q in right_report["items"]}
    deltas = []
    for qid in set(left_map) | set(right_map):
        l = left_map.get(qid)
        r = right_map.get(qid)
        deltas.append(
            {
                "question_id": qid,
                "left_overall": (l or {}).get("overall_score", 0.0),
                "right_overall": (r or {}).get("overall_score", 0.0),
                "delta": float((r or {}).get("overall_score", 0.0) - (l or {}).get("overall_score", 0.0)),
                "error_tags": (r or {}).get("error_tags", []) or (l or {}).get("error_tags", []),
            }
        )
    deltas.sort(key=lambda row: float(row.get("delta", 0.0)))

    def _slice_rows(items: dict[str, dict], key: str) -> list[dict]:
        buckets: dict[str, dict[str, float]] = {}
        for row in items.values():
            label = str(row.get(key, "unknown") or "unknown")
            bucket = buckets.setdefault(
                label,
                {
                    "question_count": 0.0,
                    "answer_score_sum": 0.0,
                    "grounding_score_sum": 0.0,
                    "telemetry_factor_sum": 0.0,
                    "ttft_factor_sum": 0.0,
                    "overall_score_sum": 0.0,
                },
            )
            bucket["question_count"] += 1.0
            bucket["answer_score_sum"] += float(row.get("answer_score", 0.0))
            bucket["grounding_score_sum"] += float(row.get("grounding_score", 0.0))
            bucket["telemetry_factor_sum"] += float(row.get("telemetry_factor", 0.0))
            bucket["ttft_factor_sum"] += float(row.get("ttft_factor", 0.0))
            bucket["overall_score_sum"] += float(row.get("overall_score", 0.0))
        out = []
        for label in sorted(buckets.keys()):
            stats = buckets[label]
            count = int(stats["question_count"])
            if count <= 0:
                continue
            out.append(
                {
                    key: label,
                    "question_count": count,
                    "answer_score_mean": stats["answer_score_sum"] / count,
                    "grounding_score_mean": stats["grounding_score_sum"] / count,
                    "telemetry_factor_mean": stats["telemetry_factor_sum"] / count,
                    "ttft_factor_mean": stats["ttft_factor_sum"] / count,
                    "overall_score_mean": stats["overall_score_sum"] / count,
                }
            )
        return out

    def _compare_slice_rows(left_rows: list[dict], right_rows: list[dict], key: str) -> list[dict]:
        left_rows_map = {str(row.get(key)): row for row in left_rows}
        right_rows_map = {str(row.get(key)): row for row in right_rows}
        out = []
        for label in sorted(set(left_rows_map.keys()) | set(right_rows_map.keys())):
            left_row = left_rows_map.get(label, {})
            right_row = right_rows_map.get(label, {})
            out.append(
                {
                    key: label,
                    "left_question_count": int(float(left_row.get("question_count", 0.0))),
                    "right_question_count": int(float(right_row.get("question_count", 0.0))),
                    "question_count_delta": int(float(right_row.get("question_count", 0.0)) - float(left_row.get("question_count", 0.0))),
                    "left_overall_score_mean": float(left_row.get("overall_score_mean", 0.0)),
                    "right_overall_score_mean": float(right_row.get("overall_score_mean", 0.0)),
                    "overall_score_mean_delta": float(right_row.get("overall_score_mean", 0.0)) - float(left_row.get("overall_score_mean", 0.0)),
                    "answer_score_mean_delta": float(right_row.get("answer_score_mean", 0.0)) - float(left_row.get("answer_score_mean", 0.0)),
                    "grounding_score_mean_delta": float(right_row.get("grounding_score_mean", 0.0)) - float(left_row.get("grounding_score_mean", 0.0)),
                    "telemetry_factor_mean_delta": float(right_row.get("telemetry_factor_mean", 0.0)) - float(left_row.get("telemetry_factor_mean", 0.0)),
                    "ttft_factor_mean_delta": float(right_row.get("ttft_factor_mean", 0.0)) - float(left_row.get("ttft_factor_mean", 0.0)),
                }
            )
        return out

    def _compare_value_rows(left_rows: list[dict], right_rows: list[dict], key: str) -> list[dict]:
        left_rows_map = {str(row.get(key)): row for row in left_rows}
        right_rows_map = {str(row.get(key)): row for row in right_rows}
        out = []
        for label in sorted(set(left_rows_map.keys()) | set(right_rows_map.keys())):
            left_row = left_rows_map.get(label, {})
            right_row = right_rows_map.get(label, {})
            out.append(
                {
                    key: label,
                    "question_count": int(float(right_row.get("question_count", 0) or 0)),
                    "coverage_share": float(right_row.get("coverage_share", 0.0) or 0.0),
                    "baseline_overall": float(left_row.get("current_overall", 0.0) or 0.0),
                    "current_overall": float(right_row.get("current_overall", 0.0) or 0.0),
                    "overall_delta": float(right_row.get("current_overall", 0.0) or 0.0) - float(left_row.get("current_overall", 0.0) or 0.0),
                    "grounding_delta": float(right_row.get("current_grounding", 0.0) or 0.0) - float(left_row.get("current_grounding", 0.0) or 0.0),
                    "answer_delta": float(right_row.get("current_answer", 0.0) or 0.0) - float(left_row.get("current_answer", 0.0) or 0.0),
                    "ttft_delta": float(right_row.get("current_ttft_factor", 0.0) or 0.0) - float(left_row.get("current_ttft_factor", 0.0) or 0.0),
                    "top_error_tags": right_row.get("top_error_tags", []) or left_row.get("top_error_tags", []),
                    "verdict": right_row.get("verdict") or left_row.get("verdict") or "unknown",
                }
            )
        return out

    left_by_answer_type = _slice_rows(left_map, "answer_type")
    right_by_answer_type = _slice_rows(right_map, "answer_type")
    left_by_route_family = _slice_rows(left_map, "route_family")
    right_by_route_family = _slice_rows(right_map, "route_family")
    left_value = (left_report.get("value_report", {}) if isinstance(left_report, dict) else {}) or {}
    right_value = (right_report.get("value_report", {}) if isinstance(right_report, dict) else {}) or {}
    return {
        "left_eval_run_id": payload.left_eval_run_id,
        "right_eval_run_id": payload.right_eval_run_id,
        "metric_deltas": {
            "overall_score_delta": right_overall - left_overall,
            "answer_score_delta": float(right.metrics.get("answer_score_mean", 0.0) - left.metrics.get("answer_score_mean", 0.0)),
            "grounding_score_delta": float(right.metrics.get("grounding_score_mean", 0.0) - left.metrics.get("grounding_score_mean", 0.0)),
            "telemetry_delta": float(right.metrics.get("telemetry_factor", 0.0) - left.metrics.get("telemetry_factor", 0.0)),
            "ttft_factor_delta": float(right.metrics.get("ttft_factor", 0.0) - left.metrics.get("ttft_factor", 0.0)),
        },
        "compare_slices": {
            "slice_version": "compare_slices.v1",
            "by_answer_type": _compare_slice_rows(left_by_answer_type, right_by_answer_type, "answer_type"),
            "by_route_family": _compare_slice_rows(left_by_route_family, right_by_route_family, "route_family"),
        },
        "value_report": {
            "report_version": "value_report.v1",
            "by_answer_type": _compare_value_rows(left_value.get("by_answer_type", []), right_value.get("by_answer_type", []), "answer_type"),
            "by_route_family": _compare_value_rows(left_value.get("by_route_family", []), right_value.get("by_route_family", []), "route_family"),
            "by_answerability": _compare_value_rows(left_value.get("by_answerability", []), right_value.get("by_answerability", []), "answerability"),
            "by_document_scope": _compare_value_rows(left_value.get("by_document_scope", []), right_value.get("by_document_scope", []), "document_scope"),
            "by_corpus_domain": _compare_value_rows(left_value.get("by_corpus_domain", []), right_value.get("by_corpus_domain", []), "corpus_domain"),
            "by_temporal_scope": _compare_value_rows(left_value.get("by_temporal_scope", []), right_value.get("by_temporal_scope", []), "temporal_scope"),
        },
        "question_deltas": deltas,
    }


@router.post("/calibrate-judge")
def calibrate_judge(payload: dict) -> dict:
    job_id = str(uuid.uuid4())
    event_payload = {
        "event": "judge_calibration_requested",
        "at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "job_id": job_id,
    }
    if runtime_pg.enabled():
        runtime_pg.append_audit("judge_calibration_requested", job_id, event_payload)
    else:
        store.audit_log.append(event_payload)
    return {"job_id": job_id, "status": "accepted"}
