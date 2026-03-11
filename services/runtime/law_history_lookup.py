"""Deterministic law-relation/history intent and solver utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import datetime
import re
from typing import Any, Dict, List, Tuple


RESOLUTION_VERSION = "law_history_lookup_resolution_v1"
SOLVER_VERSION = "law_history_deterministic_solver_v1"

_RELATION_KINDS = {
    "amended_by",
    "amends",
    "repealed_by",
    "repeals",
    "superseded_by",
    "supersedes",
    "enacted_on",
    "commenced_on",
    "effective_from",
    "current_version",
    "previous_version",
    "notice_mediated_commencement",
    "default_difc_application",
    "jurisdiction_opt_in",
}

_TEMPORAL_FOCUS_VALUES = {"current", "historical", "latest", "first_or_earliest"}

_WHITESPACE_PATTERN = re.compile(r"\s+")
_DATE_TOKEN_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[-+]?(?:\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.\d+)?")
_LAW_NUMBER_YEAR_PATTERN = re.compile(
    r"\b(?:difc\s+)?(?:law|regulation|act|code)\s+(?:no\.?|number)\s*(\d{1,4})(?:\s+of\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_NOTICE_NUMBER_YEAR_PATTERN = re.compile(
    r"\b(?:enactment|commencement)?\s*notice\s+(?:no\.?|number)?\s*(\d{1,4})(?:\s+of\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_LAW_TITLE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&'().,\- ]+?\s(?:Law|Regulation|Act|Code|Notice))"
    r"(?:\s+No\.?\s*(\d{1,4})\s+of\s+(\d{4})|\s+(\d{4}))?",
    re.IGNORECASE,
)
_PRONOUN_ANCHOR_PATTERN = re.compile(r"\b(it|this\s+law|that\s+law|the\s+law)\b", re.IGNORECASE)

_POSITIVE_BOOLEAN_PATTERN = re.compile(
    r"\b(?:yes|true|applies|applicable|in force|came into force|commenced|opted in|opt-in|exclusive jurisdiction|shall)\b",
    re.IGNORECASE,
)
_NEGATIVE_BOOLEAN_PATTERN = re.compile(
    r"\b(?:no|false|does not apply|not applicable|not in force|did not commence|unless agreed|unless the parties agree)\b",
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


@dataclass(frozen=True)
class DeterministicSolveResult:
    answer: Any
    abstained: bool
    confidence: float
    trace: Dict[str, Any] = field(default_factory=dict)


def _collapse_ws(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _uniq(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        token = _collapse_ws(item)
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _normalize_date_token(raw: Any) -> str | None:
    if raw is None:
        return None
    value = _collapse_ws(raw)
    if not value:
        return None
    value = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    if len(value) >= 10:
        try:
            return datetime.fromisoformat(value[:10]).date().isoformat()
        except ValueError:
            pass
    normalized = value.replace(",", "")
    if re.fullmatch(r"(?:19|20)\d{2}", normalized):
        return f"{normalized}-01-01"
    for date_format in _MONTH_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_number(raw: Any) -> int | float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else raw
    token_match = _NUMBER_TOKEN_PATTERN.search(_collapse_ws(raw))
    if not token_match:
        return None
    token = token_match.group(0).replace(",", "").replace(" ", "")
    try:
        number = Decimal(token)
    except InvalidOperation:
        return None
    if number == number.to_integral():
        return int(number)
    return float(number.normalize())


def _normalize_name(raw: Any) -> str | None:
    value = _collapse_ws(raw).strip(" \t\r\n,;:.\"")
    if not value:
        return None
    if len(value) <= 1:
        return None
    return value


def _extract_law_mentions(text: str) -> List[Dict[str, Any]]:
    mentions: List[Dict[str, Any]] = []
    for match in _LAW_TITLE_PATTERN.finditer(text):
        title = _collapse_ws(match.group(1))
        number = _collapse_ws(match.group(2) or "")
        year = _collapse_ws(match.group(3) or match.group(4) or "")
        if not title:
            continue
        mentions.append(
            {
                "title": title,
                "law_number": number or None,
                "law_year": year or None,
                "law_identifier": _slug(title),
            }
        )

    for match in _LAW_NUMBER_YEAR_PATTERN.finditer(text):
        number = _collapse_ws(match.group(1) or "")
        year = _collapse_ws(match.group(2) or "")
        law_identifier = f"law_no_{number}_of_{year}" if year else f"law_no_{number}"
        mentions.append(
            {
                "title": None,
                "law_number": number or None,
                "law_year": year or None,
                "law_identifier": law_identifier,
            }
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in mentions:
        key = (
            str(item.get("law_identifier") or ""),
            str(item.get("law_number") or ""),
            str(item.get("law_year") or ""),
            str(item.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]


def _extract_notice_mentions(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for match in _NOTICE_NUMBER_YEAR_PATTERN.finditer(text):
        number = _collapse_ws(match.group(1) or "")
        year = _collapse_ws(match.group(2) or "")
        notice_id = f"notice_no_{number}_of_{year}" if year else f"notice_no_{number}"
        out.append(
            {
                "notice_number": number or None,
                "notice_year": year or None,
                "notice_identifier": notice_id,
            }
        )
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in out:
        key = (str(item.get("notice_number") or ""), str(item.get("notice_year") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]


def _detect_relation_kind(lowered: str) -> str:
    if ("jurisdiction" in lowered or "difc court" in lowered or "difc courts" in lowered) and (
        "opt in" in lowered or "opt-in" in lowered or "submit" in lowered or "agreed" in lowered
    ):
        return "jurisdiction_opt_in"

    if "governing law" in lowered or "applicable law" in lowered:
        return "default_difc_application"

    if any(
        marker in lowered
        for marker in (
            "enactment notice",
            "commencement notice",
            "date specified in an enactment notice",
            "specified in an enactment notice",
        )
    ):
        return "notice_mediated_commencement"

    if "amended by" in lowered:
        return "amended_by"
    if "repealed by" in lowered:
        return "repealed_by"
    if "superseded by" in lowered:
        return "superseded_by"
    if re.search(r"\bamended\b", lowered):
        return "amended_by"
    if re.search(r"\brepealed\b", lowered):
        return "repealed_by"
    if re.search(r"\bsuperseded\b", lowered):
        return "superseded_by"

    if any(marker in lowered for marker in ("enacted on", "enactment date", "date of its enactment")):
        return "enacted_on"
    if "enacted" in lowered and ("when" in lowered or "date" in lowered):
        return "enacted_on"
    if any(
        marker in lowered
        for marker in (
            "commencement date",
            "came into force",
            "come into force",
            "commenced on",
            "commence on",
        )
    ):
        return "commenced_on"
    if "effective from" in lowered or "effective date" in lowered or "effective dates" in lowered:
        return "effective_from"

    if any(
        marker in lowered
        for marker in (
            "current version",
            "currently in force",
            "in force version",
            "latest law",
            "latest difc law",
        )
    ):
        return "current_version"
    if any(marker in lowered for marker in ("previous version", "prior law", "historical version", "earlier version")):
        return "previous_version"

    if any(marker in lowered for marker in ("what law did it amend", "which law did it amend")):
        return "amends"
    if re.search(r"\bamends?\b", lowered):
        return "amends"
    if re.search(r"\brepeals?\b", lowered):
        return "repeals"
    if re.search(r"\bsupersedes?\b", lowered):
        return "supersedes"

    if any(
        marker in lowered
        for marker in (
            "apply in the jurisdiction of the dubai international financial centre",
            "applies in the difc",
            "application of civil and commercial laws in the difc",
            "default application",
        )
    ):
        return "default_difc_application"
    return ""


def _detect_temporal_focus(lowered: str, relation_kind: str) -> str:
    if any(token in lowered for token in ("latest", "most recent", "currently in force")):
        return "latest"
    if any(token in lowered for token in ("first", "earliest")):
        return "first_or_earliest"
    if any(token in lowered for token in ("historical", "previous", "prior", "superseded", "repealed")):
        return "historical"
    if relation_kind in {"current_version", "default_difc_application", "jurisdiction_opt_in"}:
        return "current"
    return "historical"


def _is_structural_required(
    *,
    relation_kind: str,
    has_explicit_anchor: bool,
    question_text: str,
) -> bool:
    if relation_kind not in _RELATION_KINDS:
        return False
    if relation_kind == "notice_mediated_commencement" and "enactment notice" in question_text.lower():
        return False
    if has_explicit_anchor:
        return False
    if _PRONOUN_ANCHOR_PATTERN.search(question_text):
        return True
    return relation_kind in {
        "amended_by",
        "amends",
        "repealed_by",
        "repeals",
        "superseded_by",
        "supersedes",
        "current_version",
        "previous_version",
        "enacted_on",
        "commenced_on",
        "effective_from",
    }


def resolve_law_history_lookup_intent(question_text: str) -> Dict[str, Any]:
    raw_text = _collapse_ws(question_text)
    lowered = raw_text.lower()

    law_mentions = _extract_law_mentions(raw_text)
    notice_mentions = _extract_notice_mentions(raw_text)
    relation_kind = _detect_relation_kind(lowered)
    temporal_focus = _detect_temporal_focus(lowered, relation_kind)

    is_difc_context = any(
        marker in lowered
        for marker in (
            "difc",
            "dubai international financial centre",
            "difc laws",
            "difc law",
        )
    )
    is_jurisdiction_question = any(
        marker in lowered
        for marker in (
            "jurisdiction",
            "forum",
            "court jurisdiction",
            "difc courts",
            "court of first instance",
        )
    )
    is_governing_law_question = any(
        marker in lowered
        for marker in (
            "governing law",
            "applicable law",
            "law applies",
            "application of",
        )
    )
    is_notice_mediated = any(
        marker in lowered
        for marker in (
            "enactment notice",
            "commencement notice",
            "specified in an enactment notice",
            "specified in the enactment notice",
        )
    ) or bool(notice_mentions)
    is_current_vs_historical_question = any(
        marker in lowered
        for marker in (
            "current",
            "latest",
            "previous",
            "historical",
            "amended",
            "repealed",
            "superseded",
            "enacted",
            "commenc",
            "effective",
        )
    )

    relation_kind = relation_kind or (
        "default_difc_application" if is_governing_law_question and not is_jurisdiction_question else ""
    )
    if relation_kind == "" and is_notice_mediated:
        relation_kind = "notice_mediated_commencement"

    anchored_laws = [
        item
        for item in law_mentions
        if item.get("law_number") or item.get("law_year")
    ]
    target_law = anchored_laws[0] if anchored_laws else (law_mentions[0] if law_mentions else {})
    related_laws = [item for item in law_mentions if item is not target_law]
    target_notice = notice_mentions[0] if notice_mentions else {}

    target_law_identifier = target_law.get("law_identifier") if target_law else None
    related_law_identifiers = [
        str(item.get("law_identifier"))
        for item in related_laws
        if str(item.get("law_identifier") or "").strip()
    ]
    target_notice_identifier = target_notice.get("notice_identifier") if target_notice else None
    target_notice_identifiers = [
        str(item.get("notice_identifier"))
        for item in notice_mentions
        if str(item.get("notice_identifier") or "").strip()
    ]

    has_explicit_anchor = bool(target_law_identifier or target_notice_identifier or law_mentions or notice_mentions)
    requires_structural_resolution = _is_structural_required(
        relation_kind=relation_kind,
        has_explicit_anchor=has_explicit_anchor,
        question_text=raw_text,
    )

    confidence = 0.0
    if relation_kind:
        confidence += 0.42
    if target_law_identifier:
        confidence += 0.2
    if target_notice_identifier:
        confidence += 0.16
    if related_law_identifiers:
        confidence += 0.12
    if temporal_focus in _TEMPORAL_FOCUS_VALUES:
        confidence += 0.06
    if is_notice_mediated:
        confidence += 0.08
    if is_difc_context:
        confidence += 0.04
    resolution_confidence = round(min(0.99, confidence), 2)

    return {
        "resolver_version": RESOLUTION_VERSION,
        "relation_kind": relation_kind or None,
        "temporal_focus": temporal_focus,
        "target_law_identifier": target_law_identifier,
        "target_law_title": target_law.get("title") if target_law else None,
        "target_law_number": target_law.get("law_number") if target_law else None,
        "target_law_year": target_law.get("law_year") if target_law else None,
        "related_law_identifiers": related_law_identifiers,
        "related_law_titles": [item.get("title") for item in related_laws if item.get("title")],
        "target_notice_identifier": target_notice_identifier,
        "target_notice_identifiers": target_notice_identifiers,
        "target_notice_number": target_notice.get("notice_number") if target_notice else None,
        "target_notice_year": target_notice.get("notice_year") if target_notice else None,
        "law_mentions": law_mentions,
        "notice_mentions": notice_mentions,
        "resolution_confidence": resolution_confidence,
        "requires_structural_resolution": requires_structural_resolution,
        "has_explicit_anchor": has_explicit_anchor,
        "is_difc_context": is_difc_context,
        "is_jurisdiction_question": is_jurisdiction_question,
        "is_governing_law_question": is_governing_law_question,
        "is_notice_mediated": is_notice_mediated,
        "is_current_vs_historical_question": is_current_vs_historical_question,
    }


def build_law_history_retrieval_hints(question_text: str, history_intent: Dict[str, Any]) -> Dict[str, Any]:
    relation_kind = str(history_intent.get("relation_kind") or "")
    lower = _collapse_ws(question_text).lower()

    doc_type_priority = ["law", "regulation", "enactment_notice"]
    if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from", "enacted_on"}:
        doc_type_priority = ["enactment_notice", "law", "regulation"]
    elif relation_kind in {"default_difc_application", "jurisdiction_opt_in"}:
        doc_type_priority = ["law", "regulation", "enactment_notice"]

    relation_terms = {
        "amended_by": ["amended by", "amendment law"],
        "amends": ["amends", "amendment"],
        "repealed_by": ["repealed by"],
        "repeals": ["repeals", "repeal"],
        "superseded_by": ["superseded by"],
        "supersedes": ["supersedes", "supersede"],
        "enacted_on": ["enacted", "enactment"],
        "commenced_on": ["commencement", "came into force"],
        "effective_from": ["effective date", "effective from"],
        "current_version": ["current version", "latest"],
        "previous_version": ["previous version", "prior"],
        "notice_mediated_commencement": ["enactment notice", "commencement notice"],
        "default_difc_application": ["DIFC", "application"],
        "jurisdiction_opt_in": ["jurisdiction", "opt in", "DIFC Courts"],
    }

    expansions: List[str] = []
    expansions.extend(relation_terms.get(relation_kind, []))
    for marker_key in ("target_law_title", "target_law_number", "target_law_year"):
        value = _collapse_ws(history_intent.get(marker_key))
        if value:
            expansions.append(value)
    for value in history_intent.get("related_law_titles", []) if isinstance(history_intent.get("related_law_titles"), list) else []:
        token = _collapse_ws(value)
        if token:
            expansions.append(token)
    for value in history_intent.get("target_notice_identifiers", []) if isinstance(history_intent.get("target_notice_identifiers"), list) else []:
        token = _collapse_ws(value)
        if token:
            expansions.append(token)

    expanded_query = _collapse_ws(" ".join([question_text, *expansions]))
    if not expanded_query:
        expanded_query = question_text

    return {
        "hint_version": "law_history_retrieval_hints_v1",
        "relation_kind": relation_kind or None,
        "doc_type_priority": doc_type_priority,
        "expanded_query": expanded_query,
        "expansion_terms": _uniq(expansions),
        "lineage_expansion_enabled": bool(history_intent.get("is_current_vs_historical_question") or relation_kind in {
            "amended_by",
            "amends",
            "repealed_by",
            "repeals",
            "superseded_by",
            "supersedes",
            "current_version",
            "previous_version",
        }),
        "contains_notice_hint": bool("notice" in lower or history_intent.get("is_notice_mediated")),
    }


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
        str(projection.get("text_clean", "")),
        str(projection.get("retrieval_text", "")),
    ]
    return _collapse_ws(" ".join(part for part in parts if part))


def _ordered_unique(values: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _candidate_matches_notice_anchor(candidate: Dict[str, Any], history_intent: Dict[str, Any]) -> bool:
    target_notice_number = _collapse_ws(history_intent.get("target_notice_number"))
    target_notice_year = _collapse_ws(history_intent.get("target_notice_year"))
    if not target_notice_number and not target_notice_year:
        return True
    projection = _candidate_projection(candidate)
    projected_number = _collapse_ws(projection.get("notice_number"))
    projected_year = _collapse_ws(projection.get("notice_year"))
    if target_notice_number and projected_number and target_notice_number != projected_number:
        return False
    if target_notice_year and projected_year and target_notice_year != projected_year:
        return False
    if (target_notice_number and not projected_number) or (target_notice_year and not projected_year):
        text = _candidate_text(candidate).lower()
        if target_notice_number and f"notice no. {target_notice_number}".lower() not in text and f"notice {target_notice_number}" not in text:
            return False
        if target_notice_year and target_notice_year not in text:
            return False
    return True


def _candidate_matches_law_anchor(candidate: Dict[str, Any], history_intent: Dict[str, Any]) -> bool:
    target_law_number = _collapse_ws(history_intent.get("target_law_number"))
    target_law_year = _collapse_ws(history_intent.get("target_law_year"))
    if not target_law_number and not target_law_year:
        return True
    projection = _candidate_projection(candidate)
    projected_number = _collapse_ws(projection.get("law_number"))
    projected_year = _collapse_ws(projection.get("law_year") or projection.get("regulation_year"))
    if target_law_number and projected_number and target_law_number != projected_number:
        return False
    if target_law_year and projected_year and target_law_year != projected_year:
        return False
    if (target_law_number and not projected_number) or (target_law_year and not projected_year):
        text = _candidate_text(candidate).lower()
        if target_law_number and f"law no. {target_law_number}" not in text and f"law no {target_law_number}" not in text:
            return False
        if target_law_year and target_law_year not in text:
            return False
    return True


def _extract_candidate_dates(candidate: Dict[str, Any], relation_kind: str) -> List[str]:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)

    key_priority = ["commencement_date", "effective_start_date", "issued_date", "decision_date", "effective_end_date"]
    if relation_kind == "enacted_on":
        key_priority = ["enactment_date", "issued_date", "promulgation_date", "commencement_date", "effective_start_date"]
    elif relation_kind in {"commenced_on", "notice_mediated_commencement"}:
        key_priority = ["commencement_date", "effective_start_date", "issued_date", "enactment_date"]
    elif relation_kind == "effective_from":
        key_priority = ["effective_start_date", "commencement_date", "issued_date"]

    values: List[Any] = []
    for key in key_priority:
        if projection.get(key):
            values.append(projection.get(key))
    values.extend(projection.get("dates", []) if isinstance(projection.get("dates"), list) else [])
    values.extend(paragraph.get("dates", []) if isinstance(paragraph.get("dates"), list) else [])
    if not values:
        values.extend(_DATE_TOKEN_PATTERN.findall(_candidate_text(candidate)))

    normalized = [_normalize_date_token(value) for value in values]
    return _ordered_unique([value for value in normalized if value])


def _extract_relation_names(candidate: Dict[str, Any], relation_kind: str) -> List[str]:
    projection = _candidate_projection(candidate)
    paragraph = _candidate_paragraph(candidate)

    if relation_kind in {"amended_by", "repealed_by", "superseded_by"}:
        explicit = projection.get("amended_by_doc_ids")
        if isinstance(explicit, list) and explicit:
            normalized = [_normalize_name(value) for value in explicit]
            return _ordered_unique([value for value in normalized if value])
    if relation_kind in {"amends", "repeals", "supersedes"}:
        explicit = projection.get("amends_law_ids")
        if isinstance(explicit, list) and explicit:
            normalized = [_normalize_name(value) for value in explicit]
            return _ordered_unique([value for value in normalized if value])

    values: List[Any] = []
    values.extend(projection.get("law_refs", []) if isinstance(projection.get("law_refs"), list) else [])
    values.extend(paragraph.get("law_refs", []) if isinstance(paragraph.get("law_refs"), list) else [])

    for key in (
        "law_title",
        "title",
        "citation_title",
        "document_title",
        "short_title",
        "target_title",
        "enabled_by_law_id",
        "target_doc_id",
    ):
        if projection.get(key):
            values.append(projection.get(key))

    normalized = [_normalize_name(value) for value in values]
    return _ordered_unique([value for value in normalized if value])


def _build_trace(
    *,
    answer_type: str,
    route_name: str,
    path: str,
    candidate_count: int,
    matched_candidate_indices: List[int],
    values_considered: List[Any],
    history_intent: Dict[str, Any],
) -> Dict[str, Any]:
    legal_context_flags = {
        "is_difc_context": bool(history_intent.get("is_difc_context")),
        "is_jurisdiction_question": bool(history_intent.get("is_jurisdiction_question")),
        "is_governing_law_question": bool(history_intent.get("is_governing_law_question")),
        "is_notice_mediated": bool(history_intent.get("is_notice_mediated")),
        "is_current_vs_historical_question": bool(history_intent.get("is_current_vs_historical_question")),
    }
    return {
        "solver_version": SOLVER_VERSION,
        "answer_type": answer_type,
        "route_name": route_name,
        "execution_mode": "deterministic_evidence" if matched_candidate_indices else "deterministic_fallback",
        "path": path,
        "candidate_count": candidate_count,
        "matched_candidate_count": len(matched_candidate_indices),
        "matched_candidate_indices": matched_candidate_indices,
        "values_considered": [str(value) for value in values_considered[:10]],
        "law_history_lookup_resolution": history_intent,
        "legal_context_flags": legal_context_flags,
    }


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
    history_intent: Dict[str, Any],
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
            history_intent=history_intent,
        ),
    )


def _source_of_law_guardrail(history_intent: Dict[str, Any], candidates: List[Dict[str, Any]]) -> bool:
    relation_kind = str(history_intent.get("relation_kind") or "")
    if relation_kind not in {"default_difc_application", "jurisdiction_opt_in"} and not history_intent.get(
        "is_governing_law_question"
    ):
        return False

    source_of_law_tokens = (
        "difc",
        "governing law",
        "applicable law",
        "jurisdiction",
        "difc courts",
        "opt in",
        "opt-in",
    )
    for candidate in candidates:
        text = _candidate_text(candidate).lower()
        if any(token in text for token in source_of_law_tokens):
            return False
    return True


def _solve_boolean(question_text: str, candidates: List[Dict[str, Any]], history_intent: Dict[str, Any]) -> DeterministicSolveResult:
    relation_kind = str(history_intent.get("relation_kind") or "")
    matched: List[int] = []
    values: List[bool] = []
    for index, candidate in enumerate(candidates):
        text = _candidate_text(candidate)
        if not text:
            continue

        if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from"} and (
            "precise calendar date" in question_text.lower() or "calendar date" in question_text.lower()
        ):
            date_values = _extract_candidate_dates(candidate, relation_kind)
            if date_values:
                values.append(True)
                matched.append(index)
                continue

        if _NEGATIVE_BOOLEAN_PATTERN.search(text):
            values.append(False)
            matched.append(index)
            continue
        if _POSITIVE_BOOLEAN_PATTERN.search(text):
            values.append(True)
            matched.append(index)
            continue

    unique = _ordered_unique(values)
    if len(unique) == 1:
        return _result(
            answer=unique[0],
            abstained=False,
            confidence=0.89,
            answer_type="boolean",
            route_name="history_lineage",
            path="history_boolean_evidence",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )
    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="boolean",
        route_name="history_lineage",
        path="history_boolean_abstain_unresolved",
        candidate_count=len(candidates),
        matched_candidate_indices=matched,
        values_considered=unique,
        history_intent=history_intent,
    )


def _solve_date(question_text: str, candidates: List[Dict[str, Any]], history_intent: Dict[str, Any]) -> DeterministicSolveResult:
    relation_kind = str(history_intent.get("relation_kind") or "")
    matched: List[int] = []
    values: List[str] = []

    for index, candidate in enumerate(candidates):
        if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from"}:
            if not _candidate_matches_notice_anchor(candidate, history_intent):
                continue
        if relation_kind in {"amended_by", "amends", "repealed_by", "repeals", "superseded_by", "supersedes", "enacted_on"}:
            if not _candidate_matches_law_anchor(candidate, history_intent):
                continue
        date_values = _extract_candidate_dates(candidate, relation_kind)
        if not date_values:
            continue
        values.extend(date_values)
        matched.append(index)

    unique = _ordered_unique(values)
    if len(unique) == 1:
        return _result(
            answer=unique[0],
            abstained=False,
            confidence=0.95,
            answer_type="date",
            route_name="history_lineage",
            path="history_date_evidence_value",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    if len(unique) > 1 and any(token in question_text.lower() for token in ("latest", "most recent")):
        latest = sorted(unique)[-1]
        return _result(
            answer=latest,
            abstained=False,
            confidence=0.91,
            answer_type="date",
            route_name="history_lineage",
            path="history_date_latest",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="date",
        route_name="history_lineage",
        path="history_date_abstain_conflict_or_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=matched,
        values_considered=unique,
        history_intent=history_intent,
    )


def _solve_number(question_text: str, candidates: List[Dict[str, Any]], history_intent: Dict[str, Any]) -> DeterministicSolveResult:
    lower = question_text.lower()
    relation_kind = str(history_intent.get("relation_kind") or "")
    matched: List[int] = []
    values: List[int | float] = []

    prefer_law_number = any(token in lower for token in ("law number", "latest difc law number", "notice number"))
    prefer_year = "year" in lower

    for index, candidate in enumerate(candidates):
        projection = _candidate_projection(candidate)
        candidate_values: List[Any] = []

        if prefer_law_number:
            candidate_values.extend(
                [
                    projection.get("law_number"),
                    projection.get("notice_number"),
                    projection.get("regulation_number"),
                ]
            )
        if prefer_year:
            candidate_values.extend(
                [
                    projection.get("law_year"),
                    projection.get("notice_year"),
                    projection.get("regulation_year"),
                ]
            )
        if relation_kind in {"current_version", "previous_version"}:
            candidate_values.extend([projection.get("version_sequence")])

        if not candidate_values:
            candidate_values.extend(_NUMBER_TOKEN_PATTERN.findall(_candidate_text(candidate)))

        normalized = [_normalize_number(item) for item in candidate_values]
        normalized = [item for item in normalized if item is not None]
        if not normalized:
            continue
        values.extend(normalized)
        matched.append(index)

    unique = _ordered_unique(values)
    if not unique:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type="number",
            route_name="history_lineage",
            path="history_number_abstain_missing",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    if "latest" in lower:
        numeric = sorted(float(value) for value in unique)
        latest = int(numeric[-1]) if numeric[-1].is_integer() else numeric[-1]
        return _result(
            answer=latest,
            abstained=False,
            confidence=0.92,
            answer_type="number",
            route_name="history_lineage",
            path="history_number_latest",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    if len(unique) == 1:
        return _result(
            answer=unique[0],
            abstained=False,
            confidence=0.93,
            answer_type="number",
            route_name="history_lineage",
            path="history_number_evidence_value",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="number",
        route_name="history_lineage",
        path="history_number_abstain_conflict",
        candidate_count=len(candidates),
        matched_candidate_indices=matched,
        values_considered=unique,
        history_intent=history_intent,
    )


def _solve_name(question_text: str, candidates: List[Dict[str, Any]], history_intent: Dict[str, Any]) -> DeterministicSolveResult:
    relation_kind = str(history_intent.get("relation_kind") or "")
    lower = question_text.lower()
    matched: List[int] = []
    values: List[str] = []

    for index, candidate in enumerate(candidates):
        if relation_kind in {"amended_by", "amends", "repealed_by", "repeals", "superseded_by", "supersedes"}:
            if not _candidate_matches_law_anchor(candidate, history_intent):
                continue
        if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from"}:
            if not _candidate_matches_notice_anchor(candidate, history_intent):
                continue
        projection = _candidate_projection(candidate)
        if relation_kind == "current_version" and not bool(projection.get("is_current_version")):
            continue
        if relation_kind == "previous_version" and bool(projection.get("is_current_version")):
            continue

        names = _extract_relation_names(candidate, relation_kind)
        if not names:
            continue
        values.extend(names)
        matched.append(index)

    unique = _ordered_unique(values)
    if len(unique) == 1:
        return _result(
            answer=unique[0],
            abstained=False,
            confidence=0.9,
            answer_type="name",
            route_name="history_lineage",
            path="history_name_evidence",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    if unique and "full title" in lower:
        chosen = max(unique, key=len)
        return _result(
            answer=chosen,
            abstained=False,
            confidence=0.86,
            answer_type="name",
            route_name="history_lineage",
            path="history_name_title_preferred",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="name",
        route_name="history_lineage",
        path="history_name_abstain_unresolved",
        candidate_count=len(candidates),
        matched_candidate_indices=matched,
        values_considered=unique,
        history_intent=history_intent,
    )


def _solve_names(candidates: List[Dict[str, Any]], history_intent: Dict[str, Any]) -> DeterministicSolveResult:
    relation_kind = str(history_intent.get("relation_kind") or "")
    matched: List[int] = []
    values: List[str] = []

    for index, candidate in enumerate(candidates):
        names = _extract_relation_names(candidate, relation_kind)
        if not names:
            continue
        values.extend(names)
        matched.append(index)

    unique = _ordered_unique(values)
    if unique:
        return _result(
            answer=unique,
            abstained=False,
            confidence=0.9,
            answer_type="names",
            route_name="history_lineage",
            path="history_names_evidence",
            candidate_count=len(candidates),
            matched_candidate_indices=matched,
            values_considered=unique,
            history_intent=history_intent,
        )

    return _result(
        answer=None,
        abstained=True,
        confidence=0.0,
        answer_type="names",
        route_name="history_lineage",
        path="history_names_abstain_missing",
        candidate_count=len(candidates),
        matched_candidate_indices=matched,
        values_considered=unique,
        history_intent=history_intent,
    )


def _compact_free_text_extract(raw_text: str) -> str:
    text = _collapse_ws(raw_text)
    if not text:
        return ""
    sentences = re.split(r"(?<=[\.!?])\s+", text)
    sentence = sentences[0].strip() if sentences else text
    if sentence.lower().endswith("no.") and len(sentences) > 1:
        sentence = f"{sentence} {sentences[1].strip()}".strip()
    if len(sentence) < 24 and ";" in text:
        sentence = text.split(";", 1)[0].strip()
    if len(sentence) <= 280:
        return sentence
    return sentence[:277].rstrip() + "..."


def _solve_free_text(
    question_text: str,
    candidates: List[Dict[str, Any]],
    history_intent: Dict[str, Any],
) -> DeterministicSolveResult:
    relation_kind = str(history_intent.get("relation_kind") or "")
    extracts: List[Tuple[int, str]] = []
    for index, candidate in enumerate(candidates):
        if relation_kind in {"notice_mediated_commencement", "commenced_on", "effective_from"}:
            if not _candidate_matches_notice_anchor(candidate, history_intent):
                continue
        if relation_kind in {"amended_by", "amends", "repealed_by", "repeals", "superseded_by", "supersedes"}:
            if not _candidate_matches_law_anchor(candidate, history_intent):
                continue
        text = _candidate_text(candidate)
        if not text:
            continue
        extract = _compact_free_text_extract(text)
        if not extract:
            continue
        extracts.append((index, extract))

    if not extracts:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type="free_text",
            route_name="history_lineage",
            path="history_free_text_abstain_missing_evidence",
            candidate_count=len(candidates),
            matched_candidate_indices=[],
            values_considered=[],
            history_intent=history_intent,
        )

    lower = question_text.lower()
    preferred = extracts[0]
    if relation_kind:
        for index, extract in extracts:
            text = extract.lower()
            if relation_kind.startswith("amend") and "amend" in text:
                preferred = (index, extract)
                break
            if relation_kind.startswith("repeal") and "repeal" in text:
                preferred = (index, extract)
                break
            if relation_kind.startswith("supersed") and "supersed" in text:
                preferred = (index, extract)
                break
            if relation_kind in {"enacted_on", "commenced_on", "effective_from"} and any(
                marker in text for marker in ("enact", "commenc", "effective", "in force")
            ):
                preferred = (index, extract)
                break

    if any(marker in lower for marker in ("governing law", "jurisdiction", "difc courts", "opt in", "opt-in")):
        for index, extract in extracts:
            lowered_extract = extract.lower()
            if any(marker in lowered_extract for marker in ("governing law", "jurisdiction", "difc courts", "difc")):
                preferred = (index, extract)
                break

    selected_index, selected_text = preferred
    return _result(
        answer=selected_text,
        abstained=False,
        confidence=0.72,
        answer_type="free_text",
        route_name="history_lineage",
        path="history_free_text_evidence_extract",
        candidate_count=len(candidates),
        matched_candidate_indices=[selected_index],
        values_considered=[extract for _, extract in extracts[:4]],
        history_intent=history_intent,
    )


def solve_law_history_deterministic(
    question: Dict[str, Any],
    route_name: str,
    candidates: List[Dict[str, Any]] | None = None,
    *,
    history_intent: Dict[str, Any] | None = None,
) -> DeterministicSolveResult:
    question_text = _collapse_ws(question.get("question", ""))
    answer_type = str(question.get("answer_type", "free_text"))
    candidate_rows = candidates or []
    intent = history_intent or resolve_law_history_lookup_intent(question_text)

    if not question_text:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="history_abstain_empty_question",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            history_intent=intent,
        )

    if _source_of_law_guardrail(intent, candidate_rows):
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="history_abstain_source_of_law_guardrail",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            history_intent=intent,
        )

    if answer_type == "boolean":
        return _solve_boolean(question_text, candidate_rows, intent)
    if answer_type == "date":
        return _solve_date(question_text, candidate_rows, intent)
    if answer_type == "number":
        return _solve_number(question_text, candidate_rows, intent)
    if answer_type == "name":
        return _solve_name(question_text, candidate_rows, intent)
    if answer_type == "names":
        return _solve_names(candidate_rows, intent)
    return _solve_free_text(question_text, candidate_rows, intent)
