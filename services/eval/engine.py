"""Evaluation engine helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from legal_rag_api.contracts import (
    EvalRun,
    QueryResponse,
    RuntimePolicy,
    ScoringPolicy,
    export_used_source_page_ids,
)
from packages.scorers.contracts import (
    blocking_failure_histogram,
    build_scorer_summary_markdown,
    evaluate_query_response_contract,
    strict_competition_contracts_enabled,
)
from packages.scorers.metrics import overlap_stats

POLICY_REGISTRY_VERSION = "policy_registry.v1"
POLICY_FAMILY_NAMES = ("scoring", "retrieval", "solver", "prompt")
POLICY_VERSION_FIELDS = {
    "scoring": "scoring_policy_version",
    "retrieval": "retrieval_policy_version",
    "solver": "solver_policy_version",
    "prompt": "prompt_policy_version",
}
DEFAULT_POLICY_FAMILY_VERSIONS = {
    "scoring": "contest_v2026_public_rules_v1",
    "retrieval": "default",
    "solver": "default",
    "prompt": "default",
}
DEFAULT_SCORING_POLICY_SPEC = {
    "policy_version": DEFAULT_POLICY_FAMILY_VERSIONS["scoring"],
    "policy_type": "contest_emulation",
    "beta": 2.5,
    "ttft_curve": {
        "mode": "piecewise_linear_avg_ttft",
        "best_seconds": 1.0,
        "best_factor": 1.05,
        "worst_seconds": 5.0,
        "worst_factor": 0.85,
    },
    "telemetry_policy": "run_level_factor",
}
METRIC_SLICE_VERSION = "eval_metric_slices.v1"
EVAL_GOLD_EXPORT_COMPATIBILITY_VERSION = "eval_gold_export_compatibility.v1"
EVAL_GOLD_EXPORT_REQUIRED_FIELDS = (
    "question_id",
    "canonical_answer",
    "answer_type",
    "source_sets",
)


def _as_label(value: Any) -> str:
    if value is None:
        return ""
    label = str(value).strip()
    return label


def _dedupe_labels(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        label = _as_label(value)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_float(value: Any, *, default: float, min_value: float | None = None) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = float(default)
    if min_value is not None and out < min_value:
        return float(default)
    return out


def _first_label(*values: Any) -> str:
    for value in values:
        label = _as_label(value)
        if label:
            return label
    return ""


def _append_export_issue(
    issues: List[Dict[str, Any]],
    *,
    item_index: int,
    question_id: str,
    field: str,
    code: str,
    message: str,
) -> None:
    issue = {
        "item_index": item_index,
        "field": field,
        "code": code,
        "message": message,
    }
    if question_id:
        issue["question_id"] = question_id
    issues.append(issue)


def build_gold_export_compatibility_assertions(items: Iterable[Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    checked_count = 0

    for idx, item in enumerate(items):
        checked_count += 1
        payload = _as_mapping(item)
        question_id = _as_label(payload.get("question_id"))

        if not question_id:
            _append_export_issue(
                issues,
                item_index=idx,
                question_id=question_id,
                field="question_id",
                code="missing_or_empty",
                message="question_id must be a non-empty string",
            )

        if "canonical_answer" not in payload:
            _append_export_issue(
                issues,
                item_index=idx,
                question_id=question_id,
                field="canonical_answer",
                code="missing_field",
                message="canonical_answer field is required for eval compatibility",
            )

        answer_type = _as_label(payload.get("answer_type"))
        if not answer_type:
            _append_export_issue(
                issues,
                item_index=idx,
                question_id=question_id,
                field="answer_type",
                code="missing_or_empty",
                message="answer_type must be a non-empty string",
            )

        source_sets = payload.get("source_sets")
        if not isinstance(source_sets, list) or not source_sets:
            _append_export_issue(
                issues,
                item_index=idx,
                question_id=question_id,
                field="source_sets",
                code="missing_or_invalid",
                message="source_sets must be a non-empty list",
            )
            continue

        has_primary_set = False
        for source_idx, source_set in enumerate(source_sets):
            source_payload = _as_mapping(source_set)
            is_primary = source_payload.get("is_primary")
            if not isinstance(is_primary, bool):
                _append_export_issue(
                    issues,
                    item_index=idx,
                    question_id=question_id,
                    field=f"source_sets[{source_idx}].is_primary",
                    code="invalid_type",
                    message="is_primary must be a boolean",
                )
            elif is_primary:
                has_primary_set = True

            page_ids = source_payload.get("page_ids")
            if not isinstance(page_ids, list) or not page_ids:
                _append_export_issue(
                    issues,
                    item_index=idx,
                    question_id=question_id,
                    field=f"source_sets[{source_idx}].page_ids",
                    code="missing_or_invalid",
                    message="page_ids must be a non-empty list",
                )
                continue

            for page_idx, page_id in enumerate(page_ids):
                if not _as_label(page_id):
                    _append_export_issue(
                        issues,
                        item_index=idx,
                        question_id=question_id,
                        field=f"source_sets[{source_idx}].page_ids[{page_idx}]",
                        code="empty_value",
                        message="page_ids entries must be non-empty strings",
                    )

        if not has_primary_set:
            _append_export_issue(
                issues,
                item_index=idx,
                question_id=question_id,
                field="source_sets",
                code="missing_primary_source_set",
                message="at least one source_set must have is_primary=true",
            )

    return {
        "assertion_version": EVAL_GOLD_EXPORT_COMPATIBILITY_VERSION,
        "required_fields": list(EVAL_GOLD_EXPORT_REQUIRED_FIELDS),
        "checked_item_count": checked_count,
        "issue_count": len(issues),
        "compatible": not issues,
        "issues": issues,
    }


def collect_scoring_policy_versions(items: Iterable[Any]) -> List[str]:
    labels: List[str] = []
    for item in items:
        if isinstance(item, ScoringPolicy):
            labels.append(item.policy_version)
            continue
        payload = _as_mapping(item)
        labels.append(payload.get("policy_version"))
    return _dedupe_labels(labels)


def collect_scoring_policy_catalog(items: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    for item in items:
        payload: Dict[str, Any]
        if isinstance(item, ScoringPolicy):
            payload = item.model_dump(mode="json")
        else:
            payload = _as_mapping(item)
        version = _as_label(payload.get("policy_version"))
        if not version:
            continue
        catalog[version] = payload
    return catalog


def _normalize_ttft_curve(payload: Mapping[str, Any] | None) -> Dict[str, float | str]:
    defaults = _as_mapping(DEFAULT_SCORING_POLICY_SPEC.get("ttft_curve"))
    curve_payload = _as_mapping(payload)
    mode = _first_label(curve_payload.get("mode"), defaults.get("mode"))
    best_seconds = _as_float(
        curve_payload.get("best_seconds"),
        default=float(defaults.get("best_seconds", 1.0)),
        min_value=0.0,
    )
    worst_seconds = _as_float(
        curve_payload.get("worst_seconds"),
        default=float(defaults.get("worst_seconds", 5.0)),
        min_value=0.0,
    )
    if worst_seconds <= best_seconds:
        best_seconds = float(defaults.get("best_seconds", 1.0))
        worst_seconds = float(defaults.get("worst_seconds", 5.0))
    best_factor = _as_float(
        curve_payload.get("best_factor"),
        default=float(defaults.get("best_factor", 1.05)),
    )
    worst_factor = _as_float(
        curve_payload.get("worst_factor"),
        default=float(defaults.get("worst_factor", 0.85)),
    )
    return {
        "mode": mode or "piecewise_linear_avg_ttft",
        "best_seconds": best_seconds,
        "best_factor": best_factor,
        "worst_seconds": worst_seconds,
        "worst_factor": worst_factor,
    }


def resolve_scoring_policy_spec(
    scoring_policy_version: str,
    *,
    catalog: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    requested_version = _as_label(scoring_policy_version)
    catalog_payload: Dict[str, Dict[str, Any]] = {}
    for key, value in _as_mapping(catalog).items():
        version = _as_label(key)
        if not version:
            continue
        if isinstance(value, ScoringPolicy):
            catalog_payload[version] = value.model_dump(mode="json")
            continue
        normalized = _as_mapping(value)
        if normalized:
            catalog_payload[version] = normalized

    default_version = _as_label(DEFAULT_SCORING_POLICY_SPEC["policy_version"])
    if requested_version and requested_version in catalog_payload:
        resolved_version = requested_version
        resolution_rule = "requested_policy_version"
    elif default_version in catalog_payload:
        resolved_version = default_version
        resolution_rule = (
            "default_policy_for_unknown_requested_version"
            if requested_version
            else "default_policy_version"
        )
    elif catalog_payload:
        resolved_version = sorted(catalog_payload.keys())[0]
        resolution_rule = (
            "first_available_policy_for_unknown_requested_version"
            if requested_version
            else "first_available_policy_version"
        )
    else:
        resolved_version = default_version
        resolution_rule = (
            "builtin_default_for_unknown_requested_version"
            if requested_version
            else "builtin_default_policy_version"
        )

    defaults = dict(DEFAULT_SCORING_POLICY_SPEC)
    raw = catalog_payload.get(resolved_version, {})
    beta = _as_float(raw.get("beta"), default=float(defaults["beta"]), min_value=0.01)
    ttft_curve = _normalize_ttft_curve(raw.get("ttft_curve"))
    telemetry_policy = _first_label(raw.get("telemetry_policy"), defaults.get("telemetry_policy"))
    policy_type = _first_label(raw.get("policy_type"), defaults.get("policy_type"))

    return {
        "requested_policy_version": requested_version or None,
        "resolved_policy_version": resolved_version,
        "policy_type": policy_type,
        "beta": beta,
        "ttft_curve": ttft_curve,
        "telemetry_policy": telemetry_policy,
        "used_fallback": bool(requested_version and resolved_version != requested_version),
        "resolution_rule": resolution_rule,
    }


def build_policy_registry(
    *,
    scoring_policy_versions: Iterable[str],
    override: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    policies: Dict[str, Dict[str, Any]] = {}
    scoring_available = _dedupe_labels(scoring_policy_versions)
    if not scoring_available:
        scoring_available = [_as_label(DEFAULT_POLICY_FAMILY_VERSIONS["scoring"])]

    for family in POLICY_FAMILY_NAMES:
        default_version = _as_label(DEFAULT_POLICY_FAMILY_VERSIONS[family])
        available = scoring_available if family == "scoring" else [default_version]
        policies[family] = {
            "active_version": default_version,
            "fallback_version": default_version,
            "available_versions": list(available),
            "owner": "control-plane",
        }

    override_payload = _as_mapping(override)
    override_policies = _as_mapping(override_payload.get("policies"))
    for family in POLICY_FAMILY_NAMES:
        patch = _as_mapping(override_policies.get(family))
        if not patch:
            continue
        entry = policies[family]
        available = _dedupe_labels(
            patch.get("available_versions", patch.get("versions", entry.get("available_versions", [])))
        )
        if available:
            entry["available_versions"] = available
        active = _first_label(patch.get("active_version"), patch.get("active"), entry.get("active_version"))
        if active:
            entry["active_version"] = active
        fallback = _first_label(patch.get("fallback_version"), patch.get("fallback"), entry.get("fallback_version"))
        if fallback:
            entry["fallback_version"] = fallback

    for family in POLICY_FAMILY_NAMES:
        entry = policies[family]
        available = _dedupe_labels(entry.get("available_versions", []))
        default_version = _as_label(DEFAULT_POLICY_FAMILY_VERSIONS[family])
        if not available:
            available = [default_version]
        active = _first_label(entry.get("active_version"), default_version, available[0])
        if active not in available:
            available.insert(0, active)
        fallback = _as_label(entry.get("fallback_version"))
        if not fallback:
            active_idx = available.index(active)
            fallback = available[active_idx - 1] if active_idx > 0 else active
        if fallback not in available:
            available.append(fallback)
        entry["available_versions"] = available
        entry["active_version"] = active
        entry["fallback_version"] = fallback

    return {"registry_version": POLICY_REGISTRY_VERSION, "policies": policies}


def _resolve_policy_version(requested: str, entry: Mapping[str, Any]) -> Dict[str, Any]:
    available = _dedupe_labels(entry.get("available_versions", []))
    active = _first_label(entry.get("active_version"), available[0] if available else "")
    fallback = _first_label(entry.get("fallback_version"), active)
    if active not in available and active:
        available.insert(0, active)
    if fallback not in available and fallback:
        available.append(fallback)

    if requested:
        if requested in available:
            return {
                "requested_version": requested,
                "resolved_version": requested,
                "active_version": active,
                "fallback_version": fallback,
                "used_fallback": False,
                "rule": "requested_version",
            }
        return {
            "requested_version": requested,
            "resolved_version": fallback,
            "active_version": active,
            "fallback_version": fallback,
            "used_fallback": True,
            "rule": "fallback_for_unknown_requested_version",
        }
    return {
        "requested_version": None,
        "resolved_version": active,
        "active_version": active,
        "fallback_version": fallback,
        "used_fallback": False,
        "rule": "active_version_default",
    }


def resolve_policy_versions(
    *,
    registry: Mapping[str, Any],
    runtime_policy: RuntimePolicy | Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    eval_run: EvalRun | None = None,
) -> Dict[str, Any]:
    normalized = build_policy_registry(
        scoring_policy_versions=[],
        override=_as_mapping(registry),
    )
    policies = _as_mapping(normalized.get("policies"))
    profile_payload = _as_mapping(profile)
    profile_runtime_policy = _as_mapping(profile_payload.get("runtime_policy"))
    profile_versions = _as_mapping(profile_payload.get("policy_versions"))
    retrieval_profile = _as_mapping(profile_payload.get("retrieval_profile"))
    processing_profile = _as_mapping(profile_payload.get("processing_profile"))

    runtime_policy_payload: Dict[str, Any]
    if isinstance(runtime_policy, RuntimePolicy):
        runtime_policy_payload = runtime_policy.model_dump(mode="json")
    else:
        runtime_policy_payload = _as_mapping(runtime_policy)

    scoring_requested = _first_label(
        runtime_policy_payload.get("scoring_policy_version"),
        profile_versions.get("scoring_policy_version"),
        profile_versions.get("scoring"),
        profile_runtime_policy.get("scoring_policy_version"),
        processing_profile.get("scoring_policy_version"),
        eval_run.scoring_policy_version if eval_run else None,
    )
    retrieval_requested = _first_label(
        profile_versions.get("retrieval_policy_version"),
        profile_versions.get("retrieval"),
        retrieval_profile.get("policy_version"),
        retrieval_profile.get("profile_version"),
        retrieval_profile.get("version"),
    )
    solver_requested = _first_label(
        profile_versions.get("solver_policy_version"),
        profile_versions.get("solver"),
        processing_profile.get("solver_policy_version"),
        processing_profile.get("solver_version"),
    )
    prompt_requested = _first_label(
        profile_versions.get("prompt_policy_version"),
        profile_versions.get("prompt"),
        processing_profile.get("prompt_policy_version"),
        processing_profile.get("prompt_version"),
    )

    requested = {
        "scoring": scoring_requested,
        "retrieval": retrieval_requested,
        "solver": solver_requested,
        "prompt": prompt_requested,
    }

    resolution: Dict[str, Dict[str, Any]] = {}
    resolved_labels: Dict[str, str] = {}
    for family in POLICY_FAMILY_NAMES:
        info = _resolve_policy_version(_as_label(requested.get(family)), _as_mapping(policies.get(family)))
        resolution[family] = info
        resolved_labels[POLICY_VERSION_FIELDS[family]] = _as_label(info.get("resolved_version"))

    return {**resolved_labels, "resolution": resolution}


def runtime_policy_with_resolved_scoring(
    runtime_policy: RuntimePolicy,
    policy_versions: Mapping[str, Any],
) -> RuntimePolicy:
    scoring_version = _as_label(policy_versions.get("scoring_policy_version"))
    if not scoring_version or scoring_version == runtime_policy.scoring_policy_version:
        return runtime_policy
    return runtime_policy.model_copy(update={"scoring_policy_version": scoring_version})


def policy_versions_for_eval_run(
    eval_run: EvalRun,
    *,
    resolved_policy_versions: Mapping[str, Any] | None = None,
) -> Dict[str, str]:
    out = {
        "scoring_policy_version": _as_label(eval_run.scoring_policy_version)
        or _as_label(DEFAULT_POLICY_FAMILY_VERSIONS["scoring"]),
        "retrieval_policy_version": _as_label(DEFAULT_POLICY_FAMILY_VERSIONS["retrieval"]),
        "solver_policy_version": _as_label(DEFAULT_POLICY_FAMILY_VERSIONS["solver"]),
        "prompt_policy_version": _as_label(DEFAULT_POLICY_FAMILY_VERSIONS["prompt"]),
    }

    merged: List[Mapping[str, Any]] = []
    if isinstance(eval_run.metrics, Mapping):
        policy_versions_payload = eval_run.metrics.get("policy_versions")
        if isinstance(policy_versions_payload, Mapping):
            merged.append(policy_versions_payload)
    if resolved_policy_versions:
        merged.insert(0, resolved_policy_versions)
    for payload in merged:
        for family, field in POLICY_VERSION_FIELDS.items():
            label = _first_label(payload.get(field), payload.get(family))
            if label:
                out[field] = label
    return out


def eval_answer_score(pred: QueryResponse, gold: Dict[str, Any]) -> float:
    expected = gold.get("canonical_answer")
    if pred.abstained:
        return 1.0 if expected is None else 0.0
    if pred.answer == expected:
        return 1.0
    if isinstance(expected, list) and isinstance(pred.answer, list):
        set_exp = set(str(x) for x in expected)
        set_pred = set(str(x) for x in pred.answer)
        if set_pred == set_exp:
            return 1.0
        inter = len(set_exp.intersection(set_pred))
        if not set_exp:
            return 1.0 if not set_pred else 0.0
        return inter / len(set_exp)
    return 0.0


def eval_grounding(pred: QueryResponse, gold: Dict[str, Any], *, beta: float = 2.5) -> float:
    pred_ids = export_used_source_page_ids(pred.sources)
    all_gold = []
    for ss in gold.get("source_sets", []):
        ids = ss.get("page_ids", [])
        if ss.get("is_primary", False):
            all_gold.extend(ids)
    if not all_gold:
        return 1.0 if not pred_ids else 0.0
    _, _, fbeta = overlap_stats(pred_ids, all_gold, beta=beta)
    return float(fbeta)


def _gold_primary_ids(gold: Dict[str, Any]) -> List[str]:
    all_gold: List[str] = []
    for ss in gold.get("source_sets", []):
        ids = ss.get("page_ids", [])
        if ss.get("is_primary", False):
            all_gold.extend(str(item) for item in ids if str(item).strip())
    return _dedupe_labels(all_gold)


def _source_overlap(pred: QueryResponse, gold: Dict[str, Any], *, beta: float) -> tuple[float, float, float]:
    pred_ids = export_used_source_page_ids(pred.sources)
    gold_ids = _gold_primary_ids(gold)
    return overlap_stats(pred_ids, gold_ids, beta=beta)


def _question_error_tags(
    pred: QueryResponse,
    gold: Dict[str, Any],
    *,
    answer_score: float,
    source_precision: float,
    source_recall: float,
    ttft_factor: float,
    answer_schema_valid: bool,
    source_page_id_valid: bool,
    telemetry_contract_valid: bool,
    no_answer_form_valid: bool,
) -> List[str]:
    tags: List[str] = []
    if answer_score < 1.0:
        tags.append("answer_mismatch")
    if not answer_schema_valid:
        tags.append("answer_schema_invalid")
    if source_recall < 1.0:
        tags.append("missing_primary_source")
    if source_precision < 1.0 and export_used_source_page_ids(pred.sources):
        tags.append("overcited_sources")
    if not source_page_id_valid:
        tags.append("invalid_source_page_id")
    if not pred.telemetry.telemetry_complete:
        tags.append("telemetry_incomplete")
    if not telemetry_contract_valid and "telemetry_incomplete" not in tags:
        tags.append("telemetry_incomplete")
    if ttft_factor < 1.0:
        tags.append("ttft_slow")
    gold_has_no_answer = gold.get("canonical_answer") is None
    if pred.abstained != gold_has_no_answer:
        tags.append("abstain_mismatch")
    if not no_answer_form_valid:
        tags.append("no_answer_form_invalid")
    return tags


def eval_ttft_factor(avg_ttft_ms: float, *, ttft_curve: Mapping[str, Any] | None = None) -> float:
    curve = _normalize_ttft_curve(ttft_curve)
    best_seconds = float(curve["best_seconds"])
    worst_seconds = float(curve["worst_seconds"])
    best_factor = float(curve["best_factor"])
    worst_factor = float(curve["worst_factor"])
    ttft_sec = avg_ttft_ms / 1000.0
    if ttft_sec <= best_seconds:
        return best_factor
    if ttft_sec >= worst_seconds:
        return worst_factor
    ratio = (ttft_sec - best_seconds) / (worst_seconds - best_seconds)
    return best_factor + ratio * (worst_factor - best_factor)


def _aggregate_telemetry_factor(values: List[float], *, telemetry_policy: str) -> float:
    if not values:
        return 0.0
    policy = _as_label(telemetry_policy)
    if policy in {"all_or_nothing", "strict_all_required"}:
        return 1.0 if all(value >= 1.0 for value in values) else 0.0
    return sum(values) / len(values)


def _build_metric_slice_rows(
    question_metrics: List[Dict[str, Any]],
    *,
    key: str,
) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in question_metrics:
        label = _first_label(row.get(key), "unknown")
        buckets.setdefault(label, []).append(row)

    rows: List[Dict[str, Any]] = []
    for label in sorted(buckets.keys()):
        bucket = buckets[label]
        count = len(bucket)
        answer_score_mean = sum(float(item.get("answer_score", 0.0)) for item in bucket) / count
        grounding_score_mean = sum(float(item.get("grounding_score", 0.0)) for item in bucket) / count
        telemetry_factor_mean = sum(float(item.get("telemetry_factor", 0.0)) for item in bucket) / count
        ttft_factor_mean = sum(float(item.get("ttft_factor", 0.0)) for item in bucket) / count
        overall_score_mean = sum(float(item.get("overall_score", 0.0)) for item in bucket) / count
        rows.append(
            {
                key: label,
                "question_count": count,
                "answer_score_mean": answer_score_mean,
                "grounding_score_mean": grounding_score_mean,
                "telemetry_factor_mean": telemetry_factor_mean,
                "ttft_factor_mean": ttft_factor_mean,
                "overall_score_mean": overall_score_mean,
            }
        )
    return rows


def _build_metric_slices(question_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "slice_version": METRIC_SLICE_VERSION,
        "by_answer_type": _build_metric_slice_rows(question_metrics, key="answer_type"),
        "by_route_family": _build_metric_slice_rows(question_metrics, key="route_family"),
        "by_answerability": _build_metric_slice_rows(question_metrics, key="answerability"),
        "by_document_scope": _build_metric_slice_rows(question_metrics, key="document_scope"),
        "by_corpus_domain": _build_metric_slice_rows(question_metrics, key="corpus_domain"),
        "by_temporal_scope": _build_metric_slice_rows(question_metrics, key="temporal_scope"),
    }


def _error_tag_summary(question_metrics: List[Dict[str, Any]]) -> List[str]:
    counts: Dict[str, int] = {}
    for row in question_metrics:
        for tag in row.get("error_tags", []) if isinstance(row.get("error_tags"), list) else []:
            label = _as_label(tag)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [label for label, _ in ordered[:3]]


def _build_value_rows(question_metrics: List[Dict[str, Any]], *, key: str) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    total = max(1, len(question_metrics))
    for row in question_metrics:
        label = _first_label(row.get(key), "unknown")
        buckets.setdefault(label, []).append(row)

    rows: List[Dict[str, Any]] = []
    for label in sorted(buckets.keys()):
        bucket = buckets[label]
        count = len(bucket)
        current_overall = sum(float(item.get("overall_score", 0.0)) for item in bucket) / count
        current_grounding = sum(float(item.get("grounding_score", 0.0)) for item in bucket) / count
        current_answer = sum(float(item.get("answer_score", 0.0)) for item in bucket) / count
        current_ttft = sum(float(item.get("ttft_factor", 0.0)) for item in bucket) / count
        rows.append(
            {
                key: label,
                "question_count": count,
                "coverage_share": round(count / total, 4),
                "current_overall": current_overall,
                "current_grounding": current_grounding,
                "current_answer": current_answer,
                "current_ttft_factor": current_ttft,
                "weighted_current_overall_value": count * current_overall,
                "weighted_grounding_value": count * current_grounding,
                "top_error_tags": _error_tag_summary(bucket),
                "verdict": "strong"
                if current_overall >= 0.75
                else "mixed"
                if current_overall >= 0.4
                else "weak",
            }
        )
    return rows


def build_value_report(question_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "report_version": "value_report.v1",
        "by_answer_type": _build_value_rows(question_metrics, key="answer_type"),
        "by_route_family": _build_value_rows(question_metrics, key="route_family"),
        "by_answerability": _build_value_rows(question_metrics, key="answerability"),
        "by_document_scope": _build_value_rows(question_metrics, key="document_scope"),
        "by_corpus_domain": _build_value_rows(question_metrics, key="corpus_domain"),
        "by_temporal_scope": _build_value_rows(question_metrics, key="temporal_scope"),
    }


def aggregate_run(
    eval_run: EvalRun,
    predictions: List[QueryResponse],
    gold_questions: List[Dict[str, Any]],
    *,
    scoring_policy_catalog: Mapping[str, Any] | None = None,
    question_context_by_id: Mapping[str, Any] | None = None,
    strict_contract_mode: bool | None = None,
) -> Dict[str, Any]:
    strict_mode = strict_competition_contracts_enabled() if strict_contract_mode is None else bool(strict_contract_mode)
    policy_versions = policy_versions_for_eval_run(eval_run)
    scoring_policy = resolve_scoring_policy_spec(
        policy_versions.get("scoring_policy_version", ""),
        catalog=scoring_policy_catalog,
    )
    policy_versions["scoring_policy_version"] = _as_label(
        scoring_policy.get("resolved_policy_version")
    ) or policy_versions["scoring_policy_version"]
    if not predictions:
        empty_metrics = {
            "answer_score_mean": 0.0,
            "grounding_score_mean": 0.0,
            "telemetry_factor": 0.0,
            "ttft_factor": 0.0,
            "overall_score": 0.0,
            "S": 0.0,
            "G": 0.0,
            "T": 0.0,
            "F": 0.0,
            "source_precision": 0.0,
            "source_recall": 0.0,
            "source_f_beta": 0.0,
            "no_answer_precision": 0.0,
            "no_answer_recall": 0.0,
            "answer_schema_valid_rate": 0.0,
            "source_page_id_valid_rate": 0.0,
            "telemetry_completeness_rate": 0.0,
            "no_answer_form_valid_rate": 0.0,
            "contract_pass_rate": 0.0,
            "competition_contract_pass_rate": 0.0,
            "contract_severity_model": "blocking_only.v1",
            "invalid_prediction_count": 0,
            "blocking_contract_failure_histogram": {},
            "strict_contract_mode": strict_mode,
            "competition_gate_passed": True,
            "overall_score_raw": 0.0,
            "p50_ttft_ms": 0,
            "p95_ttft_ms": 0,
            "policy_versions": policy_versions,
            "scoring_policy": scoring_policy,
            "slices": {
                "slice_version": METRIC_SLICE_VERSION,
                "by_answer_type": [],
                "by_route_family": [],
                "by_answerability": [],
                "by_document_scope": [],
                "by_corpus_domain": [],
                "by_temporal_scope": [],
            },
            "value_report": {
                "report_version": "value_report.v1",
                "by_answer_type": [],
                "by_route_family": [],
                "by_answerability": [],
                "by_document_scope": [],
                "by_corpus_domain": [],
                "by_temporal_scope": [],
            },
        }
        empty_metrics["scorer_summary"] = {
            "summary_version": "scorer_summary.v1",
            "markdown": build_scorer_summary_markdown(empty_metrics),
        }
        return empty_metrics

    by_id = {g["question_id"]: g for g in gold_questions}
    a_scores = []
    g_scores = []
    ttfts = []
    telemetry_complete = []
    source_precisions = []
    source_recalls = []
    source_f_betas = []
    answer_schema_validity: List[float] = []
    source_page_id_validity: List[float] = []
    telemetry_contract_validity: List[float] = []
    no_answer_form_validity: List[float] = []
    contract_passes: List[float] = []
    competition_contract_validity: List[float] = []
    all_blocking_contract_failures: List[str] = []
    question_metrics: List[Dict[str, Any]] = []
    predicted_abstain = 0
    correct_abstain = 0
    gold_no_answer = 0
    beta = _as_float(scoring_policy.get("beta"), default=float(DEFAULT_SCORING_POLICY_SPEC["beta"]), min_value=0.01)
    ttft_curve = _as_mapping(scoring_policy.get("ttft_curve"))
    telemetry_policy = _first_label(
        scoring_policy.get("telemetry_policy"),
        DEFAULT_SCORING_POLICY_SPEC.get("telemetry_policy"),
    )

    for pred in predictions:
        gold = by_id.get(pred.question_id, {})
        answer_score = eval_answer_score(pred, gold)
        grounding_score = eval_grounding(pred, gold, beta=beta)
        source_precision, source_recall, source_f_beta = _source_overlap(pred, gold, beta=beta)
        ttft_ms = float(pred.telemetry.ttft_ms)
        telemetry_factor = 1.0 if pred.telemetry.telemetry_complete else 0.0
        question_ttft_factor = eval_ttft_factor(ttft_ms, ttft_curve=ttft_curve)
        question_overall = answer_score * grounding_score * telemetry_factor * question_ttft_factor
        answer_type = _first_label(pred.answer_type, gold.get("answer_type"), "unknown")
        route_family = _first_label(pred.route_name, gold.get("route_hint"), "unknown")
        question_context = _as_mapping((question_context_by_id or {}).get(pred.question_id))
        answerability = "unanswerable" if gold.get("canonical_answer") is None else "answerable"
        document_scope = _first_label(question_context.get("document_scope"), "unknown")
        corpus_domain = _first_label(question_context.get("corpus_domain"), "unknown")
        temporal_scope = _first_label(question_context.get("temporal_scope"), "unknown")
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
        answer_schema_valid = bool(contract_checks.get("answer_schema_valid", False))
        source_page_id_valid = bool(contract_checks.get("source_page_id_valid", False))
        telemetry_contract_valid = bool(contract_checks.get("telemetry_contract_valid", False))
        no_answer_form_valid = bool(contract_checks.get("no_answer_form_valid", False))
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
            question_overall = 0.0
        error_tags = _question_error_tags(
            pred,
            gold,
            answer_score=answer_score,
            source_precision=source_precision,
            source_recall=source_recall,
            ttft_factor=question_ttft_factor,
            answer_schema_valid=answer_schema_valid,
            source_page_id_valid=source_page_id_valid,
            telemetry_contract_valid=telemetry_contract_valid,
            no_answer_form_valid=no_answer_form_valid,
        )
        if blocking_contract_failures:
            error_tags.append("blocking_contract_failure")

        a_scores.append(answer_score)
        g_scores.append(grounding_score)
        ttfts.append(ttft_ms)
        telemetry_complete.append(telemetry_factor)
        source_precisions.append(source_precision)
        source_recalls.append(source_recall)
        source_f_betas.append(source_f_beta)
        answer_schema_validity.append(1.0 if answer_schema_valid else 0.0)
        source_page_id_validity.append(1.0 if source_page_id_valid else 0.0)
        telemetry_contract_validity.append(1.0 if telemetry_contract_valid else 0.0)
        no_answer_form_validity.append(1.0 if no_answer_form_valid else 0.0)
        competition_contract_validity.append(1.0 if competition_contract_valid else 0.0)
        contract_passes.append(1.0 if competition_contract_valid else 0.0)
        all_blocking_contract_failures.extend(blocking_contract_failures)
        if pred.abstained:
            predicted_abstain += 1
            if gold.get("canonical_answer") is None:
                correct_abstain += 1
        if gold.get("canonical_answer") is None:
            gold_no_answer += 1
        question_metrics.append(
            {
                "question_id": pred.question_id,
                "answer_type": answer_type,
                "route_family": route_family,
                "answer_score": answer_score,
                "grounding_score": grounding_score,
                "source_precision": source_precision,
                "source_recall": source_recall,
                "source_f_beta": source_f_beta,
                "telemetry_factor": telemetry_factor,
                "ttft_factor": question_ttft_factor,
                "overall_score": question_overall,
                "answerability": answerability,
                "document_scope": document_scope,
                "corpus_domain": corpus_domain,
                "temporal_scope": temporal_scope,
                "retrieval_profile_id": _first_label(question_context.get("retrieval_profile_id")),
                "candidate_count": int(question_context.get("candidate_count", 0) or 0),
                "used_page_count": int(question_context.get("used_page_count", 0) or 0),
                "answer_schema_valid": answer_schema_valid,
                "source_page_id_valid": source_page_id_valid,
                "telemetry_contract_valid": telemetry_contract_valid,
                "no_answer_form_valid": no_answer_form_valid,
                "blocking_contract_failures": blocking_contract_failures,
                "competition_contract_valid": competition_contract_valid,
                "prediction_valid_for_competition": prediction_valid_for_competition,
                "invalid_reason_tags": invalid_reason_tags,
                "contract_checks": contract_checks,
                "error_tags": error_tags,
            }
        )

    answer_score_mean = sum(a_scores) / len(a_scores)
    grounding_score_mean = sum(g_scores) / len(g_scores)
    ttft_ms = sum(ttfts) / len(ttfts)
    telemetry_factor = _aggregate_telemetry_factor(
        telemetry_complete,
        telemetry_policy=telemetry_policy,
    )
    ttft_factor = eval_ttft_factor(ttft_ms, ttft_curve=ttft_curve)
    overall_raw = answer_score_mean * grounding_score_mean * telemetry_factor * ttft_factor
    source_precision_mean = sum(source_precisions) / len(source_precisions)
    source_recall_mean = sum(source_recalls) / len(source_recalls)
    source_f_beta_mean = sum(source_f_betas) / len(source_f_betas)
    no_answer_precision = (correct_abstain / predicted_abstain) if predicted_abstain else 0.0
    no_answer_recall = (correct_abstain / gold_no_answer) if gold_no_answer else 0.0
    answer_schema_valid_rate = sum(answer_schema_validity) / len(answer_schema_validity)
    source_page_id_valid_rate = sum(source_page_id_validity) / len(source_page_id_validity)
    telemetry_completeness_rate = sum(telemetry_contract_validity) / len(telemetry_contract_validity)
    no_answer_form_valid_rate = sum(no_answer_form_validity) / len(no_answer_form_validity)
    contract_pass_rate = sum(contract_passes) / len(contract_passes)
    competition_contract_pass_rate = sum(competition_contract_validity) / len(competition_contract_validity)
    invalid_prediction_count = int(len(predictions) - sum(int(value) for value in competition_contract_validity))
    blocking_contract_failures = blocking_failure_histogram(all_blocking_contract_failures)
    overall = overall_raw
    if strict_mode:
        overall = overall_raw * competition_contract_pass_rate
    competition_gate_passed = invalid_prediction_count == 0
    metrics = {
        "answer_score_mean": answer_score_mean,
        "grounding_score_mean": grounding_score_mean,
        "telemetry_factor": telemetry_factor,
        "ttft_factor": ttft_factor,
        "overall_score": overall,
        "overall_score_raw": overall_raw,
        "S": answer_score_mean,
        "G": grounding_score_mean,
        "T": telemetry_factor,
        "F": ttft_factor,
        "source_precision": source_precision_mean,
        "source_recall": source_recall_mean,
        "source_f_beta": source_f_beta_mean,
        "no_answer_precision": no_answer_precision,
        "no_answer_recall": no_answer_recall,
        "answer_schema_valid_rate": answer_schema_valid_rate,
        "source_page_id_valid_rate": source_page_id_valid_rate,
        "telemetry_completeness_rate": telemetry_completeness_rate,
        "no_answer_form_valid_rate": no_answer_form_valid_rate,
        "contract_pass_rate": contract_pass_rate,
        "competition_contract_pass_rate": competition_contract_pass_rate,
        "contract_severity_model": "blocking_only.v1",
        "invalid_prediction_count": invalid_prediction_count,
        "blocking_contract_failure_histogram": blocking_contract_failures,
        "strict_contract_mode": strict_mode,
        "competition_gate_passed": competition_gate_passed,
        "p50_ttft_ms": int(sorted(ttfts)[len(ttfts) // 2]),
        "p95_ttft_ms": int(sorted(ttfts)[max(0, int(len(ttfts) * 0.95) - 1)]),
        "policy_versions": policy_versions,
        "scoring_policy": scoring_policy,
        "question_metrics": question_metrics,
        "slices": _build_metric_slices(question_metrics),
        "value_report": build_value_report(question_metrics),
    }
    metrics["scorer_summary"] = {
        "summary_version": "scorer_summary.v1",
        "markdown": build_scorer_summary_markdown(metrics),
    }
    return metrics
