"""Typed answer resolvers and normalizers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple


_NO_ANSWER_MARKERS = (
    "outside",
    "irrelevant",
    "ambiguous",
    "not answerable",
    "unknown",
    "insufficient information",
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[-+]?(?:\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.\d+)?")
_CURRENCY_TOKEN_PATTERN = re.compile(
    r"\b(?:aed|usd|eur|gbp|qar|sar|omr|dirhams?|dollars?|euros?|pounds?)\b",
    re.IGNORECASE,
)
_DATE_TOKEN_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_NAME_LABEL_PREFIX_PATTERN = re.compile(
    r"^(?:the\s+)?(?:claimants?|respondents?|judges?|claimant|respondent|judge|presiding judge)\s*[:\-]\s*",
    re.IGNORECASE,
)
_NAME_LIST_SPLIT_PATTERN = re.compile(r"\s*(?:;|,|\band\b|\n)\s*", re.IGNORECASE)
_CASE_NUMBER_PATTERN = re.compile(r"\b[A-Z]{2,4}\s*\d{1,4}/\d{4}\b")
_SAME_YEAR_SPLIT_PATTERN = re.compile(r"\bsame year as\b", re.IGNORECASE)
_POSITIVE_BOOLEAN_PATTERN = re.compile(
    r"\b(?:approved|allowed|granted|same|authori[sz]ed|valid|in force|shall|must)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[\.\!\?])\s+")
_NEGATIVE_BOOLEAN_PATTERN = re.compile(
    r"\b(?:not|no|denied|dismissed|rejected|without|different)\b",
    re.IGNORECASE,
)
_MONTH_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
)
_UPPERCASE_NAME_TOKENS = {"LLC", "LLP", "LTD", "PLC", "PJSC", "DIFC", "UAE"}


@dataclass(frozen=True)
class DeterministicSolveResult:
    answer: Any
    abstained: bool
    confidence: float
    trace: Dict[str, Any] = field(default_factory=dict)


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_date_token(raw: Any) -> str | None:
    if raw is None:
        return None
    value = _collapse_whitespace(str(raw))
    if not value:
        return None
    value = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    if len(value) >= 10:
        try:
            return datetime.fromisoformat(value[:10]).date().isoformat()
        except ValueError:
            pass
    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if slash_match:
        first = int(slash_match.group(1))
        second = int(slash_match.group(2))
        if first > 12:
            value = f"{first:02d} {second:02d} {slash_match.group(3)}"
            try:
                return datetime.strptime(value, "%d %m %Y").date().isoformat()
            except ValueError:
                return None
        if second > 12:
            value = f"{first:02d} {second:02d} {slash_match.group(3)}"
            try:
                return datetime.strptime(value, "%m %d %Y").date().isoformat()
            except ValueError:
                return None
        return None
    normalized = value.replace(",", "")
    for date_format in _MONTH_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_boolean_value(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    value = _collapse_whitespace(str(raw)).lower()
    if value in {"true", "yes", "y", "1"}:
        return True
    if value in {"false", "no", "n", "0"}:
        return False
    return None


def _normalize_number_token(raw: Any) -> int | float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else raw
    value = _collapse_whitespace(str(raw))
    if not value:
        return None
    stripped = _CURRENCY_TOKEN_PATTERN.sub(" ", value)
    match = _NUMBER_TOKEN_PATTERN.search(stripped)
    if not match:
        return None
    token = match.group(0).replace(" ", "").replace(",", "")
    try:
        number = Decimal(token)
    except InvalidOperation:
        return None
    if number == number.to_integral():
        return int(number)
    return float(number.normalize())


def _canonicalize_name_token(token: str) -> str:
    if not token:
        return ""
    if any(char.isdigit() for char in token):
        return token.upper()
    bare = token.strip(".,;:")
    if not bare:
        return ""
    if bare.isupper() and len(bare) <= 5:
        return bare
    if bare.upper() in _UPPERCASE_NAME_TOKENS:
        return bare.upper()
    return bare[0].upper() + bare[1:].lower()


def _normalize_name_token(raw: Any) -> str | None:
    if raw is None:
        return None
    value = _collapse_whitespace(str(raw).strip(" \t\r\n,;:.-"))
    if not value:
        return None
    value = _NAME_LABEL_PREFIX_PATTERN.sub("", value)
    parts = [_canonicalize_name_token(part) for part in value.split()]
    parts = [part for part in parts if part]
    if not parts:
        return None
    return " ".join(parts)


def _normalize_name_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    normalized: List[str] = []
    seen = set()
    for item in items:
        if item is None:
            continue
        value = str(item)
        segments = [value]
        if isinstance(item, str):
            segments = [segment for segment in _NAME_LIST_SPLIT_PATTERN.split(value) if segment.strip()]
        for segment in segments:
            name = _normalize_name_token(segment)
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(name)
    normalized.sort(key=str.casefold)
    return normalized


def _normalize_scalar_answer(answer: Any, answer_type: str) -> Tuple[Any, str | None]:
    if answer is None:
        return None, None
    if answer_type == "boolean":
        value = _normalize_boolean_value(answer)
        if value is None:
            return None, None
        return value, "true" if value else "false"
    if answer_type == "number":
        value = _normalize_number_token(answer)
        if value is None:
            return None, None
        return value, f"{value:g}" if isinstance(value, float) else str(value)
    if answer_type == "date":
        value = _normalize_date_token(answer)
        return (value, value) if value else (None, None)
    if answer_type == "name":
        value = _normalize_name_token(answer)
        return (value, value) if value else (None, None)
    if answer_type == "free_text":
        value = _collapse_whitespace(str(answer))
        return (value, value) if value else (None, None)
    return answer, str(answer)


def normalize_answer(answer: Any, answer_type: str) -> Tuple[Any, str | None]:
    if answer is None:
        return None, None

    if answer_type == "names":
        values = _normalize_name_list(answer)
        return values, ", ".join(values) if values else None

    return _normalize_scalar_answer(answer, answer_type)


def _candidate_projection(candidate: Dict[str, Any]) -> Dict[str, Any]:
    projection = candidate.get("chunk_projection")
    return projection if isinstance(projection, dict) else {}


def _candidate_paragraph(candidate: Dict[str, Any]) -> Dict[str, Any]:
    paragraph = candidate.get("paragraph")
    return paragraph if isinstance(paragraph, dict) else {}


def _candidate_text(candidate: Dict[str, Any]) -> str:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)
    parts = [
        str(paragraph.get("text", "")),
        str(projection.get("retrieval_text", "")),
        str(projection.get("text_clean", "")),
    ]
    return " ".join(part for part in parts if part).strip()


def _candidate_evidence_text(candidate: Dict[str, Any]) -> str:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)
    parts = [
        str(paragraph.get("text", "")),
        str(projection.get("text_clean", "")),
    ]
    return _collapse_whitespace(" ".join(part for part in parts if part))


def _ordered_unique(values: List[Any]) -> List[Any]:
    ordered: List[Any] = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _build_trace(
    *,
    answer_type: str,
    route_name: str,
    path: str,
    candidate_count: int,
    matched_candidate_indices: List[int],
    values_considered: List[Any],
) -> Dict[str, Any]:
    return {
        "solver_version": "typed_deterministic_solver_v1",
        "answer_type": answer_type,
        "route_name": route_name,
        "execution_mode": "deterministic_evidence" if matched_candidate_indices else "deterministic_fallback",
        "path": path,
        "candidate_count": candidate_count,
        "matched_candidate_count": len(matched_candidate_indices),
        "matched_candidate_indices": matched_candidate_indices,
        "values_considered": [str(value) for value in values_considered[:8]],
    }


def _normalize_question_entity(raw: Any) -> str:
    value = _collapse_whitespace(str(raw or "").strip(" \t\r\n,;:.?"))
    if not value:
        return ""
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value.strip()


def _extract_same_year_entities(question_text: str) -> List[str]:
    if not _SAME_YEAR_SPLIT_PATTERN.search(question_text):
        return []
    left, right = _SAME_YEAR_SPLIT_PATTERN.split(question_text, maxsplit=1)
    left = re.sub(r"^.*?\bthe\s+", "", left, flags=re.IGNORECASE)
    left = re.sub(
        r"\s+(?:enacted|issued|made|adopted|promulgated|approved|administered)\s+in\s+the\s*$",
        "",
        left,
        flags=re.IGNORECASE,
    )
    right = re.sub(r"^\s*the\s+", "", right, flags=re.IGNORECASE)
    right = re.sub(r"[\?\.!]\s*$", "", right)
    entities = [_normalize_question_entity(left), _normalize_question_entity(right)]
    return [entity for entity in entities if entity]


def _candidate_matches_entity(candidate: Dict[str, Any], entity: str) -> bool:
    normalized = _normalize_question_entity(entity).casefold()
    if not normalized:
        return False
    return normalized in _candidate_evidence_text(candidate).casefold()


def _extract_candidate_year(candidate: Dict[str, Any]) -> int | None:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)
    for key in ("law_year", "regulation_year", "notice_year"):
        raw_value = projection.get(key)
        if isinstance(raw_value, int):
            return raw_value
    date_candidates: List[Any] = []
    date_candidates.extend(projection.get("dates", []) if isinstance(projection.get("dates"), list) else [])
    date_candidates.extend(paragraph.get("dates", []) if isinstance(paragraph.get("dates"), list) else [])
    for date_value in date_candidates:
        normalized = _normalize_date_token(date_value)
        if normalized:
            return int(normalized[:4])
    return None


def _normalize_case_number(raw: Any) -> str:
    value = _collapse_whitespace(str(raw or ""))
    return value.upper()


def _extract_question_case_numbers(question_text: str) -> List[str]:
    return _ordered_unique(_normalize_case_number(match.group(0)) for match in _CASE_NUMBER_PATTERN.finditer(question_text.upper()))


def _extract_candidate_case_number(candidate: Dict[str, Any]) -> str:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)
    raw_values: List[Any] = [projection.get("case_number")]
    raw_values.extend(projection.get("case_refs", []) if isinstance(projection.get("case_refs"), list) else [])
    raw_values.extend(paragraph.get("case_refs", []) if isinstance(paragraph.get("case_refs"), list) else [])
    for raw_value in raw_values:
        normalized = _normalize_case_number(raw_value)
        if normalized:
            return normalized
    match = _CASE_NUMBER_PATTERN.search(_candidate_evidence_text(candidate).upper())
    return _normalize_case_number(match.group(0)) if match else ""


def _extract_candidate_dates(candidate: Dict[str, Any]) -> List[str]:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)
    raw_values: List[Any] = []
    for key in ("decision_date", "commencement_date", "effective_start_date", "effective_end_date"):
        raw_value = projection.get(key)
        if raw_value:
            raw_values.append(raw_value)
    raw_values.extend(projection.get("dates", []) if isinstance(projection.get("dates"), list) else [])
    raw_values.extend(paragraph.get("dates", []) if isinstance(paragraph.get("dates"), list) else [])
    if not raw_values:
        raw_values.extend(_DATE_TOKEN_PATTERN.findall(_candidate_evidence_text(candidate)))
    return _ordered_unique([value for value in (_normalize_date_token(item) for item in raw_values) if value])


def _result(
    *,
    answer: Any,
    abstained: bool,
    confidence: float,
    answer_type: str,
    route_name: str,
    path: str,
    candidate_count: int,
    matched_candidate_indices: List[int],
    values_considered: List[Any],
) -> DeterministicSolveResult:
    return DeterministicSolveResult(
        answer=answer,
        abstained=abstained,
        confidence=confidence,
        trace=_build_trace(
            answer_type=answer_type,
            route_name=route_name,
            path=path,
            candidate_count=candidate_count,
            matched_candidate_indices=matched_candidate_indices,
            values_considered=values_considered,
        ),
    )


def _extract_same_year_boolean(question_text: str, candidates: List[Dict[str, Any]], route_name: str) -> DeterministicSolveResult | None:
    if "same year" not in question_text:
        return None
    targets = _extract_same_year_entities(question_text)
    if len(targets) >= 2:
        target_years: List[int] = []
        matched_indices: List[int] = []
        values_considered: List[str] = []
        for target in targets[:2]:
            years: List[int] = []
            target_indices: List[int] = []
            for index, candidate in enumerate(candidates):
                if not _candidate_matches_entity(candidate, target):
                    continue
                candidate_year = _extract_candidate_year(candidate)
                if candidate_year is None:
                    continue
                years.append(candidate_year)
                target_indices.append(index)
            unique_years = _ordered_unique(years)
            if len(unique_years) != 1:
                return _result(
                    answer=None,
                    abstained=True,
                    confidence=0.0,
                    answer_type="boolean",
                    route_name=route_name,
                    path="boolean_same_year_abstain_target_conflict",
                    candidate_count=len(candidates),
                    matched_candidate_indices=_ordered_unique(matched_indices + target_indices),
                    values_considered=values_considered + [f"{target}@{year}" for year in unique_years],
                )
            target_years.append(unique_years[0])
            matched_indices.extend(target_indices)
            values_considered.append(f"{target}@{unique_years[0]}")
        if len(target_years) == 2:
            return _result(
                answer=target_years[0] == target_years[1],
                abstained=False,
                confidence=0.96,
                answer_type="boolean",
                route_name=route_name,
                path="boolean_same_year",
                candidate_count=len(candidates),
                matched_candidate_indices=_ordered_unique(matched_indices),
                values_considered=values_considered,
            )
    years: List[int] = []
    matched_indices: List[int] = []
    for index, candidate in enumerate(candidates):
        candidate_year = _extract_candidate_year(candidate)
        if candidate_year is None:
            continue
        years.append(candidate_year)
        matched_indices.append(index)
    if len(years) < 2:
        return None
    return _result(
        answer=years[0] == years[1],
        abstained=False,
        confidence=0.96,
        answer_type="boolean",
        route_name=route_name,
        path="boolean_same_year",
        candidate_count=len(candidates),
        matched_candidate_indices=matched_indices[:2],
        values_considered=years[:2],
    )


def _solve_boolean(question_text: str, route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    same_year = _extract_same_year_boolean(question_text, candidates, route_name)
    if same_year is not None:
        return same_year

    positive_hits: List[int] = []
    negative_hits: List[int] = []
    for index, candidate in enumerate(candidates):
        text = _candidate_text(candidate)
        if not text:
            continue
        if _NEGATIVE_BOOLEAN_PATTERN.search(text):
            negative_hits.append(index)
        elif _POSITIVE_BOOLEAN_PATTERN.search(text):
            positive_hits.append(index)

    if positive_hits and not negative_hits:
        return _result(
            answer=True,
            abstained=False,
            confidence=0.82,
            answer_type="boolean",
            route_name=route_name,
            path="boolean_text_entailment",
            candidate_count=len(candidates),
            matched_candidate_indices=positive_hits,
            values_considered=["true"],
        )
    if negative_hits and not positive_hits:
        return _result(
            answer=False,
            abstained=False,
            confidence=0.82,
            answer_type="boolean",
            route_name=route_name,
            path="boolean_text_negation",
            candidate_count=len(candidates),
            matched_candidate_indices=negative_hits,
            values_considered=["false"],
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="boolean",
        route_name=route_name,
        path="boolean_abstain_unresolved",
        candidate_count=len(candidates),
        matched_candidate_indices=[],
        values_considered=[],
    )


def _extract_numeric_candidates(candidate_text: str, question_text: str) -> List[str]:
    values: List[str] = []
    lowered_question = question_text.lower()
    unit_terms: List[str] = []
    if "business day" in lowered_question:
        unit_terms.extend(["business day", "business days"])
    if "day" in lowered_question:
        unit_terms.extend(["day", "days"])
    if "month" in lowered_question:
        unit_terms.extend(["month", "months"])
    if "year" in lowered_question:
        unit_terms.extend(["year", "years"])

    if unit_terms:
        unit_pattern = re.compile(
            rf"(?P<number>{_NUMBER_TOKEN_PATTERN.pattern})\s*(?:{'|'.join(re.escape(term) for term in unit_terms)})\b",
            re.IGNORECASE,
        )
        for match in unit_pattern.finditer(candidate_text):
            values.append(match.group("number"))
        if values:
            return _ordered_unique(values)

    for match in _NUMBER_TOKEN_PATTERN.finditer(candidate_text):
        token = match.group(0)
        prefix = candidate_text[max(0, match.start() - 32): match.start()].lower()
        if re.search(r"(article|section|paragraph|clause)\s*$", prefix):
            continue
        if re.search(r"law\s+(?:no\.?|number)\s*$", prefix):
            continue
        values.append(token)
    return _ordered_unique(values)


def _solve_number(question_text: str, route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    values: List[int | float] = []
    matched_indices: List[int] = []
    lowered = question_text.lower()
    for index, candidate in enumerate(candidates):
        projection = _candidate_projection(candidate)
        paragraph = _candidate_paragraph(candidate)
        raw_values: List[Any] = []
        if any(token in lowered for token in ("claim value", "claim amount", "fine amount", "amount", "value")):
            raw_values.extend(projection.get("money_values", []) if isinstance(projection.get("money_values"), list) else [])
            raw_values.extend(paragraph.get("money_mentions", []) if isinstance(paragraph.get("money_mentions"), list) else [])
        if not raw_values and "law number" in lowered:
            raw_values.extend(
                [
                    projection.get("law_number"),
                    projection.get("regulation_number"),
                    projection.get("notice_number"),
                    projection.get("article_number"),
                ]
            )
        if not raw_values:
            raw_values.extend(_extract_numeric_candidates(_candidate_text(candidate), question_text))
        normalized = _ordered_unique(
            [number for number in (_normalize_number_token(value) for value in raw_values) if number is not None]
        )
        if not normalized:
            continue
        values.extend(normalized)
        matched_indices.append(index)

    unique_values = _ordered_unique(values)
    if len(unique_values) == 1:
        return _result(
            answer=unique_values[0],
            abstained=False,
            confidence=0.94,
            answer_type="number",
            route_name=route_name,
            path="number_evidence_value",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=unique_values,
        )
    if len(unique_values) > 1:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type="number",
            route_name=route_name,
            path="number_abstain_conflict",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=unique_values,
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="number",
        route_name=route_name,
        path="number_abstain_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=[],
        values_considered=[],
    )


def _solve_date(route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    values: List[str] = []
    matched_indices: List[int] = []
    for index, candidate in enumerate(candidates):
        normalized = _extract_candidate_dates(candidate)
        if not normalized:
            continue
        values.extend(normalized)
        matched_indices.append(index)

    unique_values = _ordered_unique(values)
    if len(unique_values) == 1:
        return _result(
            answer=unique_values[0],
            abstained=False,
            confidence=0.95,
            answer_type="date",
            route_name=route_name,
            path="date_evidence_value",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=unique_values,
        )
    if len(unique_values) > 1:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type="date",
            route_name=route_name,
            path="date_abstain_conflict",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=unique_values,
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="date",
        route_name=route_name,
        path="date_abstain_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=[],
        values_considered=[],
    )


def _solve_name(question_text: str, route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    lowered = question_text.lower()
    if "earlier" in lowered or "earliest" in lowered:
        target_cases = _extract_question_case_numbers(question_text)
        if target_cases:
            case_rows: List[Tuple[str, str, int]] = []
            matched_indices: List[int] = []
            for target_case in target_cases:
                case_dates: List[str] = []
                case_indices: List[int] = []
                for index, candidate in enumerate(candidates):
                    case_number = _extract_candidate_case_number(candidate)
                    if case_number != target_case:
                        continue
                    normalized_dates = _extract_candidate_dates(candidate)
                    if not normalized_dates:
                        continue
                    case_dates.extend(normalized_dates)
                    case_indices.append(index)
                unique_dates = _ordered_unique(case_dates)
                if len(unique_dates) != 1:
                    return _result(
                        answer=None,
                        abstained=True,
                        confidence=0.0,
                        answer_type="name",
                        route_name=route_name,
                        path="name_abstain_case_target_conflict",
                        candidate_count=len(candidates),
                        matched_candidate_indices=_ordered_unique(matched_indices + case_indices),
                        values_considered=[f"{target_case}@{date}" for date in unique_dates],
                    )
                matched_indices.extend(case_indices)
                case_rows.append((target_case, unique_dates[0], case_indices[0]))
            if case_rows:
                case_rows.sort(key=lambda row: row[1])
                earliest = case_rows[0]
                tied = [row for row in case_rows if row[1] == earliest[1]]
                if len(tied) == 1:
                    return _result(
                        answer=earliest[0],
                        abstained=False,
                        confidence=0.93,
                        answer_type="name",
                        route_name=route_name,
                        path="name_case_timeline",
                        candidate_count=len(candidates),
                        matched_candidate_indices=_ordered_unique(matched_indices),
                        values_considered=[f"{row[0]}@{row[1]}" for row in case_rows[:4]],
                    )
                return _result(
                    answer=None,
                    abstained=True,
                    confidence=0.0,
                    answer_type="name",
                    route_name=route_name,
                    path="name_abstain_case_tie",
                    candidate_count=len(candidates),
                    matched_candidate_indices=_ordered_unique(matched_indices),
                    values_considered=[f"{row[0]}@{row[1]}" for row in tied],
                )

    values: List[str] = []
    matched_indices: List[int] = []
    for index, candidate in enumerate(candidates):
        projection = _candidate_projection(candidate)
        paragraph = _candidate_paragraph(candidate)
        raw_values: List[Any] = []
        if "judge" in lowered:
            raw_values.extend(projection.get("judge_names", []) if isinstance(projection.get("judge_names"), list) else [])
        raw_values.extend(projection.get("entity_names", []) if isinstance(projection.get("entity_names"), list) else [])
        raw_values.extend(paragraph.get("entities", []) if isinstance(paragraph.get("entities"), list) else [])
        normalized = _ordered_unique([value for value in (_normalize_name_token(item) for item in raw_values) if value])
        if not normalized:
            continue
        values.extend(normalized[:1])
        matched_indices.append(index)
    unique_values = _ordered_unique(values)
    if len(unique_values) == 1:
        return _result(
            answer=unique_values[0],
            abstained=False,
            confidence=0.85,
            answer_type="name",
            route_name=route_name,
            path="name_evidence_entity",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=unique_values,
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="name",
        route_name=route_name,
        path="name_abstain_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=[],
        values_considered=[],
    )


def _extract_labeled_names(text: str, labels: List[str]) -> List[str]:
    if not text:
        return []
    for label in labels:
        pattern = re.compile(rf"\b{re.escape(label)}\b\s*[:\-]\s*(.+)", re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            continue
        extracted = match.group(1).split(".")[0]
        normalized = _normalize_name_list(extracted)
        if normalized:
            return normalized
    return []


def _solve_names(question_text: str, route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    lowered = question_text.lower()
    labels: List[str] = []
    if "claimant" in lowered:
        labels = ["claimants", "claimant"]
    elif "respondent" in lowered:
        labels = ["respondents", "respondent"]
    elif "judge" in lowered:
        labels = ["judges", "judge"]

    values: List[str] = []
    matched_indices: List[int] = []
    for index, candidate in enumerate(candidates):
        text = _candidate_text(candidate)
        raw_names: List[str] = _extract_labeled_names(text, labels) if labels else []
        if not raw_names:
            projection = _candidate_projection(candidate)
            paragraph = _candidate_paragraph(candidate)
            if "judge" in lowered:
                raw_names = _normalize_name_list(projection.get("judge_names", []))
            elif labels:
                raw_names = _normalize_name_list(paragraph.get("entities", []))
            else:
                raw_names = _normalize_name_list(projection.get("entity_names", []) or paragraph.get("entities", []))
        if not raw_names:
            continue
        values.extend(raw_names)
        matched_indices.append(index)

    normalized_values = _ordered_unique(_normalize_name_list(values))
    if normalized_values:
        return _result(
            answer=normalized_values,
            abstained=False,
            confidence=0.9,
            answer_type="names",
            route_name=route_name,
            path="names_evidence_list",
            candidate_count=len(candidates),
            matched_candidate_indices=matched_indices,
            values_considered=normalized_values,
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="names",
        route_name=route_name,
        path="names_abstain_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=[],
        values_considered=[],
    )


def _compact_free_text_extract(raw_text: str) -> str:
    text = _collapse_whitespace(raw_text)
    if not text:
        return ""
    sentences = [segment.strip() for segment in _SENTENCE_SPLIT_PATTERN.split(text) if segment.strip()]
    candidate = sentences[0] if sentences else text
    if len(candidate) <= 280:
        return candidate
    return candidate[:277].rstrip() + "..."


def _solve_free_text(question_text: str, route_name: str, candidates: List[Dict[str, Any]]) -> DeterministicSolveResult:
    extracts: List[Tuple[int, str]] = []
    for index, candidate in enumerate(candidates):
        extract = _compact_free_text_extract(_candidate_evidence_text(candidate))
        if not extract:
            continue
        extracts.append((index, extract))

    if not extracts:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type="free_text",
            route_name=route_name,
            path="free_text_abstain_missing_evidence",
            candidate_count=len(candidates),
            matched_candidate_indices=[],
            values_considered=[],
        )

    preferred = extracts[0]
    if _ARTICLE_MARKER_PATTERN.search(question_text):
        for index, extract in extracts:
            if _ARTICLE_MARKER_PATTERN.search(extract):
                preferred = (index, extract)
                break

    selected_index, selected_extract = preferred
    return _result(
        answer=selected_extract,
        abstained=False,
        confidence=0.74 if route_name == "article_lookup" else 0.66,
        answer_type="free_text",
        route_name=route_name,
        path="free_text_evidence_extract",
        candidate_count=len(candidates),
        matched_candidate_indices=[selected_index],
        values_considered=[extract for _, extract in extracts[:3]],
    )


def solve_deterministic(
    question: Dict[str, Any],
    route_name: str,
    candidates: List[Dict[str, Any]] | None = None,
) -> DeterministicSolveResult:
    text = str(question.get("question", "")).strip()
    lowered = text.lower()
    answer_type = str(question.get("answer_type", "free_text"))
    candidate_rows = candidates or []

    if not text:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="abstain_empty_question",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
        )

    if any(token in lowered for token in _NO_ANSWER_MARKERS):
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="abstain_no_answer_marker",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
        )

    if answer_type == "boolean":
        return _solve_boolean(text, route_name, candidate_rows)
    if answer_type == "number":
        return _solve_number(lowered, route_name, candidate_rows)
    if answer_type == "date":
        return _solve_date(route_name, candidate_rows)
    if answer_type == "name":
        return _solve_name(text, route_name, candidate_rows)
    if answer_type == "names":
        return _solve_names(lowered, route_name, candidate_rows)
    return _solve_free_text(text, route_name, candidate_rows)


def choose_used_sources(
    candidate_refs: List[Dict[str, Any]],
    route_name: str,
    *,
    question_text: str = "",
    answer_type: str = "free_text",
    used_page_limit: int | None = None,
) -> List[Dict[str, Any]]:
    used_sources, _ = choose_used_sources_with_trace(
        candidate_refs,
        route_name,
        question_text=question_text,
        answer_type=answer_type,
        used_page_limit=used_page_limit,
    )
    return used_sources


def _selection_keywords_from_ref(ref: Dict[str, Any], question_text: str) -> List[str]:
    values: List[str] = []
    values.extend(ref.get("article_refs", []) if isinstance(ref.get("article_refs"), list) else [])
    values.extend(ref.get("exact_terms", []) if isinstance(ref.get("exact_terms"), list) else [])
    values.extend(ref.get("entity_names", []) if isinstance(ref.get("entity_names"), list) else [])
    text = _collapse_whitespace(str(ref.get("chunk_text", "")))
    if text:
        query_tokens = _tokenize(question_text)
        values.extend(token for token in query_tokens if token in text.lower())
    return _ordered_unique([_collapse_whitespace(str(value)) for value in values if _collapse_whitespace(str(value))])


def _score_page_bucket_for_selection(
    bucket: Dict[str, Any],
    *,
    uncovered_keywords: set[str],
    route_name: str,
) -> float:
    coverage_hits = len([keyword for keyword in bucket["keywords"] if keyword in uncovered_keywords])
    score = float(bucket["best_score"])
    score += float(coverage_hits) * 0.25
    if bucket["exact_identifier_hit"]:
        score += 0.45
    if route_name == "history_lineage" and bucket["lineage_signal"]:
        score += 0.2
    return score


def choose_used_sources_with_trace(
    candidate_refs: List[Dict[str, Any]],
    route_name: str,
    *,
    question_text: str = "",
    answer_type: str = "free_text",
    used_page_limit: int | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not candidate_refs:
        return [], {
            "trace_version": "evidence_selection_trace_v1",
            "route_name": route_name,
            "selection_rule": "no_candidates",
            "answer_type": answer_type,
            "used_page_limit": int(used_page_limit or 0),
            "retrieved_candidate_count": 0,
            "used_candidate_count": 0,
            "retrieved_source_page_ids": [],
            "used_source_page_ids": [],
            "page_collapse_ratio": 0.0,
            "decisions": [],
        }

    selection_rule = "route_default_top2"
    selection_limit = 2
    if used_page_limit is not None and used_page_limit > 0:
        selection_rule = "profile_used_page_limit"
        selection_limit = int(used_page_limit)
    elif route_name in {"cross_case_compare", "cross_law_compare", "history_lineage", "article_lookup"}:
        selection_rule = "route_default_top3"
        selection_limit = 3

    page_buckets: Dict[str, Dict[str, Any]] = {}
    compare_instrument_order: List[str] = []
    for rank, ref in enumerate(candidate_refs):
        source_page_id = str(ref.get("source_page_id", "")).strip()
        if not source_page_id:
            continue
        compare_instrument_identifier = _collapse_whitespace(str(ref.get("compare_instrument_identifier", "")))
        if compare_instrument_identifier and compare_instrument_identifier not in compare_instrument_order:
            compare_instrument_order.append(compare_instrument_identifier)
        bucket = page_buckets.setdefault(
            source_page_id,
            {
                "source_page_id": source_page_id,
                "refs": [],
                "best_ref": None,
                "best_score": -1.0,
                "keywords": [],
                "exact_identifier_hit": False,
                "lineage_signal": False,
                "compare_instrument_identifier": compare_instrument_identifier,
            },
        )
        bucket["refs"].append(ref)
        try:
            score = float(ref.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if score > float(bucket["best_score"]):
            bucket["best_score"] = score
            bucket["best_ref"] = ref
        bucket["keywords"] = _ordered_unique(bucket["keywords"] + _selection_keywords_from_ref(ref, question_text))
        bucket["exact_identifier_hit"] = bool(bucket["exact_identifier_hit"] or ref.get("exact_identifier_hit"))
        bucket["lineage_signal"] = bool(
            bucket["lineage_signal"]
            or ref.get("lineage_signal")
            or route_name == "history_lineage"
        )
        if (
            compare_instrument_identifier
            and not _collapse_whitespace(str(bucket.get("compare_instrument_identifier", "")))
        ):
            bucket["compare_instrument_identifier"] = compare_instrument_identifier

    all_keywords = _ordered_unique(
        keyword
        for bucket in page_buckets.values()
        for keyword in bucket["keywords"]
    )
    uncovered_keywords = set(all_keywords)
    selected_pages: List[str] = []
    compare_coverage_selected: set[str] = set()

    if route_name == "cross_law_compare":
        if compare_instrument_order:
            selection_rule = "cross_law_compare_instrument_coverage"
        best_page_by_instrument: Dict[str, str] = {}
        for page_id, bucket in page_buckets.items():
            instrument_id = _collapse_whitespace(str(bucket.get("compare_instrument_identifier", "")))
            if not instrument_id:
                continue
            existing_page_id = best_page_by_instrument.get(instrument_id)
            if not existing_page_id:
                best_page_by_instrument[instrument_id] = page_id
                continue
            existing_bucket = page_buckets[existing_page_id]
            current_score = _score_page_bucket_for_selection(
                bucket,
                uncovered_keywords=uncovered_keywords,
                route_name=route_name,
            )
            existing_score = _score_page_bucket_for_selection(
                existing_bucket,
                uncovered_keywords=uncovered_keywords,
                route_name=route_name,
            )
            if current_score > existing_score:
                best_page_by_instrument[instrument_id] = page_id
        for instrument_id in compare_instrument_order:
            page_id = best_page_by_instrument.get(instrument_id)
            if not page_id or page_id in selected_pages:
                continue
            if len(selected_pages) >= selection_limit:
                break
            selected_pages.append(page_id)
            compare_coverage_selected.add(page_id)
            for keyword in page_buckets[page_id]["keywords"]:
                uncovered_keywords.discard(keyword)

    remaining_page_ids = [page_id for page_id in page_buckets.keys() if page_id not in selected_pages]
    while remaining_page_ids and len(selected_pages) < selection_limit:
        ranked_page_ids = sorted(
            remaining_page_ids,
            key=lambda page_id: (
                _score_page_bucket_for_selection(
                    page_buckets[page_id],
                    uncovered_keywords=uncovered_keywords,
                    route_name=route_name,
                ),
                float(page_buckets[page_id]["best_score"]),
            ),
            reverse=True,
        )
        next_page_id = ranked_page_ids[0]
        selected_pages.append(next_page_id)
        for keyword in page_buckets[next_page_id]["keywords"]:
            uncovered_keywords.discard(keyword)
        remaining_page_ids = [page_id for page_id in remaining_page_ids if page_id != next_page_id]

    selected = [
        page_buckets[page_id]["best_ref"]
        for page_id in selected_pages
        if isinstance(page_buckets[page_id].get("best_ref"), dict)
    ]
    selected_ids = {id(ref) for ref in selected}
    selected_page_ids = set(selected_pages)
    retrieved_source_page_ids: List[str] = []
    used_source_page_ids: List[str] = []
    compare_instrument_ids_retrieved: List[str] = []
    seen_retrieved = set()
    seen_used = set()
    seen_compare_retrieved = set()
    seen_compare_used = set()
    decisions: List[Dict[str, Any]] = []
    for rank, ref in enumerate(candidate_refs):
        source_page_id = str(ref.get("source_page_id", "")).strip()
        compare_instrument_identifier = _collapse_whitespace(str(ref.get("compare_instrument_identifier", "")))
        if source_page_id and source_page_id not in seen_retrieved:
            seen_retrieved.add(source_page_id)
            retrieved_source_page_ids.append(source_page_id)
        if compare_instrument_identifier and compare_instrument_identifier not in seen_compare_retrieved:
            seen_compare_retrieved.add(compare_instrument_identifier)
            compare_instrument_ids_retrieved.append(compare_instrument_identifier)
        selected_for_use = id(ref) in selected_ids
        if selected_for_use and source_page_id and source_page_id not in seen_used:
            seen_used.add(source_page_id)
            used_source_page_ids.append(source_page_id)
        if selected_for_use and compare_instrument_identifier and compare_instrument_identifier not in seen_compare_used:
            seen_compare_used.add(compare_instrument_identifier)
        try:
            score = float(ref.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        bucket = page_buckets.get(source_page_id, {})
        if selected_for_use:
            decision = "selected"
        elif source_page_id in selected_page_ids:
            decision = "collapsed"
        elif bucket.get("best_ref") is not ref and bucket.get("refs"):
            decision = "duplicate_suppressed"
        else:
            decision = "dropped_over_limit"
        if route_name == "history_lineage" and source_page_id in selected_page_ids and bucket.get("lineage_signal"):
            decision = "lineage_retained" if not selected_for_use else "selected"
        if (
            route_name == "cross_law_compare"
            and source_page_id in compare_coverage_selected
            and selected_for_use
        ):
            decision = "compare_coverage_selected"
        decisions.append(
            {
                "rank": rank,
                "source_page_id": source_page_id,
                "score": score,
                "selected": selected_for_use,
                "decision": decision,
                "compare_instrument_identifier": compare_instrument_identifier,
            }
        )

    compare_coverage_complete = True
    if route_name == "cross_law_compare" and compare_instrument_ids_retrieved:
        compare_coverage_complete = set(compare_instrument_ids_retrieved).issubset(set(seen_compare_used))

    trace = {
        "trace_version": "evidence_selection_trace_v1",
        "route_name": route_name,
        "selection_rule": selection_rule,
        "answer_type": answer_type,
        "used_page_limit": int(used_page_limit or 0),
        "retrieved_candidate_count": len(candidate_refs),
        "used_candidate_count": len(selected),
        "retrieved_source_page_ids": retrieved_source_page_ids,
        "used_source_page_ids": used_source_page_ids,
        "page_collapse_ratio": round(
            (len(retrieved_source_page_ids) / max(1, len(candidate_refs))),
            4,
        ),
        "compare_instrument_ids_retrieved": compare_instrument_ids_retrieved,
        "compare_instrument_ids_used": sorted(seen_compare_used),
        "compare_coverage_complete": compare_coverage_complete,
        "uncovered_keywords": sorted(uncovered_keywords),
        "decisions": decisions,
    }
    return selected, trace


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_ARTICLE_MARKER_PATTERN = re.compile(r"\b(article|section|clause|paragraph)\b", re.IGNORECASE)


def _tokenize(text: str) -> List[str]:
    return [token for token in _TOKEN_PATTERN.findall(text.lower()) if len(token) >= 3]


def build_route_recall_diagnostics(
    *,
    question_text: str,
    route_name: str,
    retrieval_profile_id: str,
    candidates: List[Dict[str, Any]],
    used_sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    query_tokens = set(_tokenize(question_text))
    covered_tokens = set()
    score_values: List[float] = []
    article_ref_hits = 0
    exact_identifier_hit_count = 0
    lineage_signal_count = 0

    for candidate in candidates:
        try:
            score_values.append(float(candidate.get("score", 0.0)))
        except (TypeError, ValueError):
            score_values.append(0.0)
        if candidate.get("exact_identifier_hit"):
            exact_identifier_hit_count += 1
        if candidate.get("lineage_signal"):
            lineage_signal_count += 1
        paragraph = candidate.get("paragraph")
        if not isinstance(paragraph, dict):
            continue
        paragraph_text = str(paragraph.get("text", ""))
        article_refs = paragraph.get("article_refs", [])
        if isinstance(article_refs, list) and article_refs:
            article_ref_hits += 1
            paragraph_text = f"{paragraph_text} {' '.join(str(item) for item in article_refs)}"
        candidate_tokens = set(_tokenize(paragraph_text))
        covered_tokens.update(query_tokens.intersection(candidate_tokens))

    candidate_count = len(candidates)
    used_count = len(used_sources)
    query_token_count = len(query_tokens)
    query_coverage = (len(covered_tokens) / query_token_count) if query_token_count else 0.0
    used_to_candidate_ratio = (used_count / candidate_count) if candidate_count else 0.0

    return {
        "diagnostics_version": "route_recall_diagnostics_v1",
        "route_name": route_name,
        "retrieval_profile_id": retrieval_profile_id,
        "candidate_count": candidate_count,
        "used_count": used_count,
        "query_token_count": query_token_count,
        "query_token_coverage": round(query_coverage, 4),
        "used_to_candidate_ratio": round(used_to_candidate_ratio, 4),
        "article_signal_present": bool(_ARTICLE_MARKER_PATTERN.search(question_text)),
        "article_ref_hit_count": article_ref_hits,
        "exact_identifier_hit_count": exact_identifier_hit_count,
        "lineage_signal_count": lineage_signal_count,
        "score_top": round(max(score_values), 4) if score_values else 0.0,
        "score_bottom": round(min(score_values), 4) if score_values else 0.0,
    }


def build_latency_budget_assertion(
    *,
    route_name: str,
    retrieval_profile_id: str,
    observed_ttft_ms: int,
    budget_ttft_ms: int,
) -> Dict[str, Any]:
    budget = max(0, int(budget_ttft_ms))
    observed = max(0, int(observed_ttft_ms))
    within_budget = observed <= budget
    return {
        "assertion_version": "latency_budget_assertion_v1",
        "route_name": route_name,
        "retrieval_profile_id": retrieval_profile_id,
        "budget_ttft_ms": budget,
        "observed_ttft_ms": observed,
        "over_budget_ms": max(0, observed - budget),
        "within_budget": within_budget,
    }
