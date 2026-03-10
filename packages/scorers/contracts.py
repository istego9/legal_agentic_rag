"""Contract validators and readable summaries for scorer outputs."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_SOURCE_PAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+_[0-9]+$")
_ALLOWED_ANSWER_TYPES = {"boolean", "number", "date", "name", "names", "free_text"}


def _read(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field, default)
    return getattr(value, field, default)


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _is_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def answer_schema_issues(
    *,
    answer: Any,
    answer_type: str,
    abstained: bool,
) -> list[str]:
    issues: list[str] = []
    a_type = str(answer_type).strip()
    if a_type not in _ALLOWED_ANSWER_TYPES:
        return [f"unsupported_answer_type:{a_type or 'empty'}"]

    if abstained:
        if a_type == "free_text":
            if answer is not None and not _is_non_empty_text(answer):
                issues.append("free_text_abstain_answer_must_be_non_empty_text_or_null")
        elif answer is not None:
            issues.append("abstain_answer_must_be_null_for_non_free_text")
        return issues

    if answer is None:
        return ["non_abstained_answer_must_not_be_null"]

    if a_type == "boolean":
        if not isinstance(answer, bool):
            issues.append("boolean_answer_must_be_bool")
    elif a_type == "number":
        if not isinstance(answer, (int, float)) or isinstance(answer, bool):
            issues.append("number_answer_must_be_numeric")
    elif a_type in {"date", "name", "free_text"}:
        if not _is_non_empty_text(answer):
            issues.append(f"{a_type}_answer_must_be_non_empty_text")
    elif a_type == "names":
        if not isinstance(answer, list) or not answer:
            issues.append("names_answer_must_be_non_empty_list")
        elif not all(_is_non_empty_text(item) for item in answer):
            issues.append("names_answer_items_must_be_non_empty_text")
    return issues


def source_page_id_issues(sources: Iterable[Any]) -> list[str]:
    issues: list[str] = []
    for index, source in enumerate(sources):
        used = bool(_read(source, "used", False))
        if not used:
            continue
        source_page_id = str(_read(source, "source_page_id", "")).strip()
        pdf_id = str(_read(source, "pdf_id", "")).strip()
        page_num = _read(source, "page_num", None)

        if not source_page_id:
            issues.append(f"sources[{index}].source_page_id_missing")
            continue
        if not _SOURCE_PAGE_ID_PATTERN.fullmatch(source_page_id):
            issues.append(f"sources[{index}].source_page_id_pattern_invalid")
            continue

        if not pdf_id:
            issues.append(f"sources[{index}].pdf_id_missing")
            continue
        if not isinstance(page_num, int) or page_num < 0:
            issues.append(f"sources[{index}].page_num_invalid")
            continue

        expected = f"{pdf_id}_{page_num}"
        if source_page_id != expected:
            issues.append(f"sources[{index}].source_page_id_not_canonical")
    return issues


def telemetry_issues(telemetry: Any) -> list[str]:
    issues: list[str] = []
    if not bool(_read(telemetry, "telemetry_complete", False)):
        issues.append("telemetry_complete_flag_false")
    if not _is_non_empty_text(_read(telemetry, "trace_id", "")):
        issues.append("trace_id_missing")
    if not _is_non_empty_text(_read(telemetry, "model_name", "")):
        issues.append("model_name_missing")
    if not _is_non_empty_text(_read(telemetry, "route_name", "")):
        issues.append("route_name_missing")
    if not _is_non_empty_text(_read(telemetry, "search_profile", "")):
        issues.append("search_profile_missing")

    ttft_ms = _to_float(_read(telemetry, "ttft_ms", 0.0))
    total_ms = _to_float(_read(telemetry, "total_response_ms", 0.0))
    if ttft_ms < 0:
        issues.append("ttft_ms_negative")
    if total_ms < 0:
        issues.append("total_response_ms_negative")
    if total_ms < ttft_ms:
        issues.append("total_response_ms_below_ttft_ms")
    return issues


def no_answer_form_issues(
    *,
    answer: Any,
    answer_type: str,
    abstained: bool,
    confidence: float,
    sources: Iterable[Any],
) -> list[str]:
    if not abstained:
        return []
    issues: list[str] = []

    used_source_count = sum(1 for source in sources if bool(_read(source, "used", False)))
    if used_source_count:
        issues.append("abstained_response_must_not_have_used_sources")
    if _to_float(confidence) > 0.0:
        issues.append("abstained_response_confidence_must_be_zero")

    a_type = str(answer_type).strip()
    if a_type == "free_text":
        if answer is not None and not _is_non_empty_text(answer):
            issues.append("free_text_abstain_answer_must_be_non_empty_text_or_null")
    elif answer is not None:
        issues.append("abstained_non_free_text_answer_must_be_null")
    return issues


def evaluate_query_response_contract(
    *,
    answer: Any,
    answer_type: str,
    abstained: bool,
    confidence: float,
    sources: Iterable[Any],
    telemetry: Any,
) -> dict[str, Any]:
    answer_issues = answer_schema_issues(answer=answer, answer_type=answer_type, abstained=abstained)
    source_issues = source_page_id_issues(sources)
    telemetry_contract_issues = telemetry_issues(telemetry)
    no_answer_issues = no_answer_form_issues(
        answer=answer,
        answer_type=answer_type,
        abstained=abstained,
        confidence=confidence,
        sources=sources,
    )

    merged_issues = (
        [f"answer_schema:{item}" for item in answer_issues]
        + [f"source_page_id:{item}" for item in source_issues]
        + [f"telemetry:{item}" for item in telemetry_contract_issues]
        + [f"no_answer:{item}" for item in no_answer_issues]
    )
    answer_schema_valid = not answer_issues
    source_page_id_valid = not source_issues
    telemetry_contract_valid = not telemetry_contract_issues
    no_answer_form_valid = not no_answer_issues
    return {
        "answer_schema_valid": answer_schema_valid,
        "source_page_id_valid": source_page_id_valid,
        "telemetry_contract_valid": telemetry_contract_valid,
        "no_answer_form_valid": no_answer_form_valid,
        "passed": answer_schema_valid
        and source_page_id_valid
        and telemetry_contract_valid
        and no_answer_form_valid,
        "issues": merged_issues,
        "issue_count": len(merged_issues),
    }


def build_scorer_summary_markdown(metrics: Mapping[str, Any]) -> str:
    def _metric(name: str) -> float:
        return _to_float(metrics.get(name, 0.0))

    def _fmt(value: float, *, digits: int = 4) -> str:
        return f"{value:.{digits}f}"

    lines = [
        "# Scorer Regression Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| overall_score | {_fmt(_metric('overall_score'))} |",
        f"| answer_score_mean | {_fmt(_metric('answer_score_mean'))} |",
        f"| grounding_score_mean | {_fmt(_metric('grounding_score_mean'))} |",
        f"| telemetry_factor | {_fmt(_metric('telemetry_factor'))} |",
        f"| telemetry_completeness_rate | {_fmt(_metric('telemetry_completeness_rate'))} |",
        f"| no_answer_precision | {_fmt(_metric('no_answer_precision'))} |",
        f"| no_answer_recall | {_fmt(_metric('no_answer_recall'))} |",
        f"| answer_schema_valid_rate | {_fmt(_metric('answer_schema_valid_rate'))} |",
        f"| source_page_id_valid_rate | {_fmt(_metric('source_page_id_valid_rate'))} |",
        f"| no_answer_form_valid_rate | {_fmt(_metric('no_answer_form_valid_rate'))} |",
        f"| contract_pass_rate | {_fmt(_metric('contract_pass_rate'))} |",
    ]
    return "\n".join(lines) + "\n"

