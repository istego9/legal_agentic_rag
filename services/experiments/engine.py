"""Experiment execution engine (proxy -> full) for API-first orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import EvalRun, ExperimentRunCreateRequest, QueryResponse, RuntimePolicy
from legal_rag_api.routers import qa as qa_router
from legal_rag_api.state import store
from services.eval.engine import (
    POLICY_REGISTRY_VERSION,
    POLICY_VERSION_FIELDS,
    aggregate_run,
    build_policy_registry,
    collect_scoring_policy_catalog,
    collect_scoring_policy_versions,
    eval_answer_score,
    eval_grounding,
    eval_ttft_factor,
    resolve_scoring_policy_spec,
    resolve_policy_versions,
    runtime_policy_with_resolved_scoring,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
COMPARE_SLICE_VERSION = "compare_slices.v1"
PROXY_GATE_RULE_VERSION = "proxy_gate.v1"
RUN_METADATA_VERSION = "run_metadata.v1"
RUN_METADATA_SCORE_FIELDS = (
    "overall_score",
    "answer_score_mean",
    "grounding_score_mean",
    "telemetry_factor",
    "ttft_factor",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _policy_registry_override() -> Dict[str, Any]:
    if runtime_pg.enabled():
        payload = runtime_pg.get_config_version(POLICY_REGISTRY_VERSION) or {}
        return payload if isinstance(payload, dict) else {}
    payload = store.config_versions.get(POLICY_REGISTRY_VERSION, {})
    return payload if isinstance(payload, dict) else {}


def _scoring_policy_items() -> List[Any]:
    if runtime_pg.enabled():
        return list(runtime_pg.list_scoring_policies())
    return list(store.scoring_policies.values())


def _policy_registry_snapshot(*, scoring_items: List[Any] | None = None) -> Dict[str, Any]:
    if scoring_items is None:
        scoring_items = _scoring_policy_items()
    return build_policy_registry(
        scoring_policy_versions=collect_scoring_policy_versions(scoring_items),
        override=_policy_registry_override(),
    )


def _default_runtime_policy(scoring_policy_version: str) -> RuntimePolicy:
    return RuntimePolicy(
        use_llm=False,
        max_candidate_pages=8,
        max_context_paragraphs=8,
        page_index_base_export=0,
        scoring_policy_version=scoring_policy_version,
        allow_dense_fallback=True,
        return_debug_trace=False,
    )


def _resolve_runtime_policy(profile: Dict[str, Any], scoring_policy_version: str) -> RuntimePolicy:
    payload = profile.get("runtime_policy")
    if isinstance(payload, dict):
        candidate = dict(payload)
        if not str(candidate.get("scoring_policy_version", "")).strip():
            candidate["scoring_policy_version"] = scoring_policy_version
        try:
            return RuntimePolicy(**candidate)
        except Exception:
            return _default_runtime_policy(scoring_policy_version)
    return _default_runtime_policy(scoring_policy_version)


def _dataset_questions(dataset_id: str) -> List[Dict[str, Any]]:
    if runtime_pg.enabled():
        listing = runtime_pg.list_dataset_questions(dataset_id, limit=100000)
        return list(listing.get("items", []))
    dataset = store.datasets.get(dataset_id, {})
    questions = dataset.get("questions", {}) if isinstance(dataset, dict) else {}
    if not isinstance(questions, dict):
        return []
    return [row for row in questions.values() if isinstance(row, dict)]


def _question_ids_from_items(items: Iterable[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for row in items:
        qid = str(row.get("id", "")).strip()
        if qid:
            out.append(qid)
    out.sort()
    return out


def _proxy_sample_size(total: int) -> int:
    if total <= 0:
        return 0
    raw = int(math.ceil(total * 0.25))
    target = max(50, min(300, raw))
    return min(total, target)


def _stratified_sample(question_items: List[Dict[str, Any]], target_size: int) -> List[str]:
    if target_size <= 0:
        return []
    buckets: Dict[str, List[str]] = {}
    for row in question_items:
        qid = str(row.get("id", "")).strip()
        if not qid:
            continue
        key = f"{row.get('answer_type', 'free_text')}::{row.get('route_hint', 'none')}"
        buckets.setdefault(key, []).append(qid)
    for bucket in buckets.values():
        bucket.sort()
    selected: List[str] = []
    cursor: Dict[str, int] = {key: 0 for key in buckets}
    keys = sorted(buckets.keys())
    while len(selected) < target_size and keys:
        made_progress = False
        for key in keys:
            idx = cursor[key]
            bucket = buckets[key]
            if idx >= len(bucket):
                continue
            selected.append(bucket[idx])
            cursor[key] = idx + 1
            made_progress = True
            if len(selected) >= target_size:
                break
        if not made_progress:
            break
    return selected


def _get_experiment_run(experiment_run_id: str) -> Optional[Dict[str, Any]]:
    if runtime_pg.enabled():
        return runtime_pg.get_experiment_run(experiment_run_id)
    return store.exp_runs.get(experiment_run_id)


def _get_experiment_score(experiment_run_id: str) -> Dict[str, Any]:
    if runtime_pg.enabled():
        return runtime_pg.get_exp_score(experiment_run_id) or {}
    return store.exp_scores.get(experiment_run_id, {})


def _list_completed_full_runs(experiment_id: str) -> List[Dict[str, Any]]:
    if runtime_pg.enabled():
        candidates = runtime_pg.list_experiment_runs(experiment_id, limit=100)
    else:
        candidates = list(store.exp_runs.values())
    filtered = [
        run
        for run in candidates
        if str(run.get("experiment_id")) == experiment_id
        and str(run.get("status")) == "completed"
        and str(run.get("stage_type")) == "full"
    ]
    filtered.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    return filtered


def _baseline_score(
    experiment: Dict[str, Any],
    requested_baseline_run_id: Optional[str],
    *,
    allow_latest_fallback: bool = True,
) -> Tuple[Optional[str], Dict[str, Any]]:
    baseline_run_id = requested_baseline_run_id or experiment.get("baseline_experiment_run_id")
    if baseline_run_id:
        resolved_baseline_id = str(baseline_run_id)
        baseline_run = _get_experiment_run(resolved_baseline_id)
        if not baseline_run:
            raise ValueError(f"baseline experiment run not found: {resolved_baseline_id}")
        if str(baseline_run.get("experiment_id")) != str(experiment.get("experiment_id")):
            raise ValueError("baseline experiment run must belong to the same experiment")
        if str(baseline_run.get("stage_type")) != "full":
            raise ValueError("baseline experiment run must be full stage")
        if str(baseline_run.get("status")) != "completed":
            raise ValueError("baseline experiment run must be completed")
        baseline_score = _get_experiment_score(resolved_baseline_id)
        if not baseline_score:
            raise ValueError(f"baseline score not found: {resolved_baseline_id}")
        return resolved_baseline_id, baseline_score
    if not allow_latest_fallback:
        return None, {}
    for run in _list_completed_full_runs(str(experiment["experiment_id"])):
        found_id = str(run.get("experiment_run_id", "")).strip()
        if not found_id:
            continue
        baseline_score = _get_experiment_score(found_id)
        if baseline_score:
            return found_id, baseline_score
    return None, {}


def _cache_key(
    profile: Dict[str, Any],
    experiment: Dict[str, Any],
    stage_type: str,
    question_ids: List[str],
    baseline_run_id: Optional[str],
    policy_versions: Dict[str, str],
) -> str:
    source = {
        "profile_id": profile.get("profile_id"),
        "dataset_id": profile.get("dataset_id"),
        "gold_dataset_id": profile.get("gold_dataset_id"),
        "endpoint_target": profile.get("endpoint_target", "local"),
        "runtime_policy": profile.get("runtime_policy"),
        "processing_profile": profile.get("processing_profile", {}),
        "retrieval_profile": profile.get("retrieval_profile", {}),
        "experiment_id": experiment.get("experiment_id"),
        "stage_type": stage_type,
        "question_ids": sorted(question_ids),
        "baseline_experiment_run_id": baseline_run_id,
        "policy_versions": policy_versions,
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _gate_eval(proxy_metrics: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    baseline_overall = float(baseline.get("overall_score", 0.0))
    baseline_answer = float(baseline.get("answer_score_mean", 0.0))
    baseline_grounding = float(baseline.get("grounding_score_mean", 0.0))
    overall = float(proxy_metrics.get("overall_score", 0.0))
    answer_score = float(proxy_metrics.get("answer_score_mean", 0.0))
    grounding = float(proxy_metrics.get("grounding_score_mean", 0.0))
    telemetry_factor = float(proxy_metrics.get("telemetry_factor", 0.0))
    ttft_factor = float(proxy_metrics.get("ttft_factor", 0.0))
    thresholds = {
        "overall_proxy": baseline_overall - 0.01,
        "answer_score_mean": baseline_answer - 0.01,
        "grounding_proxy": baseline_grounding - 0.01,
        "telemetry_factor": 1.0,
        "ttft_factor": 0.95,
    }
    actual = {
        "overall_proxy": overall,
        "answer_score_mean": answer_score,
        "grounding_proxy": grounding,
        "telemetry_factor": telemetry_factor,
        "ttft_factor": ttft_factor,
    }
    checks = {
        key: actual[key] >= threshold for key, threshold in thresholds.items()
    }
    failed_rules = [
        {
            "rule": key,
            "threshold": thresholds[key],
            "actual": actual[key],
        }
        for key, passed in checks.items()
        if not passed
    ]
    return {
        "passed": not failed_rules,
        "rule_version": PROXY_GATE_RULE_VERSION,
        "checks": checks,
        "thresholds": thresholds,
        "failed_rules": failed_rules,
        "baseline_overall": baseline_overall,
        "baseline_answer": baseline_answer,
        "baseline_grounding": baseline_grounding,
        "actual": actual,
        "telemetry_completeness_gate": {
            "required": True,
            "passed": telemetry_factor >= thresholds["telemetry_factor"],
        },
    }


async def _execute_questions(
    profile: Dict[str, Any],
    question_ids: List[str],
    runtime_policy: RuntimePolicy,
) -> Tuple[str, List[QueryResponse]]:
    if runtime_pg.enabled():
        qa_run = runtime_pg.create_run(str(profile["dataset_id"]), len(question_ids), status="running")
    else:
        qa_run = store.create_run(str(profile["dataset_id"]), len(question_ids), status="running")
    qa_run_id = str(qa_run["run_id"])
    predictions: List[QueryResponse] = []
    for question_id in question_ids:
        request_payload = qa_router._build_question_from_dataset(
            project_id=str(profile["project_id"]),
            dataset_id=str(profile["dataset_id"]),
            question_id=question_id,
            runtime_policy=runtime_policy,
        )
        result, answer_ctx = await qa_router._answer_query(request_payload)
        predictions.append(result)
        if runtime_pg.enabled():
            runtime_pg.upsert_run_question(qa_run_id, question_id, result)
            runtime_pg.upsert_run_question_review(
                qa_run_id,
                question_id,
                qa_router._build_review_artifact(
                    run_id=qa_run_id,
                    query_request=request_payload,
                    response=result,
                    candidates=answer_ctx["candidates"],
                    page_refs=answer_ctx["page_refs"],
                    retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                    solver_trace=answer_ctx["solver_trace"],
                    evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                    route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                    latency_budget_assertion=answer_ctx["latency_budget_assertion"],
                ),
            )
            runtime_pg.upsert_question_telemetry(question_id, result.telemetry.model_dump(mode="json"))
        else:
            store.upsert_run_question(qa_run_id, question_id, result)
            store.upsert_run_question_review(
                qa_run_id,
                question_id,
                qa_router._build_review_artifact(
                    run_id=qa_run_id,
                    query_request=request_payload,
                    response=result,
                    candidates=answer_ctx["candidates"],
                    page_refs=answer_ctx["page_refs"],
                    retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                    solver_trace=answer_ctx["solver_trace"],
                    evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                    route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                    latency_budget_assertion=answer_ctx["latency_budget_assertion"],
                ).model_dump(mode="json"),
            )
            store.question_telemetry[question_id] = result.telemetry.model_dump(mode="json")
    if runtime_pg.enabled():
        runtime_pg.set_run_status(qa_run_id, "completed")
    else:
        store.set_run_status(qa_run_id, "completed")
    return qa_run_id, predictions


def _gold_questions(gold_dataset_id: str) -> List[Dict[str, Any]]:
    if runtime_pg.enabled():
        return [row.model_dump(mode="json") for row in runtime_pg.list_gold_questions(gold_dataset_id).values()]
    return [row.model_dump(mode="json") for row in store.gold_questions.get(gold_dataset_id, {}).values()]


def _save_eval_run(
    qa_run_id: str,
    gold_dataset_id: str,
    metrics: Dict[str, Any],
    *,
    scoring_policy_version: str,
) -> str:
    eval_run = EvalRun(
        eval_run_id=str(uuid4()),
        run_id=qa_run_id,
        gold_dataset_id=gold_dataset_id,
        scoring_policy_version=scoring_policy_version,
        judge_policy_version="judge_v1",
        status="completed",
        metrics=metrics,
    )
    if runtime_pg.enabled():
        runtime_pg.create_eval_run(eval_run)
    else:
        store.create_eval_run(eval_run)
    return eval_run.eval_run_id


def _save_question_metrics(
    experiment_run_id: str,
    predictions: List[QueryResponse],
    gold_by_question_id: Dict[str, Dict[str, Any]],
    baseline_question_map: Dict[str, Dict[str, Any]],
    *,
    scoring_policy: Dict[str, Any],
    question_context_by_id: Dict[str, Dict[str, Any]] | None = None,
) -> None:
    beta = float(scoring_policy.get("beta", 2.5))
    ttft_curve = scoring_policy.get("ttft_curve", {})
    question_context_by_id = question_context_by_id or {}
    for pred in predictions:
        gold = gold_by_question_id.get(pred.question_id, {})
        question_context = question_context_by_id.get(pred.question_id, {})
        answer_score = eval_answer_score(pred, gold)
        grounding_score = eval_grounding(pred, gold, beta=beta)
        telemetry_factor = 1.0 if pred.telemetry.telemetry_complete else 0.0
        ttft_factor = eval_ttft_factor(pred.telemetry.ttft_ms, ttft_curve=ttft_curve)
        overall_score = answer_score * grounding_score * telemetry_factor * ttft_factor
        baseline_metric = baseline_question_map.get(pred.question_id, {})
        baseline_overall = baseline_metric.get("overall_score")
        route_family = str(pred.route_name or gold.get("route_hint") or "unknown").strip() or "unknown"
        answer_type = str(pred.answer_type or gold.get("answer_type") or "unknown").strip() or "unknown"
        answerability = "unanswerable" if gold.get("canonical_answer") is None else "answerable"
        metric = {
            "question_id": pred.question_id,
            "answer_score": answer_score,
            "grounding_score": grounding_score,
            "telemetry_factor": telemetry_factor,
            "ttft_factor": ttft_factor,
            "overall_score": overall_score,
            "route_name": pred.route_name,
            "route_family": route_family,
            "answer_type": answer_type,
            "answerability": answerability,
            "document_scope": str(question_context.get("document_scope", "unknown")).strip() or "unknown",
            "corpus_domain": str(question_context.get("corpus_domain", "unknown")).strip() or "unknown",
            "temporal_scope": str(question_context.get("temporal_scope", "unknown")).strip() or "unknown",
            "segment": f"{pred.answer_type}:{pred.route_name}",
            "delta_vs_baseline": (
                float(overall_score - float(baseline_overall))
                if baseline_overall is not None
                else None
            ),
            "error_tags": [],
        }
        if runtime_pg.enabled():
            runtime_pg.upsert_exp_question_metric(experiment_run_id, pred.question_id, metric)
        else:
            store.upsert_exp_question_metric(experiment_run_id, pred.question_id, metric)


def _load_baseline_question_map(baseline_run_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
    if not baseline_run_id:
        return {}
    if runtime_pg.enabled():
        return {
            str(row.get("question_id")): row
            for row in runtime_pg.list_exp_question_metrics(str(baseline_run_id))
        }
    return {
        str(row.get("question_id")): row
        for row in store.list_exp_question_metrics(str(baseline_run_id))
    }


def _run_question_context(run_id: str, question_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    context: Dict[str, Dict[str, Any]] = {}
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
        response_payload = payload.get("response", {}) if isinstance(payload.get("response"), dict) else {}
        route_family = str(response_payload.get("route_name", "")).strip()
        question_text = str(question_payload.get("question", "")).lower()
        if route_family == "history_lineage":
            temporal_scope = "history-lineage"
        elif any(token in question_text for token in ("current", "valid", "updated", "in force")):
            temporal_scope = "current-law"
        else:
            temporal_scope = "general"
        used_page_ids = evidence.get("used_page_ids", []) if isinstance(evidence.get("used_page_ids"), list) else []
        context[question_id] = {
            "document_scope": "multi-doc" if len(documents) > 1 else "single-doc" if len(documents) == 1 else "unknown",
            "corpus_domain": doc_types[0] if len(doc_types) == 1 else "mixed" if len(doc_types) > 1 else "unknown",
            "temporal_scope": temporal_scope,
            "retrieval_profile_id": str(evidence.get("retrieval_profile_id", "")).strip(),
            "candidate_count": int(evidence.get("candidate_count", 0) or 0),
            "used_page_count": len(used_page_ids),
        }
    return context


def _save_stage_artifact(experiment_run_id: str, payload: Dict[str, Any]) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"experiment_run_{experiment_run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_uri()


def _save_compare_artifact(left_run_id: str, right_run_id: str, payload: Dict[str, Any]) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"experiment_compare_{left_run_id}_{right_run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_uri()


def _request_metadata(request: ExperimentRunCreateRequest) -> Dict[str, Any]:
    return {
        "stage_mode": str(request.stage_mode),
        "baseline_experiment_run_id": str(request.baseline_experiment_run_id or ""),
        "proxy_sample_size": int(request.proxy_sample_size) if request.proxy_sample_size is not None else None,
        "actor": str(request.actor),
        "agent_mode": bool(request.agent_mode),
    }


def _build_run_metadata(
    *,
    profile_id: str,
    stage_type: str,
    baseline_experiment_run_id: str,
    sample_size: int,
    question_count: int,
    qa_run_id: str,
    eval_run_id: str,
    run_report_artifact_url: str,
    compare_artifact_url: str,
    compare_required: bool,
    policy_versions: Dict[str, str],
    metrics: Dict[str, Any],
    request_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    metrics_summary = {
        field: float(metrics.get(field, 0.0)) for field in RUN_METADATA_SCORE_FIELDS
    }
    return {
        "metadata_version": RUN_METADATA_VERSION,
        "profile_id": profile_id,
        "stage_type": stage_type,
        "baseline_experiment_run_id": baseline_experiment_run_id,
        "sample_size": sample_size,
        "question_count": question_count,
        "qa_run_id": qa_run_id,
        "eval_run_id": eval_run_id,
        "run_report_artifact_url": run_report_artifact_url,
        "compare_artifact_url": compare_artifact_url,
        "compare_required": compare_required,
        "policy_versions": dict(policy_versions),
        "metrics_summary": metrics_summary,
        "request": dict(request_metadata),
    }


def _run_metadata_errors(run_metadata: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required_text_fields = (
        "profile_id",
        "stage_type",
        "baseline_experiment_run_id",
        "qa_run_id",
        "eval_run_id",
        "run_report_artifact_url",
    )
    for field in required_text_fields:
        if not str(run_metadata.get(field, "")).strip():
            errors.append(field)
    for field in ("sample_size", "question_count"):
        value = run_metadata.get(field)
        if not isinstance(value, int) or value <= 0:
            errors.append(field)
    if not isinstance(run_metadata.get("compare_required"), bool):
        errors.append("compare_required")
    if bool(run_metadata.get("compare_required")) and not str(run_metadata.get("compare_artifact_url", "")).strip():
        errors.append("compare_artifact_url")
    if (
        isinstance(run_metadata.get("sample_size"), int)
        and isinstance(run_metadata.get("question_count"), int)
        and run_metadata["sample_size"] != run_metadata["question_count"]
    ):
        errors.append("sample_size_question_count_mismatch")
    policy_versions = run_metadata.get("policy_versions")
    if not isinstance(policy_versions, dict):
        errors.append("policy_versions")
    elif not str(policy_versions.get("scoring_policy_version", "")).strip():
        errors.append("policy_versions.scoring_policy_version")
    metrics_summary = run_metadata.get("metrics_summary")
    if not isinstance(metrics_summary, dict):
        errors.append("metrics_summary")
    else:
        for field in RUN_METADATA_SCORE_FIELDS:
            value = metrics_summary.get(field)
            if not isinstance(value, (int, float)):
                errors.append(f"metrics_summary.{field}")
    request_metadata = run_metadata.get("request")
    if not isinstance(request_metadata, dict):
        errors.append("request")
    else:
        for field in ("stage_mode", "actor"):
            if not str(request_metadata.get(field, "")).strip():
                errors.append(f"request.{field}")
        if not isinstance(request_metadata.get("agent_mode"), bool):
            errors.append("request.agent_mode")
        proxy_sample_size = request_metadata.get("proxy_sample_size")
        if proxy_sample_size is not None and (not isinstance(proxy_sample_size, int) or proxy_sample_size <= 0):
            errors.append("request.proxy_sample_size")
        baseline_request_id = request_metadata.get("baseline_experiment_run_id")
        if baseline_request_id is not None and not isinstance(baseline_request_id, str):
            errors.append("request.baseline_experiment_run_id")
    return errors


def _assert_required_run_metadata(run_metadata: Dict[str, Any]) -> None:
    errors = _run_metadata_errors(run_metadata)
    if errors:
        raise ValueError(
            "required run metadata validation failed: "
            + ", ".join(sorted(set(errors)))
        )


def _assert_idempotent_request_metadata(run: Dict[str, Any], request: ExperimentRunCreateRequest) -> None:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    run_metadata = metrics.get("run_metadata") if isinstance(metrics, dict) else None
    if not isinstance(run_metadata, dict):
        raise ValueError("idempotent run is missing required metadata")
    _assert_required_run_metadata(run_metadata)
    existing_request = run_metadata.get("request")
    if not isinstance(existing_request, dict):
        raise ValueError("idempotent run request metadata is missing")
    current_request = _request_metadata(request)
    mismatches: List[str] = []
    for field in (
        "stage_mode",
        "baseline_experiment_run_id",
        "proxy_sample_size",
        "actor",
        "agent_mode",
    ):
        if existing_request.get(field) != current_request.get(field):
            mismatches.append(field)
    if mismatches:
        raise ValueError(
            "idempotency key metadata mismatch: " + ", ".join(sorted(mismatches))
        )


async def execute_stage(
    experiment: Dict[str, Any],
    profile: Dict[str, Any],
    request: ExperimentRunCreateRequest,
    stage_type: str,
) -> Dict[str, Any]:
    scoring_items = _scoring_policy_items()
    policy_registry = _policy_registry_snapshot(scoring_items=scoring_items)
    active_scoring_policy = str(
        ((policy_registry.get("policies") or {}).get("scoring") or {}).get("active_version", "")
    ).strip()
    runtime_policy = _resolve_runtime_policy(profile, active_scoring_policy or "contest_v2026_public_rules_v1")
    resolved_policy_versions = resolve_policy_versions(
        registry=policy_registry,
        runtime_policy=runtime_policy,
        profile=profile,
    )
    runtime_policy = runtime_policy_with_resolved_scoring(runtime_policy, resolved_policy_versions)
    policy_versions_payload = {
        field: str(resolved_policy_versions.get(field, "")).strip()
        for field in POLICY_VERSION_FIELDS.values()
    }
    scoring_policy_catalog = collect_scoring_policy_catalog(scoring_items)
    scoring_policy = resolve_scoring_policy_spec(
        policy_versions_payload.get("scoring_policy_version", ""),
        catalog=scoring_policy_catalog,
    )
    resolved_scoring_policy_version = str(scoring_policy.get("resolved_policy_version", "")).strip()
    if resolved_scoring_policy_version:
        policy_versions_payload["scoring_policy_version"] = resolved_scoring_policy_version
    runtime_policy = runtime_policy_with_resolved_scoring(runtime_policy, policy_versions_payload)

    all_questions = _dataset_questions(str(profile["dataset_id"]))
    if not all_questions:
        raise ValueError("dataset has no questions")
    all_question_ids = _question_ids_from_items(all_questions)
    allow_latest_baseline_fallback = not (
        stage_type == "proxy" and request.stage_mode == "proxy"
    )
    baseline_run_id, baseline_score = _baseline_score(
        experiment,
        request.baseline_experiment_run_id,
        allow_latest_fallback=allow_latest_baseline_fallback,
    )
    if stage_type == "proxy" and not baseline_run_id:
        raise ValueError(
            "baseline compare is required for proxy runs: provide baseline_experiment_run_id or set experiment baseline_experiment_run_id"
        )
    if stage_type == "proxy" and not baseline_score:
        raise ValueError("baseline compare score is required for proxy runs")
    baseline_question_map = _load_baseline_question_map(baseline_run_id)

    if stage_type == "proxy":
        target_size = request.proxy_sample_size or _proxy_sample_size(len(all_question_ids))
        selected_ids = _stratified_sample(all_questions, target_size)
    else:
        selected_ids = all_question_ids

    if not selected_ids:
        raise ValueError("no questions selected for experiment stage")

    cache_key = _cache_key(
        profile,
        experiment,
        stage_type,
        selected_ids,
        baseline_run_id,
        policy_versions_payload,
    )
    if runtime_pg.enabled():
        cached = runtime_pg.get_exp_stage_cache(stage_type, cache_key)
    else:
        cached = store.get_exp_stage_cache(stage_type, cache_key)
    if cached:
        cached_run_id = str(cached.get("experiment_run_id", ""))
        if cached_run_id:
            run = _get_experiment_run(cached_run_id)
            cached_status = str(run.get("status")) if run else ""
            cacheable_statuses = {"completed"}
            if stage_type == "proxy":
                cacheable_statuses.add("gated_rejected")
            if run and cached_status in cacheable_statuses:
                run_metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
                run_metadata = run_metrics.get("run_metadata") if isinstance(run_metrics, dict) else None
                if isinstance(run_metadata, dict):
                    _assert_required_run_metadata(run_metadata)
                    return run

    run_payload = {
        "experiment_id": experiment["experiment_id"],
        "profile_id": profile["profile_id"],
        "gold_dataset_id": experiment["gold_dataset_id"],
        "stage_type": stage_type,
        "status": "running",
        "gate_passed": None,
        "idempotency_key": request.idempotency_key,
        "sample_size": len(selected_ids),
        "question_count": len(selected_ids),
        "baseline_experiment_run_id": baseline_run_id,
        "metrics": {},
        "started_at": _utcnow(),
    }
    if runtime_pg.enabled():
        run = runtime_pg.create_experiment_run(run_payload)
    else:
        run = store.create_experiment_run(run_payload)
    experiment_run_id = str(run["experiment_run_id"])
    effective_baseline_run_id = baseline_run_id or (
        experiment_run_id if stage_type == "full" else None
    )

    qa_run_id, predictions = await _execute_questions(profile, selected_ids, runtime_policy)
    gold_questions = _gold_questions(str(experiment["gold_dataset_id"]))
    gold_by_question_id = {row.get("question_id"): row for row in gold_questions}
    question_context_by_id = _run_question_context(qa_run_id, selected_ids)

    metrics = aggregate_run(
        EvalRun(
            eval_run_id=str(uuid4()),
            run_id=qa_run_id,
            gold_dataset_id=str(experiment["gold_dataset_id"]),
            scoring_policy_version=policy_versions_payload["scoring_policy_version"],
            judge_policy_version="judge_v1",
            status="completed",
            metrics={"policy_versions": policy_versions_payload},
        ),
        predictions=predictions,
        gold_questions=gold_questions,
        scoring_policy_catalog=scoring_policy_catalog,
        question_context_by_id=question_context_by_id,
    )
    metrics["S"] = metrics.get("answer_score_mean", 0.0)
    metrics["G"] = metrics.get("grounding_score_mean", 0.0)
    metrics["T"] = metrics.get("telemetry_factor", 0.0)
    metrics["F"] = metrics.get("ttft_factor", 0.0)
    gate_required = bool(baseline_score)
    gate = (
        _gate_eval(metrics, baseline_score)
        if gate_required
        else {
            "passed": True,
            "checks": {},
            "thresholds": {},
            "failed_rules": [],
            "telemetry_completeness_gate": {"required": False, "passed": True},
            "baseline_seed": True,
        }
    )
    metrics["gate"] = gate
    metrics["baseline"] = baseline_score
    metrics["baseline_experiment_run_id"] = effective_baseline_run_id
    metrics["cache_key"] = cache_key
    metrics["policy_versions"] = policy_versions_payload
    metrics["policy_resolution"] = resolved_policy_versions.get("resolution", {})
    metrics["policy_registry_version"] = policy_registry.get("registry_version")

    _save_question_metrics(
        experiment_run_id,
        predictions,
        gold_by_question_id,
        baseline_question_map,
        scoring_policy=scoring_policy,
        question_context_by_id=question_context_by_id,
    )
    eval_run_id = _save_eval_run(
        qa_run_id,
        str(experiment["gold_dataset_id"]),
        metrics,
        scoring_policy_version=policy_versions_payload["scoring_policy_version"],
    )

    if runtime_pg.enabled():
        runtime_pg.upsert_exp_score(experiment_run_id, str(experiment["experiment_id"]), stage_type, metrics, payload=metrics)
    else:
        store.upsert_exp_score(experiment_run_id, str(experiment["experiment_id"]), stage_type, metrics)

    artifact_payload = {
        "experiment_run_id": experiment_run_id,
        "qa_run_id": qa_run_id,
        "eval_run_id": eval_run_id,
        "metrics": metrics,
        "question_ids": selected_ids,
    }
    artifact_url = _save_stage_artifact(experiment_run_id, artifact_payload)
    compare_required = gate_required
    compare_payload: Dict[str, Any] = {}
    compare_artifact_url = ""
    if compare_required and effective_baseline_run_id:
        compare_payload = compare_experiment_runs(str(effective_baseline_run_id), experiment_run_id)
        compare_artifact_url = _save_compare_artifact(str(effective_baseline_run_id), experiment_run_id, compare_payload)
    run_metadata = _build_run_metadata(
        profile_id=str(profile["profile_id"]),
        stage_type=stage_type,
        baseline_experiment_run_id=str(effective_baseline_run_id or ""),
        sample_size=len(selected_ids),
        question_count=len(selected_ids),
        qa_run_id=qa_run_id,
        eval_run_id=eval_run_id,
        run_report_artifact_url=artifact_url,
        compare_artifact_url=compare_artifact_url,
        compare_required=compare_required,
        policy_versions=policy_versions_payload,
        metrics=metrics,
        request_metadata=_request_metadata(request),
    )
    _assert_required_run_metadata(run_metadata)
    metrics["run_metadata"] = run_metadata
    if compare_payload:
        metrics["compare_summary"] = {
            "compare_artifact_url": compare_artifact_url,
            "metric_deltas": compare_payload.get("metric_deltas", {}),
            "value_report_version": ((compare_payload.get("value_report") or {}).get("report_version")),
        }
    metrics["promotion_decision"] = {
        "status": "accepted" if gate.get("passed", False) else "rejected",
        "reason": (
            "baseline_seed_no_compare"
            if not gate_required
            else "compare_gate_passed"
            if gate.get("passed", False)
            else ",".join(str(item.get("rule", "")) for item in gate.get("failed_rules", []))
        ),
        "compare_required": compare_required,
        "compare_artifact_url": compare_artifact_url,
    }
    final_status = (
        "gated_rejected"
        if gate_required and not gate.get("passed", False)
        else "completed"
    )
    if runtime_pg.enabled():
        runtime_pg.upsert_exp_score(experiment_run_id, str(experiment["experiment_id"]), stage_type, metrics, payload=metrics)
        runtime_pg.upsert_exp_artifact(
            experiment_run_id,
            "run_report",
            artifact_url,
            {"stage_type": stage_type, "question_count": len(selected_ids)},
        )
        if compare_artifact_url:
            runtime_pg.upsert_exp_artifact(
                experiment_run_id,
                "compare_report",
                compare_artifact_url,
                {
                    "stage_type": stage_type,
                    "baseline_experiment_run_id": str(effective_baseline_run_id),
                },
            )
        runtime_pg.upsert_exp_stage_cache(
            stage_type,
            cache_key,
            experiment_run_id,
            {"question_count": len(selected_ids), "overall_score": metrics.get("overall_score", 0.0)},
        )
        completed = runtime_pg.update_experiment_run(
            experiment_run_id,
            {
                "status": final_status,
                "gate_passed": gate.get("passed"),
                "qa_run_id": qa_run_id,
                "eval_run_id": eval_run_id,
                "baseline_experiment_run_id": effective_baseline_run_id,
                "metrics": metrics,
                "completed_at": _utcnow(),
            },
        )
        return completed or run
    store.upsert_exp_score(experiment_run_id, str(experiment["experiment_id"]), stage_type, metrics)
    store.upsert_exp_artifact(
        experiment_run_id,
        "run_report",
        artifact_url,
        {"stage_type": stage_type, "question_count": len(selected_ids)},
    )
    if compare_artifact_url:
        store.upsert_exp_artifact(
            experiment_run_id,
            "compare_report",
            compare_artifact_url,
            {
                "stage_type": stage_type,
                "baseline_experiment_run_id": str(effective_baseline_run_id),
            },
        )
    store.upsert_exp_stage_cache(
        stage_type,
        cache_key,
        experiment_run_id,
        {"question_count": len(selected_ids), "overall_score": metrics.get("overall_score", 0.0)},
    )
    updated = store.update_experiment_run(
        experiment_run_id,
        {
            "status": final_status,
            "gate_passed": gate.get("passed"),
            "qa_run_id": qa_run_id,
            "eval_run_id": eval_run_id,
            "baseline_experiment_run_id": effective_baseline_run_id,
            "metrics": metrics,
            "completed_at": _utcnow().isoformat(),
        },
    )
    return updated or run


async def execute_experiment(
    experiment: Dict[str, Any],
    profile: Dict[str, Any],
    request: ExperimentRunCreateRequest,
) -> Dict[str, Any]:
    if request.idempotency_key:
        if runtime_pg.enabled():
            idempotent = runtime_pg.find_experiment_run_by_idempotency(
                str(experiment["experiment_id"]), request.idempotency_key
            )
        else:
            idempotent = store.find_experiment_run_by_idempotency(
                str(experiment["experiment_id"]), request.idempotency_key
            )
        if idempotent:
            _assert_idempotent_request_metadata(idempotent, request)
            return idempotent

    if request.stage_mode == "auto":
        proxy_run = await execute_stage(experiment, profile, request, stage_type="proxy")
        gate = ((proxy_run.get("metrics") or {}).get("gate") or {})
        if not gate.get("passed", False):
            return proxy_run
        full_request = request.model_copy(update={"stage_mode": "full", "idempotency_key": None})
        return await execute_stage(experiment, profile, full_request, stage_type="full")
    stage_type = "full" if request.stage_mode == "full" else "proxy"
    return await execute_stage(experiment, profile, request, stage_type=stage_type)


def experiment_analysis(experiment_run_id: str) -> Dict[str, Any]:
    if runtime_pg.enabled():
        run = runtime_pg.get_experiment_run(experiment_run_id)
        score = runtime_pg.get_exp_score(experiment_run_id) or {}
        items = runtime_pg.list_exp_question_metrics(experiment_run_id)
        artifacts = runtime_pg.list_exp_artifacts(experiment_run_id)
    else:
        run = store.exp_runs.get(experiment_run_id)
        score = store.exp_scores.get(experiment_run_id, {})
        items = store.list_exp_question_metrics(experiment_run_id)
        artifacts = store.list_exp_artifacts(experiment_run_id)
    if not run:
        raise ValueError("experiment run not found")

    baseline_run_id = str(run.get("baseline_experiment_run_id") or "")
    baseline_score: Dict[str, Any] = {}
    if baseline_run_id:
        if runtime_pg.enabled():
            baseline_score = runtime_pg.get_exp_score(baseline_run_id) or {}
        else:
            baseline_score = store.exp_scores.get(baseline_run_id, {})
    deltas = {
        "overall_score_delta": float(score.get("overall_score", 0.0) - float(baseline_score.get("overall_score", 0.0)))
        if baseline_score
        else None,
        "answer_score_delta": float(score.get("answer_score_mean", 0.0) - float(baseline_score.get("answer_score_mean", 0.0)))
        if baseline_score
        else None,
        "grounding_score_delta": float(score.get("grounding_score_mean", 0.0) - float(baseline_score.get("grounding_score_mean", 0.0)))
        if baseline_score
        else None,
    }
    return {
        "experiment_run": run,
        "score": score,
        "gate": (run.get("metrics") or {}).get("gate", {}),
        "items": items,
        "deltas": deltas,
        "artifacts": artifacts,
    }


def compare_experiment_runs(left_run_id: str, right_run_id: str) -> Dict[str, Any]:
    def _as_label(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _segment_parts(row: Dict[str, Any]) -> Tuple[str, str]:
        segment = _as_label(row.get("segment"))
        if ":" not in segment:
            return "", ""
        answer_type, route_family = segment.split(":", 1)
        return answer_type, route_family

    def _answer_type(row: Dict[str, Any]) -> str:
        direct = _as_label(row.get("answer_type"))
        if direct:
            return direct
        from_segment, _ = _segment_parts(row)
        if from_segment:
            return from_segment
        return "unknown"

    def _route_family(row: Dict[str, Any]) -> str:
        direct = _as_label(row.get("route_family")) or _as_label(row.get("route_name"))
        if direct:
            return direct
        _, from_segment = _segment_parts(row)
        if from_segment:
            return from_segment
        return "unknown"

    def _slice_rows(items: List[Dict[str, Any]], *, key: str) -> List[Dict[str, Any]]:
        buckets: Dict[str, Dict[str, float]] = {}
        for row in items:
            label = _answer_type(row) if key == "answer_type" else _route_family(row)
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
            bucket["answer_score_sum"] += _as_float(row.get("answer_score"))
            bucket["grounding_score_sum"] += _as_float(row.get("grounding_score"))
            bucket["telemetry_factor_sum"] += _as_float(row.get("telemetry_factor"))
            bucket["ttft_factor_sum"] += _as_float(row.get("ttft_factor"))
            bucket["overall_score_sum"] += _as_float(row.get("overall_score"))

        rows: List[Dict[str, Any]] = []
        for label in sorted(buckets.keys()):
            stats = buckets[label]
            count = int(stats["question_count"])
            if count <= 0:
                continue
            rows.append(
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
        return rows

    def _answerability(row: Dict[str, Any]) -> str:
        direct = _as_label(row.get("answerability"))
        return direct or "unknown"

    def _context_label(row: Dict[str, Any], key: str) -> str:
        direct = _as_label(row.get(key))
        return direct or "unknown"

    def _value_rows(items: List[Dict[str, Any]], *, key: str) -> List[Dict[str, Any]]:
        buckets: Dict[str, Dict[str, float | List[str]]] = {}
        total = max(1, len(items))
        for row in items:
            if key == "answer_type":
                label = _answer_type(row)
            elif key == "route_family":
                label = _route_family(row)
            elif key in {"document_scope", "corpus_domain", "temporal_scope"}:
                label = _context_label(row, key)
            else:
                label = _answerability(row)
            bucket = buckets.setdefault(
                label,
                {
                    "question_count": 0.0,
                    "overall_score_sum": 0.0,
                    "grounding_score_sum": 0.0,
                    "answer_score_sum": 0.0,
                    "ttft_factor_sum": 0.0,
                    "top_error_tags": [],
                },
            )
            bucket["question_count"] += 1.0
            bucket["overall_score_sum"] += _as_float(row.get("overall_score"))
            bucket["grounding_score_sum"] += _as_float(row.get("grounding_score"))
            bucket["answer_score_sum"] += _as_float(row.get("answer_score"))
            bucket["ttft_factor_sum"] += _as_float(row.get("ttft_factor"))
            tags = row.get("error_tags")
            if isinstance(tags, list):
                merged = [*bucket["top_error_tags"], *[str(tag) for tag in tags if str(tag).strip()]]
                bucket["top_error_tags"] = sorted(set(merged))[:3]

        rows: List[Dict[str, Any]] = []
        for label in sorted(buckets.keys()):
            stats = buckets[label]
            count = int(stats["question_count"])
            if count <= 0:
                continue
            current_overall = _as_float(stats["overall_score_sum"]) / count
            current_grounding = _as_float(stats["grounding_score_sum"]) / count
            current_answer = _as_float(stats["answer_score_sum"]) / count
            current_ttft = _as_float(stats["ttft_factor_sum"]) / count
            rows.append(
                {
                    key: label,
                    "question_count": count,
                    "coverage_share": count / total,
                    "current_overall": current_overall,
                    "current_grounding": current_grounding,
                    "current_answer": current_answer,
                    "current_ttft_factor": current_ttft,
                    "weighted_current_overall_value": count * current_overall,
                    "weighted_grounding_value": count * current_grounding,
                    "top_error_tags": list(stats["top_error_tags"]),
                    "verdict": "strong"
                    if current_overall >= 0.75
                    else "mixed"
                    if current_overall >= 0.4
                    else "weak",
                }
            )
        return rows

    def _compare_slice_rows(
        left_rows: List[Dict[str, Any]],
        right_rows: List[Dict[str, Any]],
        *,
        key: str,
    ) -> List[Dict[str, Any]]:
        left_map = {_as_label(row.get(key)): row for row in left_rows}
        right_map = {_as_label(row.get(key)): row for row in right_rows}
        out: List[Dict[str, Any]] = []
        for label in sorted(set(left_map.keys()) | set(right_map.keys())):
            left_row = left_map.get(label, {})
            right_row = right_map.get(label, {})
            out.append(
                {
                    key: label,
                    "left_question_count": int(_as_float(left_row.get("question_count"))),
                    "right_question_count": int(_as_float(right_row.get("question_count"))),
                    "question_count_delta": int(_as_float(right_row.get("question_count")) - _as_float(left_row.get("question_count"))),
                    "left_overall_score_mean": _as_float(left_row.get("overall_score_mean")),
                    "right_overall_score_mean": _as_float(right_row.get("overall_score_mean")),
                    "overall_score_mean_delta": _as_float(right_row.get("overall_score_mean")) - _as_float(left_row.get("overall_score_mean")),
                    "answer_score_mean_delta": _as_float(right_row.get("answer_score_mean")) - _as_float(left_row.get("answer_score_mean")),
                    "grounding_score_mean_delta": _as_float(right_row.get("grounding_score_mean")) - _as_float(left_row.get("grounding_score_mean")),
                    "telemetry_factor_mean_delta": _as_float(right_row.get("telemetry_factor_mean")) - _as_float(left_row.get("telemetry_factor_mean")),
                    "ttft_factor_mean_delta": _as_float(right_row.get("ttft_factor_mean")) - _as_float(left_row.get("ttft_factor_mean")),
                }
            )
        return out

    def _compare_value_rows(
        left_rows: List[Dict[str, Any]],
        right_rows: List[Dict[str, Any]],
        *,
        key: str,
    ) -> List[Dict[str, Any]]:
        left_map = {_as_label(row.get(key)): row for row in left_rows}
        right_map = {_as_label(row.get(key)): row for row in right_rows}
        out: List[Dict[str, Any]] = []
        for label in sorted(set(left_map.keys()) | set(right_map.keys())):
            left_row = left_map.get(label, {})
            right_row = right_map.get(label, {})
            out.append(
                {
                    key: label,
                    "question_count": int(_as_float(right_row.get("question_count"))),
                    "coverage_share": _as_float(right_row.get("coverage_share")),
                    "baseline_overall": _as_float(left_row.get("current_overall")),
                    "current_overall": _as_float(right_row.get("current_overall")),
                    "overall_delta": _as_float(right_row.get("current_overall")) - _as_float(left_row.get("current_overall")),
                    "grounding_delta": _as_float(right_row.get("current_grounding")) - _as_float(left_row.get("current_grounding")),
                    "answer_delta": _as_float(right_row.get("current_answer")) - _as_float(left_row.get("current_answer")),
                    "ttft_delta": _as_float(right_row.get("current_ttft_factor")) - _as_float(left_row.get("current_ttft_factor")),
                    "weighted_overall_delta": _as_float(right_row.get("weighted_current_overall_value")) - _as_float(left_row.get("weighted_current_overall_value")),
                    "weighted_grounding_delta": _as_float(right_row.get("weighted_grounding_value")) - _as_float(left_row.get("weighted_grounding_value")),
                    "top_error_tags": right_row.get("top_error_tags", []) or left_row.get("top_error_tags", []),
                    "verdict": right_row.get("verdict") or left_row.get("verdict") or "unknown",
                }
            )
        return out

    if runtime_pg.enabled():
        left_score = runtime_pg.get_exp_score(left_run_id) or {}
        right_score = runtime_pg.get_exp_score(right_run_id) or {}
        left_items = runtime_pg.list_exp_question_metrics(left_run_id)
        right_items = runtime_pg.list_exp_question_metrics(right_run_id)
    else:
        left_score = store.exp_scores.get(left_run_id, {})
        right_score = store.exp_scores.get(right_run_id, {})
        left_items = store.list_exp_question_metrics(left_run_id)
        right_items = store.list_exp_question_metrics(right_run_id)
    if not left_score or not right_score:
        raise ValueError("one or both experiment runs not found")
    left_map = {str(row.get("question_id")): row for row in left_items}
    right_map = {str(row.get("question_id")): row for row in right_items}
    question_deltas: List[Dict[str, Any]] = []
    for qid in sorted(set(left_map.keys()) | set(right_map.keys())):
        left_value = float((left_map.get(qid) or {}).get("overall_score", 0.0))
        right_value = float((right_map.get(qid) or {}).get("overall_score", 0.0))
        question_deltas.append(
            {
                "question_id": qid,
                "left_overall": left_value,
                "right_overall": right_value,
                "delta": right_value - left_value,
            }
        )
    left_by_answer_type = _slice_rows(left_items, key="answer_type")
    right_by_answer_type = _slice_rows(right_items, key="answer_type")
    left_by_route_family = _slice_rows(left_items, key="route_family")
    right_by_route_family = _slice_rows(right_items, key="route_family")
    left_value_by_answer_type = _value_rows(left_items, key="answer_type")
    right_value_by_answer_type = _value_rows(right_items, key="answer_type")
    left_value_by_route_family = _value_rows(left_items, key="route_family")
    right_value_by_route_family = _value_rows(right_items, key="route_family")
    left_value_by_answerability = _value_rows(left_items, key="answerability")
    right_value_by_answerability = _value_rows(right_items, key="answerability")
    left_value_by_document_scope = _value_rows(left_items, key="document_scope")
    right_value_by_document_scope = _value_rows(right_items, key="document_scope")
    left_value_by_corpus_domain = _value_rows(left_items, key="corpus_domain")
    right_value_by_corpus_domain = _value_rows(right_items, key="corpus_domain")
    left_value_by_temporal_scope = _value_rows(left_items, key="temporal_scope")
    right_value_by_temporal_scope = _value_rows(right_items, key="temporal_scope")
    return {
        "left_experiment_run_id": left_run_id,
        "right_experiment_run_id": right_run_id,
        "metric_deltas": {
            "overall_score_delta": float(right_score.get("overall_score", 0.0) - left_score.get("overall_score", 0.0)),
            "answer_score_delta": float(right_score.get("answer_score_mean", 0.0) - left_score.get("answer_score_mean", 0.0)),
            "grounding_score_delta": float(right_score.get("grounding_score_mean", 0.0) - left_score.get("grounding_score_mean", 0.0)),
            "telemetry_delta": float(right_score.get("telemetry_factor", 0.0) - left_score.get("telemetry_factor", 0.0)),
            "ttft_factor_delta": float(right_score.get("ttft_factor", 0.0) - left_score.get("ttft_factor", 0.0)),
        },
        "compare_slices": {
            "slice_version": COMPARE_SLICE_VERSION,
            "by_answer_type": _compare_slice_rows(
                left_by_answer_type,
                right_by_answer_type,
                key="answer_type",
            ),
            "by_route_family": _compare_slice_rows(
                left_by_route_family,
                right_by_route_family,
                key="route_family",
            ),
        },
        "value_report": {
            "report_version": "value_report.v1",
            "by_answer_type": _compare_value_rows(
                left_value_by_answer_type,
                right_value_by_answer_type,
                key="answer_type",
            ),
            "by_route_family": _compare_value_rows(
                left_value_by_route_family,
                right_value_by_route_family,
                key="route_family",
            ),
            "by_answerability": _compare_value_rows(
                left_value_by_answerability,
                right_value_by_answerability,
                key="answerability",
            ),
            "by_document_scope": _compare_value_rows(
                left_value_by_document_scope,
                right_value_by_document_scope,
                key="document_scope",
            ),
            "by_corpus_domain": _compare_value_rows(
                left_value_by_corpus_domain,
                right_value_by_corpus_domain,
                key="corpus_domain",
            ),
            "by_temporal_scope": _compare_value_rows(
                left_value_by_temporal_scope,
                right_value_by_temporal_scope,
                key="temporal_scope",
            ),
        },
        "question_deltas": question_deltas,
    }
