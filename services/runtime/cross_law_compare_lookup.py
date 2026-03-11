"""Deterministic cross-law compare intent resolution and solver utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Tuple

from services.runtime.law_article_lookup import resolve_law_article_lookup_intent
from services.runtime.law_history_lookup import (
    resolve_law_history_lookup_intent,
    solve_law_history_deterministic,
)

RESOLUTION_VERSION = "cross_law_compare_resolution_v1"
HINTS_VERSION = "cross_law_compare_retrieval_hints_v1"
SOLVER_VERSION = "cross_law_compare_deterministic_solver_v1"

_HISTORY_BACKED_DIMENSIONS = {
    "enactment_date",
    "commencement_date",
}

_WHITESPACE_PATTERN = re.compile(r"\s+")

_INSTRUMENT_WITH_NUMBER_PATTERN = re.compile(
    r"\b(?:(?P<title>[A-Z][A-Za-z0-9&'().,\- ]+?)\s+)?"
    r"(?P<kind>Law|Regulation|Regulations|Notice)\s+"
    r"(?:No\.?|Number)?\s*(?P<number>\d{1,4})(?:\s+of\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
_TITLE_ONLY_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&'().,\- ]+?\s(?:Law|Regulation|Regulations|Notice))\b",
    re.IGNORECASE,
)
_NOTICE_ONLY_PATTERN = re.compile(
    r"\b(?:Commencement|Enactment)?\s*Notice\s+(?:No\.?|Number)?\s*(\d{1,4})(?:\s+of\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_DATE_TOKEN_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"
)
_NUMBER_TOKEN_PATTERN = re.compile(r"[-+]?(?:\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.\d+)?")

_COMPARE_TOKENS = (
    "compare",
    "comparison",
    "difference",
    "different",
    "versus",
    "vs",
    "same",
    "common",
    "earlier",
    "later",
)


@dataclass(frozen=True)
class DeterministicSolveResult:
    answer: Any
    abstained: bool
    confidence: float
    trace: Dict[str, Any] = field(default_factory=dict)


def _collapse_ws(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "")).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _uniq(items: List[Any]) -> List[str]:
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


def _normalize_date_token(raw: Any) -> str | None:
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
    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            return datetime.strptime(normalized, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_number(raw: Any) -> int | float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else raw
    match = _NUMBER_TOKEN_PATTERN.search(_collapse_ws(raw))
    if not match:
        return None
    token = match.group(0).replace(",", "").replace(" ", "")
    try:
        number = Decimal(token)
    except InvalidOperation:
        return None
    if number == number.to_integral():
        return int(number)
    return float(number.normalize())


def _clean_instrument_title(raw_title: Any) -> str:
    title = _collapse_ws(raw_title)
    if not title:
        return ""
    title = re.sub(
        r"^(?:what|which|was|is|are|do|does|did|how|when|can|could|would|should)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"^(?:the|a|an)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^(?:and|or)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+[\?\.!;,]+$", "", title)
    return _collapse_ws(title)


def _normalized_instrument_type(raw_kind: Any) -> str:
    value = _collapse_ws(raw_kind).lower()
    if value in {"law", "laws"}:
        return "law"
    if value in {"regulation", "regulations"}:
        return "regulation"
    if "notice" in value:
        return "enactment_notice"
    return "other"


def _instrument_identifier(
    *,
    instrument_type: str,
    title: str | None,
    number: str | None,
    year: str | None,
) -> str:
    clean_title = _clean_instrument_title(title)
    if instrument_type == "enactment_notice":
        if number and year:
            return f"notice_no_{number}_of_{year}"
        if number:
            return f"notice_no_{number}"
    if instrument_type == "regulation":
        if number and year:
            return f"regulation_no_{number}_of_{year}"
        if number:
            return f"regulation_no_{number}"
    if instrument_type == "law":
        if number and year:
            return f"law_no_{number}_of_{year}"
        if number:
            return f"law_no_{number}"
    if clean_title and number and year:
        return f"{_slug(clean_title)}_no_{number}_of_{year}"
    if clean_title and number:
        return f"{_slug(clean_title)}_no_{number}"
    if clean_title and year:
        return f"{_slug(clean_title)}_{year}"
    if clean_title:
        return _slug(clean_title)
    return ""


def _extract_instrument_mentions(question_text: str, history_intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_text = _collapse_ws(question_text)
    mentions: List[Dict[str, Any]] = []

    for match in _INSTRUMENT_WITH_NUMBER_PATTERN.finditer(raw_text):
        title = _clean_instrument_title(match.group("title"))
        instrument_type = _normalized_instrument_type(match.group("kind"))
        number = _collapse_ws(match.group("number")) or None
        year = _collapse_ws(match.group("year")) or None
        identifier = _instrument_identifier(
            instrument_type=instrument_type,
            title=title or None,
            number=number,
            year=year,
        )
        if not identifier:
            continue
        mentions.append(
            {
                "instrument_identifier": identifier,
                "instrument_type": instrument_type,
                "title": title or None,
                "number": number,
                "year": year,
            }
        )

    for match in _NOTICE_ONLY_PATTERN.finditer(raw_text):
        number = _collapse_ws(match.group(1) or "") or None
        year = _collapse_ws(match.group(2) or "") or None
        identifier = _instrument_identifier(
            instrument_type="enactment_notice",
            title="Commencement Notice",
            number=number,
            year=year,
        )
        if not identifier:
            continue
        mentions.append(
            {
                "instrument_identifier": identifier,
                "instrument_type": "enactment_notice",
                "title": "Commencement Notice",
                "number": number,
                "year": year,
            }
        )

    for match in _TITLE_ONLY_PATTERN.finditer(raw_text):
        title = _clean_instrument_title(match.group(1))
        if not title:
            continue
        instrument_type = "law" if "law" in title.lower() else "regulation" if "regulation" in title.lower() else "other"
        identifier = _instrument_identifier(
            instrument_type=instrument_type,
            title=title,
            number=None,
            year=None,
        )
        if not identifier:
            continue
        mentions.append(
            {
                "instrument_identifier": identifier,
                "instrument_type": instrument_type,
                "title": title,
                "number": None,
                "year": None,
            }
        )

    history_laws = history_intent.get("law_mentions", []) if isinstance(history_intent.get("law_mentions"), list) else []
    for item in history_laws:
        if not isinstance(item, dict):
            continue
        title = _clean_instrument_title(item.get("title"))
        number = _collapse_ws(item.get("law_number")) or None
        year = _collapse_ws(item.get("law_year")) or None
        instrument_type = "regulation" if (title and "regulation" in title.lower()) else "law"
        identifier = _instrument_identifier(
            instrument_type=instrument_type,
            title=title or None,
            number=number,
            year=year,
        )
        if not identifier:
            continue
        mentions.append(
            {
                "instrument_identifier": identifier,
                "instrument_type": instrument_type,
                "title": title or None,
                "number": number,
                "year": year,
            }
        )

    history_notices = history_intent.get("notice_mentions", []) if isinstance(history_intent.get("notice_mentions"), list) else []
    for item in history_notices:
        if not isinstance(item, dict):
            continue
        number = _collapse_ws(item.get("notice_number")) or None
        year = _collapse_ws(item.get("notice_year")) or None
        identifier = _instrument_identifier(
            instrument_type="enactment_notice",
            title="Enactment Notice",
            number=number,
            year=year,
        )
        if not identifier:
            continue
        mentions.append(
            {
                "instrument_identifier": identifier,
                "instrument_type": "enactment_notice",
                "title": "Enactment Notice",
                "number": number,
                "year": year,
            }
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in mentions:
        key = (
            str(item.get("instrument_identifier") or ""),
            str(item.get("instrument_type") or ""),
            str(item.get("number") or ""),
            str(item.get("year") or ""),
            str(item.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:12]


def _detect_compare_dimensions(question_text: str) -> List[str]:
    lowered = _collapse_ws(question_text).lower()
    dimensions: List[str] = []

    if any(
        marker in lowered
        for marker in (
            "enacted",
            "enactment",
            "same year",
            "earlier in the year",
            "earlier than",
            "later than",
            "same day",
            "same date",
        )
    ):
        dimensions.append("enactment_date")

    if any(
        marker in lowered
        for marker in (
            "commencement",
            "came into force",
            "come into force",
            "common commencement date",
            "effective date",
            "effective from",
            "in force",
        )
    ):
        dimensions.append("commencement_date")

    if any(marker in lowered for marker in ("administer", "administering authority", "issuing authority", "authority")):
        dimensions.append("administering_authority")

    if any(marker in lowered for marker in ("full title", "citation title", "title of", "titles of", "what is the title")):
        dimensions.append("title_full")

    if any(marker in lowered for marker in ("definition", "define", "scope", "interpretation", "interpretative")):
        dimensions.append("definition_or_scope")

    if any(marker in lowered for marker in ("penalty", "penalties", "sanction", "sanctions", "fine", "offense")):
        dimensions.append("penalties_or_sanctions")

    if "schedule" in lowered:
        dimensions.append("schedule_presence")

    if any(marker in lowered for marker in ("mention", "contains", "contain", "include", "common elements", "same term", "same entity", "both")):
        dimensions.append("feature_presence")

    if re.search(r"\bwhich\s+laws?\b", lowered) or re.search(r"\blaws?\s+(?:are|that)\b", lowered):
        dimensions.append("condition_satisfaction")

    if not dimensions and any(token in lowered for token in _COMPARE_TOKENS):
        dimensions.append("title_full")

    return _ordered_unique(dimensions)


def _detect_compare_operator(
    question_text: str,
    compare_dimensions: List[str],
    *,
    open_set_condition_query: bool,
) -> str:
    lowered = _collapse_ws(question_text).lower()
    if open_set_condition_query or "condition_satisfaction" in compare_dimensions:
        return "which_satisfy_condition"
    if any(marker in lowered for marker in ("earlier", "before")):
        return "earlier_than"
    if any(marker in lowered for marker in ("later", "after")):
        return "later_than"
    if any(marker in lowered for marker in ("same", "common", "both")):
        return "same_or_common"
    if any(marker in lowered for marker in ("mention", "contains", "contain", "include")):
        return "both_contain_feature"
    if any(marker in lowered for marker in ("difference", "compare", "versus", "vs")):
        return "contrast"
    return "unknown"


def _detect_temporal_focus(question_text: str, compare_dimensions: List[str]) -> str:
    lowered = _collapse_ws(question_text).lower()
    if any(token in lowered for token in ("latest", "current", "currently in force")):
        return "current"
    if any(token in lowered for token in ("historical", "previous", "earliest", "first")):
        return "historical"
    if any(dim in {"enactment_date", "commencement_date"} for dim in compare_dimensions):
        return "historical"
    return "none"


def _is_open_set_condition_query(question_text: str) -> bool:
    lowered = _collapse_ws(question_text).lower()
    return bool(
        re.search(r"\bwhich\s+laws?\b", lowered)
        or re.search(r"\blaws?\s+(?:are|that)\b", lowered)
        or "among these laws" in lowered
    )


def _history_backed_dimensions(compare_dimensions: List[str]) -> List[str]:
    return [dim for dim in compare_dimensions if dim in _HISTORY_BACKED_DIMENSIONS]


def resolve_cross_law_compare_intent(question_text: str) -> Dict[str, Any]:
    raw_text = _collapse_ws(question_text)
    lowered = raw_text.lower()

    history_intent = resolve_law_history_lookup_intent(raw_text)
    article_intent = resolve_law_article_lookup_intent(raw_text)

    instrument_mentions = _extract_instrument_mentions(raw_text, history_intent)
    instrument_identifiers = [
        str(item.get("instrument_identifier") or "")
        for item in instrument_mentions
        if str(item.get("instrument_identifier") or "").strip()
    ]
    instrument_types = _uniq(item.get("instrument_type") for item in instrument_mentions if item.get("instrument_type"))

    compare_dimensions = _detect_compare_dimensions(raw_text)
    open_set_condition_query = _is_open_set_condition_query(raw_text)
    compare_operator = _detect_compare_operator(
        raw_text,
        compare_dimensions,
        open_set_condition_query=open_set_condition_query,
    )
    temporal_focus = _detect_temporal_focus(raw_text, compare_dimensions)

    compare_framing = bool(any(token in lowered for token in _COMPARE_TOKENS) or open_set_condition_query)
    has_explicit_pair = len(instrument_identifiers) >= 2
    structural_resolution_required = bool(compare_framing and not has_explicit_pair and not open_set_condition_query)

    confidence = 0.0
    if compare_dimensions:
        confidence += 0.38
    if compare_operator != "unknown":
        confidence += 0.18
    if has_explicit_pair:
        confidence += 0.28
    if open_set_condition_query:
        confidence += 0.16
    if instrument_types:
        confidence += 0.08
    if temporal_focus != "none":
        confidence += 0.06
    resolution_confidence = round(min(0.99, confidence), 2)

    left_id = instrument_identifiers[0] if len(instrument_identifiers) >= 1 else None
    right_id = instrument_identifiers[1] if len(instrument_identifiers) >= 2 else None

    return {
        "resolver_version": RESOLUTION_VERSION,
        "left_instrument_identifier": left_id,
        "right_instrument_identifier": right_id,
        "instrument_identifiers": instrument_identifiers,
        "instrument_types": instrument_types,
        "compare_dimensions": compare_dimensions,
        "compare_operator": compare_operator,
        "temporal_focus": temporal_focus,
        "resolution_confidence": resolution_confidence,
        "structural_resolution_required": structural_resolution_required,
        "open_set_condition_query": open_set_condition_query,
        "has_explicit_pair": has_explicit_pair,
        "history_backed_dimensions": _history_backed_dimensions(compare_dimensions),
        "instrument_anchors": instrument_mentions,
        "history_intent_seed": history_intent,
        "article_lookup_intent": article_intent,
    }


def build_cross_law_compare_retrieval_hints(
    question_text: str,
    compare_intent: Dict[str, Any],
) -> Dict[str, Any]:
    dimensions = compare_intent.get("compare_dimensions", []) if isinstance(compare_intent.get("compare_dimensions"), list) else []
    operator = str(compare_intent.get("compare_operator") or "")
    temporal_focus = str(compare_intent.get("temporal_focus") or "none")

    doc_type_priority = ["law", "regulation", "enactment_notice"]
    if "commencement_date" in dimensions:
        doc_type_priority = ["enactment_notice", "law", "regulation"]
    elif "penalties_or_sanctions" in dimensions:
        doc_type_priority = ["regulation", "law", "enactment_notice"]

    expansions: List[str] = []
    dimension_terms = {
        "enactment_date": ["enacted", "enactment date"],
        "commencement_date": ["commencement", "came into force", "effective date", "enactment notice"],
        "administering_authority": ["administering authority", "issued by"],
        "title_full": ["title", "citation title"],
        "definition_or_scope": ["definition", "scope", "interpretation"],
        "penalties_or_sanctions": ["penalty", "sanction", "fine"],
        "schedule_presence": ["schedule", "schedule number"],
        "feature_presence": ["contains", "mentions", "common elements"],
        "condition_satisfaction": ["which laws", "satisfy condition"],
    }
    for dim in dimensions:
        expansions.extend(dimension_terms.get(dim, []))

    for anchor in compare_intent.get("instrument_anchors", []) if isinstance(compare_intent.get("instrument_anchors"), list) else []:
        if not isinstance(anchor, dict):
            continue
        for field in ("title", "number", "year", "instrument_identifier"):
            token = _collapse_ws(anchor.get(field))
            if token:
                expansions.append(token)

    if operator:
        expansions.append(operator.replace("_", " "))

    expanded_query = _collapse_ws(" ".join([question_text, *expansions]))

    requires_notice_expansion = bool("commencement_date" in dimensions)
    requires_lineage_expansion = bool(
        temporal_focus == "historical"
        or any(dim in _HISTORY_BACKED_DIMENSIONS for dim in dimensions)
        or any(token in _collapse_ws(question_text).lower() for token in ("amended", "repealed", "superseded"))
    )

    return {
        "hint_version": HINTS_VERSION,
        "doc_type_priority": list(dict.fromkeys(doc_type_priority)),
        "expanded_query": expanded_query or question_text,
        "expansion_terms": _uniq(expansions),
        "requires_notice_expansion": requires_notice_expansion,
        "requires_lineage_expansion": requires_lineage_expansion,
        "instrument_anchors": compare_intent.get("instrument_anchors", []),
        "compare_dimensions": dimensions,
        "compare_operator": operator,
        "temporal_focus": temporal_focus,
        "open_set_condition_query": bool(compare_intent.get("open_set_condition_query")),
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
    return _collapse_ws(
        " ".join(
            [
                str(paragraph.get("text", "")),
                str(projection.get("text_clean", "")),
                str(projection.get("retrieval_text", "")),
            ]
        )
    )


def _candidate_title(candidate: Dict[str, Any]) -> str:
    projection = _candidate_projection(candidate)
    return _collapse_ws(
        projection.get("law_title")
        or projection.get("citation_title")
        or projection.get("title")
        or projection.get("document_title")
        or ""
    )


def _candidate_instrument_identifier(candidate: Dict[str, Any]) -> str:
    projection = _candidate_projection(candidate)
    doc_type = _normalized_instrument_type(projection.get("doc_type"))
    number = _collapse_ws(
        projection.get("law_number")
        or projection.get("regulation_number")
        or projection.get("notice_number")
    )
    year = _collapse_ws(
        projection.get("law_year")
        or projection.get("regulation_year")
        or projection.get("notice_year")
    )
    title = _candidate_title(candidate)
    return _instrument_identifier(
        instrument_type=doc_type,
        title=title or None,
        number=number or None,
        year=year or None,
    )


def _anchor_matches_candidate(anchor: Dict[str, Any], candidate: Dict[str, Any]) -> int:
    projection = _candidate_projection(candidate)
    score = 0
    anchor_type = _normalized_instrument_type(anchor.get("instrument_type"))
    candidate_type = _normalized_instrument_type(projection.get("doc_type"))
    if anchor_type != "other" and anchor_type == candidate_type:
        score += 2

    anchor_number = _collapse_ws(anchor.get("number"))
    anchor_year = _collapse_ws(anchor.get("year"))
    candidate_number = _collapse_ws(
        projection.get("law_number")
        or projection.get("regulation_number")
        or projection.get("notice_number")
    )
    candidate_year = _collapse_ws(
        projection.get("law_year")
        or projection.get("regulation_year")
        or projection.get("notice_year")
    )
    if anchor_number and candidate_number and anchor_number == candidate_number:
        score += 3
    if anchor_year and candidate_year and anchor_year == candidate_year:
        score += 2

    anchor_title = _clean_instrument_title(anchor.get("title"))
    if anchor_title:
        title_lower = _candidate_title(candidate).lower()
        text_lower = _candidate_text(candidate).lower()
        needle = anchor_title.lower()
        if needle and (needle in title_lower or needle in text_lower):
            score += 2

    anchor_identifier = _collapse_ws(anchor.get("instrument_identifier"))
    candidate_identifier = _candidate_instrument_identifier(candidate)
    if anchor_identifier and candidate_identifier and anchor_identifier == candidate_identifier:
        score += 4

    return score


def annotate_cross_law_candidate_instruments(
    candidates: List[Dict[str, Any]],
    compare_intent: Dict[str, Any],
) -> Dict[str, int]:
    anchors = [
        item
        for item in (compare_intent.get("instrument_anchors", []) if isinstance(compare_intent.get("instrument_anchors"), list) else [])
        if isinstance(item, dict)
    ]

    counts: Dict[str, int] = {}
    for candidate in candidates:
        chosen_identifier = ""
        chosen_label = ""

        if anchors:
            scored = [
                (_anchor_matches_candidate(anchor, candidate), anchor)
                for anchor in anchors
            ]
            scored.sort(key=lambda row: row[0], reverse=True)
            if scored and scored[0][0] > 0:
                best_anchor = scored[0][1]
                chosen_identifier = str(best_anchor.get("instrument_identifier") or "")
                chosen_label = str(best_anchor.get("title") or best_anchor.get("instrument_identifier") or "")

        if not chosen_identifier:
            chosen_identifier = _candidate_instrument_identifier(candidate)
            chosen_label = _candidate_title(candidate) or chosen_identifier

        candidate["compare_instrument_identifier"] = chosen_identifier
        candidate["compare_instrument_label"] = chosen_label
        if chosen_identifier:
            counts[chosen_identifier] = counts.get(chosen_identifier, 0) + 1

    return counts


def _extract_authority_value(candidate: Dict[str, Any]) -> str | None:
    projection = _candidate_projection(candidate)
    for key in ("administering_authority", "issuing_authority"):
        value = _collapse_ws(projection.get(key))
        if value:
            return value
    text = _candidate_text(candidate)
    match = re.search(
        r"(?:administered\s+by|issued\s+by|authority\s+is|authority\s*:)\s+([A-Za-z][A-Za-z0-9 ,&\-]{2,120})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _collapse_ws(match.group(1).rstrip(".;,"))
    return None


def _extract_title_value(candidate: Dict[str, Any]) -> str | None:
    title = _candidate_title(candidate)
    return title or None


def _extract_schedule_presence(candidate_rows: List[Dict[str, Any]]) -> bool | None:
    if not candidate_rows:
        return None
    for candidate in candidate_rows:
        projection = _candidate_projection(candidate)
        if _collapse_ws(projection.get("schedule_number")):
            return True
        if "schedule" in _candidate_text(candidate).lower():
            return True
    return False


def _extract_definition_scope(candidate_rows: List[Dict[str, Any]]) -> str | None:
    for candidate in candidate_rows:
        text = _candidate_text(candidate)
        if not text:
            continue
        sentence_split = re.split(r"(?<=[\.!?])\s+", text)
        for sentence in sentence_split:
            lowered = sentence.lower()
            if any(token in lowered for token in ("definition", "means", "scope", "interpretation")):
                compact = _collapse_ws(sentence)
                if compact:
                    return compact[:280]
    return None


def _extract_penalty_or_sanction(candidate_rows: List[Dict[str, Any]]) -> int | float | str | None:
    for candidate in candidate_rows:
        projection = _candidate_projection(candidate)
        money_values = projection.get("money_values", []) if isinstance(projection.get("money_values"), list) else []
        for raw_value in money_values:
            normalized = _normalize_number(raw_value)
            if normalized is not None:
                return normalized
        text = _candidate_text(candidate)
        if any(token in text.lower() for token in ("penalty", "sanction", "fine", "offense")):
            sentence_split = re.split(r"(?<=[\.!?])\s+", text)
            for sentence in sentence_split:
                if any(token in sentence.lower() for token in ("penalty", "sanction", "fine", "offense")):
                    compact = _collapse_ws(sentence)
                    if compact:
                        return compact[:280]
    return None


def _feature_term_from_question(question_text: str) -> str:
    quote_match = re.search(r"['\"]([^'\"]{2,80})['\"]", question_text)
    if quote_match:
        return _collapse_ws(quote_match.group(1)).lower()
    lowered = _collapse_ws(question_text).lower()
    if "interpretative provisions" in lowered:
        return "interpretative provisions"
    if "ruler of dubai" in lowered:
        return "ruler of dubai"
    return ""


def _extract_feature_presence(candidate_rows: List[Dict[str, Any]], question_text: str) -> bool | None:
    if not candidate_rows:
        return None
    feature_term = _feature_term_from_question(question_text)
    if not feature_term:
        return None
    for candidate in candidate_rows:
        if feature_term in _candidate_text(candidate).lower():
            return True
    return False


def _extract_dates_from_candidates(candidate_rows: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for candidate in candidate_rows:
        projection = _candidate_projection(candidate)
        paragraph = _candidate_paragraph(candidate)
        raw_values: List[Any] = []
        for key in ("commencement_date", "effective_start_date", "decision_date", "dates"):
            value = projection.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif value:
                raw_values.append(value)
        paragraph_dates = paragraph.get("dates")
        if isinstance(paragraph_dates, list):
            raw_values.extend(paragraph_dates)
        if not raw_values:
            raw_values.extend(_DATE_TOKEN_PATTERN.findall(_candidate_text(candidate)))
        normalized = [_normalize_date_token(item) for item in raw_values]
        values.extend([item for item in normalized if item])
    return _ordered_unique(values)


def _extract_condition_targets(question_text: str) -> Dict[str, Any]:
    lowered = _collapse_ws(question_text).lower()
    condition: Dict[str, Any] = {}

    year_match = re.search(r"enacted\s+in\s+((?:19|20)\d{2})", lowered)
    if year_match:
        condition["enacted_year"] = year_match.group(1)

    authority_match = re.search(
        r"administered\s+by\s+(?:the\s+)?([A-Za-z][A-Za-z0-9\- ]{1,80})",
        question_text,
        flags=re.IGNORECASE,
    )
    if authority_match:
        condition["authority"] = _collapse_ws(authority_match.group(1)).lower()
    elif "administered by the registrar" in lowered or "administers the" in lowered and "registrar" in lowered:
        condition["authority"] = "registrar"

    quoted = _feature_term_from_question(question_text)
    if quoted:
        condition["feature_term"] = quoted

    if "schedule" in lowered:
        condition["requires_schedule"] = True

    return condition


def _instrument_label(anchor: Dict[str, Any]) -> str:
    title = _collapse_ws(anchor.get("title"))
    if title:
        return title
    identifier = _collapse_ws(anchor.get("instrument_identifier"))
    if identifier:
        return identifier
    number = _collapse_ws(anchor.get("number"))
    year = _collapse_ws(anchor.get("year"))
    if number and year:
        return f"Law No. {number} of {year}"
    return "the instrument"


def _history_date_for_instrument(
    *,
    relation_kind: str,
    anchor: Dict[str, Any],
    candidate_rows: List[Dict[str, Any]],
) -> Tuple[str | None, Dict[str, Any]]:
    label = _instrument_label(anchor)
    question_text = (
        f"On what date was {label} enacted?"
        if relation_kind == "enacted_on"
        else f"When did {label} come into force?"
    )
    sub_question = {
        "question": question_text,
        "answer_type": "date",
    }
    history_intent = resolve_law_history_lookup_intent(question_text)
    history_intent["relation_kind"] = relation_kind
    history_intent["requires_structural_resolution"] = False
    history_intent["has_explicit_anchor"] = True

    number = _collapse_ws(anchor.get("number"))
    year = _collapse_ws(anchor.get("year"))
    anchor_type = _normalized_instrument_type(anchor.get("instrument_type"))
    if anchor_type == "enactment_notice":
        history_intent["target_notice_number"] = number or None
        history_intent["target_notice_year"] = year or None
    else:
        history_intent["target_law_number"] = number or None
        history_intent["target_law_year"] = year or None

    result = solve_law_history_deterministic(
        sub_question,
        "history_lineage",
        candidate_rows,
        history_intent=history_intent,
    )
    value = None if result.abstained else _normalize_date_token(result.answer)
    trace = {
        "history_relation_kind": relation_kind,
        "history_solver_path": str(result.trace.get("path", "")),
        "history_abstained": bool(result.abstained),
        "history_confidence": float(result.confidence),
    }
    return value, trace


def _instrument_rows_by_identifier(candidates: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidates:
        identifier = _collapse_ws(row.get("compare_instrument_identifier"))
        if not identifier:
            continue
        grouped.setdefault(identifier, []).append(row)
    return grouped


def _build_trace(
    *,
    answer_type: str,
    route_name: str,
    path: str,
    candidate_count: int,
    matched_candidate_indices: List[int],
    values_considered: List[Any],
    compare_intent: Dict[str, Any],
    dimension_trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
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
        "cross_law_compare_resolution": compare_intent,
        "cross_law_compare_dimension_trace": dimension_trace,
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
    compare_intent: Dict[str, Any],
    dimension_trace: List[Dict[str, Any]],
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
            compare_intent=compare_intent,
            dimension_trace=dimension_trace,
        ),
    )


def solve_cross_law_compare_deterministic(
    question: Dict[str, Any],
    route_name: str,
    candidates: List[Dict[str, Any]] | None = None,
    *,
    compare_intent: Dict[str, Any] | None = None,
) -> DeterministicSolveResult:
    question_text = _collapse_ws(question.get("question", ""))
    answer_type = str(question.get("answer_type", "free_text"))
    candidate_rows = candidates or []
    intent = compare_intent or resolve_cross_law_compare_intent(question_text)

    if not question_text:
        return _result(
            answer=None,
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="cross_law_abstain_empty_question",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            compare_intent=intent,
            dimension_trace=[],
        )

    if not candidate_rows:
        return _result(
            answer=None if answer_type != "free_text" else "",
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="cross_law_abstain_no_candidates",
            candidate_count=0,
            matched_candidate_indices=[],
            values_considered=[],
            compare_intent=intent,
            dimension_trace=[],
        )

    annotate_cross_law_candidate_instruments(candidate_rows, intent)
    rows_by_identifier = _instrument_rows_by_identifier(candidate_rows)

    anchor_rows = [
        item
        for item in (intent.get("instrument_anchors", []) if isinstance(intent.get("instrument_anchors"), list) else [])
        if isinstance(item, dict)
    ]
    if anchor_rows:
        anchor_order = [
            str(item.get("instrument_identifier") or "")
            for item in anchor_rows
            if str(item.get("instrument_identifier") or "").strip()
        ]
    else:
        anchor_order = sorted(rows_by_identifier.keys())

    if not anchor_order:
        anchor_order = sorted(rows_by_identifier.keys())

    compare_dimensions = (
        intent.get("compare_dimensions", [])
        if isinstance(intent.get("compare_dimensions"), list)
        else []
    )
    if not compare_dimensions:
        return _result(
            answer=None if answer_type != "free_text" else "",
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="cross_law_abstain_no_dimensions",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            compare_intent=intent,
            dimension_trace=[],
        )

    compare_operator = str(intent.get("compare_operator") or "unknown")
    open_set_condition_query = bool(intent.get("open_set_condition_query"))
    if not open_set_condition_query and len(anchor_order) < 2:
        return _result(
            answer=None if answer_type != "free_text" else "",
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="cross_law_abstain_missing_instrument_pair",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            compare_intent=intent,
            dimension_trace=[],
        )

    candidate_index_by_id = {id(row): idx for idx, row in enumerate(candidate_rows)}

    dimension_trace: List[Dict[str, Any]] = []
    value_map: Dict[str, Dict[str, Any]] = {}

    anchor_lookup = {
        str(item.get("instrument_identifier") or ""): item
        for item in anchor_rows
        if str(item.get("instrument_identifier") or "").strip()
    }

    for dimension in compare_dimensions:
        per_instrument: Dict[str, Any] = {}
        used_indices: List[int] = []

        for instrument_id in anchor_order:
            rows = rows_by_identifier.get(instrument_id, [])
            if not rows and not open_set_condition_query:
                continue

            value: Any = None
            history_trace: Dict[str, Any] = {}

            if dimension in {"enactment_date", "commencement_date"}:
                anchor = anchor_lookup.get(
                    instrument_id,
                    {
                        "instrument_identifier": instrument_id,
                        "instrument_type": "law",
                        "title": rows[0].get("compare_instrument_label") if rows else instrument_id,
                    },
                )
                relation_kind = "enacted_on" if dimension == "enactment_date" else "commenced_on"
                value, history_trace = _history_date_for_instrument(
                    relation_kind=relation_kind,
                    anchor=anchor,
                    candidate_rows=rows,
                )
                if value is None:
                    fallback_dates = _extract_dates_from_candidates(rows)
                    value = fallback_dates[0] if fallback_dates else None
            elif dimension == "administering_authority":
                for row in rows:
                    value = _extract_authority_value(row)
                    if value:
                        break
            elif dimension == "title_full":
                for row in rows:
                    value = _extract_title_value(row)
                    if value:
                        break
            elif dimension == "schedule_presence":
                value = _extract_schedule_presence(rows)
            elif dimension == "definition_or_scope":
                value = _extract_definition_scope(rows)
            elif dimension == "penalties_or_sanctions":
                value = _extract_penalty_or_sanction(rows)
            elif dimension == "feature_presence":
                value = _extract_feature_presence(rows, question_text)
            elif dimension == "condition_satisfaction":
                value = True
            else:
                for row in rows:
                    text = _candidate_text(row)
                    if text:
                        value = text[:280]
                        break

            if value is not None:
                per_instrument[instrument_id] = value
                if rows:
                    for row in rows[:2]:
                        idx = candidate_index_by_id.get(id(row))
                        if idx is not None:
                            used_indices.append(idx)

            dimension_trace.append(
                {
                    "dimension": dimension,
                    "instrument_identifier": instrument_id,
                    "value": value,
                    "evidence_candidate_indices": _ordered_unique(used_indices),
                    **history_trace,
                }
            )

        if per_instrument:
            value_map[dimension] = per_instrument

    if not value_map:
        return _result(
            answer=None if answer_type != "free_text" else "",
            abstained=True,
            confidence=0.0,
            answer_type=answer_type,
            route_name=route_name,
            path="cross_law_abstain_missing_dimension_values",
            candidate_count=len(candidate_rows),
            matched_candidate_indices=[],
            values_considered=[],
            compare_intent=intent,
            dimension_trace=dimension_trace,
        )

    primary_dimension = compare_dimensions[0]
    primary_values = value_map.get(primary_dimension, {})

    values_considered = [
        f"{instrument_id}:{value}"
        for instrument_id, value in primary_values.items()
    ]

    def _all_equal(values: List[Any]) -> bool:
        if not values:
            return False
        normalized = [str(item).strip().lower() for item in values if item is not None]
        return len(set(normalized)) == 1 if normalized else False

    answer: Any = None
    abstained = False
    confidence = 0.0
    path = "cross_law_compare_unresolved"

    if compare_operator in {"same_or_common", "both_contain_feature"}:
        value_list = [primary_values.get(instrument_id) for instrument_id in anchor_order if instrument_id in primary_values]
        if primary_dimension == "feature_presence":
            bool_values = [bool(item) for item in value_list if item is not None]
            if len(bool_values) >= 2:
                answer = all(bool_values)
                confidence = 0.9
                path = "cross_law_boolean_feature_common"
            else:
                abstained = True
                path = "cross_law_abstain_feature_missing"
        elif primary_dimension in {"enactment_date", "commencement_date"}:
            if value_list and _all_equal(value_list):
                common_value = value_list[0]
                if answer_type == "date":
                    answer = common_value
                    confidence = 0.93
                    path = "cross_law_date_common"
                else:
                    answer = True
                    confidence = 0.92
                    path = "cross_law_boolean_same_date"
            elif value_list:
                answer = False if answer_type == "boolean" else None
                confidence = 0.88 if answer_type == "boolean" else 0.0
                abstained = answer_type != "boolean"
                path = "cross_law_boolean_date_not_common" if answer_type == "boolean" else "cross_law_abstain_common_date_conflict"
            else:
                abstained = True
                path = "cross_law_abstain_common_date_missing"
        else:
            comparable = [item for item in value_list if item is not None]
            if len(comparable) >= 2:
                answer = _all_equal(comparable)
                confidence = 0.9
                path = "cross_law_boolean_same_value"
            else:
                abstained = True
                path = "cross_law_abstain_same_value_missing"

    elif compare_operator in {"earlier_than", "later_than"}:
        left_id = anchor_order[0] if len(anchor_order) >= 1 else ""
        right_id = anchor_order[1] if len(anchor_order) >= 2 else ""
        left_value = _normalize_date_token(primary_values.get(left_id)) if left_id else None
        right_value = _normalize_date_token(primary_values.get(right_id)) if right_id else None
        if left_value and right_value:
            if answer_type == "boolean":
                if compare_operator == "earlier_than":
                    answer = left_value < right_value
                    path = "cross_law_boolean_earlier_than"
                else:
                    answer = left_value > right_value
                    path = "cross_law_boolean_later_than"
                confidence = 0.92
            elif answer_type == "date":
                answer = min(left_value, right_value) if compare_operator == "earlier_than" else max(left_value, right_value)
                confidence = 0.9
                path = "cross_law_date_extrema"
            else:
                left_label = _instrument_label(anchor_lookup.get(left_id, {"instrument_identifier": left_id}))
                right_label = _instrument_label(anchor_lookup.get(right_id, {"instrument_identifier": right_id}))
                answer = f"{left_label}: {left_value}; {right_label}: {right_value}."
                confidence = 0.82
                path = "cross_law_free_text_timeline_compare"
        else:
            abstained = True
            path = "cross_law_abstain_timeline_missing"

    elif compare_operator == "which_satisfy_condition":
        condition = _extract_condition_targets(question_text)
        matched_instruments: List[str] = []
        for instrument_id in anchor_order:
            rows = rows_by_identifier.get(instrument_id, [])
            if not rows:
                continue
            satisfies = True
            if condition.get("enacted_year"):
                years = _ordered_unique(
                    [
                        _collapse_ws(_candidate_projection(row).get("law_year") or _candidate_projection(row).get("regulation_year") or _candidate_projection(row).get("notice_year"))
                        for row in rows
                    ]
                )
                if condition["enacted_year"] not in years:
                    satisfies = False
            if satisfies and condition.get("authority"):
                authority_values = [
                    _collapse_ws(_extract_authority_value(row)).lower()
                    for row in rows
                    if _extract_authority_value(row)
                ]
                if not any(condition["authority"] in value for value in authority_values):
                    satisfies = False
            if satisfies and condition.get("feature_term"):
                term = str(condition["feature_term"])
                if not any(term in _candidate_text(row).lower() for row in rows):
                    satisfies = False
            if satisfies and condition.get("requires_schedule"):
                if _extract_schedule_presence(rows) is not True:
                    satisfies = False
            if satisfies:
                label = rows[0].get("compare_instrument_label") or instrument_id
                matched_instruments.append(_collapse_ws(label))

        matched_instruments = _ordered_unique([item for item in matched_instruments if item])
        if answer_type == "boolean":
            answer = bool(matched_instruments)
            confidence = 0.9
            path = "cross_law_boolean_condition_exists"
        elif answer_type == "name":
            if matched_instruments:
                answer = matched_instruments[0]
                confidence = 0.9
                path = "cross_law_name_condition_first"
            else:
                abstained = True
                path = "cross_law_abstain_condition_no_match"
        elif answer_type == "names":
            if matched_instruments:
                answer = matched_instruments
                confidence = 0.9
                path = "cross_law_names_condition_matches"
            else:
                abstained = True
                path = "cross_law_abstain_condition_no_match"
        else:
            if matched_instruments:
                answer = ", ".join(matched_instruments)
                confidence = 0.86
                path = "cross_law_free_text_condition_matches"
            else:
                abstained = True
                path = "cross_law_abstain_condition_no_match"

    else:
        if answer_type == "boolean":
            comparable = [item for item in primary_values.values() if item is not None]
            if len(comparable) >= 2:
                answer = _all_equal(comparable)
                confidence = 0.82
                path = "cross_law_boolean_default_compare"
            else:
                abstained = True
                path = "cross_law_abstain_boolean_default_missing"
        elif answer_type == "date":
            if primary_values and _all_equal(list(primary_values.values())):
                answer = list(primary_values.values())[0]
                confidence = 0.88
                path = "cross_law_date_default_common"
            else:
                abstained = True
                path = "cross_law_abstain_date_default"
        elif answer_type == "name":
            if primary_values:
                answer = str(next(iter(primary_values.values())))
                confidence = 0.8
                path = "cross_law_name_default"
            else:
                abstained = True
                path = "cross_law_abstain_name_default"
        elif answer_type == "names":
            if primary_values:
                answer = _ordered_unique([str(item) for item in primary_values.values()])
                confidence = 0.82
                path = "cross_law_names_default"
            else:
                abstained = True
                path = "cross_law_abstain_names_default"
        elif answer_type == "number":
            numbers = [_normalize_number(item) for item in primary_values.values()]
            numbers = [item for item in numbers if item is not None]
            unique_numbers = _ordered_unique(numbers)
            if len(unique_numbers) == 1:
                answer = unique_numbers[0]
                confidence = 0.86
                path = "cross_law_number_default"
            else:
                abstained = True
                path = "cross_law_abstain_number_default"
        else:
            fragments: List[str] = []
            for instrument_id in anchor_order:
                if instrument_id not in primary_values:
                    continue
                label = _instrument_label(anchor_lookup.get(instrument_id, {"instrument_identifier": instrument_id}))
                fragments.append(f"{label}: {primary_values[instrument_id]}")
            if fragments:
                answer = "; ".join(fragments) + "."
                confidence = 0.78
                path = "cross_law_free_text_extractive_compare"
            else:
                abstained = True
                path = "cross_law_abstain_free_text_default"

    if answer is None and not abstained:
        abstained = True
        confidence = 0.0

    matched_candidate_indices = _ordered_unique(
        [
            idx
            for dim_row in dimension_trace
            for idx in dim_row.get("evidence_candidate_indices", [])
            if isinstance(idx, int)
        ]
    )

    return _result(
        answer=answer,
        abstained=abstained,
        confidence=confidence if not abstained else 0.0,
        answer_type=answer_type,
        route_name=route_name,
        path=path,
        candidate_count=len(candidate_rows),
        matched_candidate_indices=matched_candidate_indices,
        values_considered=values_considered,
        compare_intent=intent,
        dimension_trace=dimension_trace,
    )
