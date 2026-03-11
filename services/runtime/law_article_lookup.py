"""Deterministic law/article lookup intent resolution for article route."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


RESOLUTION_VERSION = "law_article_lookup_resolution_v1"

_WHITESPACE_PATTERN = re.compile(r"\s+")
_PROVISION_LOOKUP_PHRASE_PATTERN = re.compile(
    r"\b(according to|under|pursuant to|as per|in accordance with)\s+"
    r"(article|section|paragraph|clause|schedule)\b",
    re.IGNORECASE,
)
_ARTICLE_PATTERN = re.compile(r"\barticle\s+(\d+[A-Za-z\-]*)(\s*(?:\([0-9A-Za-z]+\))*)", re.IGNORECASE)
_SECTION_PATTERN = re.compile(r"\bsection\s+(\d+[A-Za-z\-]*)(\s*(?:\([0-9A-Za-z]+\))*)", re.IGNORECASE)
_PARAGRAPH_PATTERN = re.compile(r"\bparagraph\s+(\d+[A-Za-z\-]*|\([0-9A-Za-z]+\))", re.IGNORECASE)
_CLAUSE_PATTERN = re.compile(r"\bclause\s+([0-9A-Za-z\-]+|\([0-9A-Za-z]+\))", re.IGNORECASE)
_SCHEDULE_PATTERN = re.compile(r"\bschedule\s+([0-9A-Za-z\-]+)", re.IGNORECASE)
_LAW_NUMBER_YEAR_PATTERN = re.compile(
    r"\b(?:difc\s+)?(?:law|regulation|statute|act|code)\s+(?:no\.?|number)\s*(\d{1,4})(?:\s+of\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_LAW_TITLE_CONTEXT_PATTERN = re.compile(
    r"\b(?:of|under|pursuant to|in|as per)\s+(?:the\s+)?"
    r"([A-Z][A-Za-z0-9&'().,\- ]+?\s(?:Law|Regulation|Statute|Code|Act))"
    r"(?:\s+No\.?\s*(\d{1,4})\s+of\s+(\d{4})|\s+(\d{4}))?",
    re.IGNORECASE,
)
_LAW_TITLE_FALLBACK_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&'().,\- ]+?\s(?:Law|Regulation|Statute|Code|Act))"
    r"(?:\s+No\.?\s*(\d{1,4})\s+of\s+(\d{4})|\s+(\d{4}))?",
    re.IGNORECASE,
)
_CASE_NUMBER_PATTERN = re.compile(r"\b(?:cfi|ca|arb|tcd|enf|dec|sct)\s*\d{1,3}/\d{4}\b", re.IGNORECASE)


def _collapse_ws(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", value).strip()


def _uniq(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        token = _collapse_ws(item)
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(token)
    return out


def _normalize_ref(value: str) -> str:
    return _collapse_ws(value).strip("()").lower()


def _extract_parenthetical_chain(raw_suffix: str) -> str | None:
    if not raw_suffix:
        return None
    groups = re.findall(r"\(([0-9A-Za-z]+)\)", raw_suffix)
    if not groups:
        return None
    return ".".join(group.lower() for group in groups)


def _extract_provision_matches(pattern: re.Pattern[str], text: str) -> List[Tuple[str, str | None]]:
    matches: List[Tuple[str, str | None]] = []
    for match in pattern.finditer(text):
        base = _normalize_ref(match.group(1))
        suffix = _extract_parenthetical_chain(match.group(2) if match.lastindex and match.lastindex >= 2 else "")
        if base:
            matches.append((base, suffix))
    return matches


def _extract_simple_matches(pattern: re.Pattern[str], text: str) -> List[str]:
    return _uniq([_normalize_ref(match.group(1)) for match in pattern.finditer(text)])


def _extract_law_title_and_refs(question_text: str) -> Tuple[str | None, str | None, str | None]:
    def _clean_title(raw_title: str) -> str:
        cleaned = _collapse_ws(raw_title)
        cleaned = re.sub(
            r"^(?:article|section|paragraph|clause|schedule)\s+[0-9A-Za-z().\-]+\s+of\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s*[\,\.;:]\s*$", "", cleaned)
        return _collapse_ws(cleaned)

    candidates: List[Tuple[str, str | None, str | None]] = []
    for pattern in (_LAW_TITLE_CONTEXT_PATTERN, _LAW_TITLE_FALLBACK_PATTERN):
        for match in pattern.finditer(question_text):
            title = _clean_title(match.group(1))
            number = _collapse_ws(match.group(2) or "")
            year = _collapse_ws(match.group(3) or match.group(4) or "")
            if not title:
                continue
            if re.match(r"^(article|section|paragraph|clause|schedule)\b", title, flags=re.IGNORECASE):
                continue
            candidates.append((title, number or None, year or None))
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda row: (len(row[0].split()), len(row[0])))
    title, number, year = candidates[0]
    return title, number, year


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug


def _resolve_law_identifier(*, title: str | None, law_number: str | None, law_year: str | None) -> str | None:
    if title and law_number and law_year:
        return f"{_slug(title)}_no_{law_number}_of_{law_year}"
    if title and law_number:
        return f"{_slug(title)}_no_{law_number}"
    if title and law_year:
        return f"{_slug(title)}_{law_year}"
    if law_number and law_year:
        return f"law_no_{law_number}_of_{law_year}"
    if law_number:
        return f"law_no_{law_number}"
    if title:
        return _slug(title)
    return None


def _resolved_doc_type_guess(question_text: str, law_title: str | None) -> str:
    lowered = question_text.lower()
    title_lower = (law_title or "").lower()
    if _CASE_NUMBER_PATTERN.search(question_text):
        return "case"
    if "enactment notice" in lowered or "enactment notice" in title_lower:
        return "enactment_notice"
    if "regulation" in lowered or "regulation" in title_lower:
        return "regulation"
    if any(token in lowered for token in ("law", "statute", "act", "code")) or law_title:
        return "law"
    return "unknown"


def resolve_law_article_lookup_intent(question_text: str) -> Dict[str, Any]:
    raw_text = _collapse_ws(str(question_text or ""))
    article_matches = _extract_provision_matches(_ARTICLE_PATTERN, raw_text)
    section_matches = _extract_provision_matches(_SECTION_PATTERN, raw_text)
    paragraph_refs = _extract_simple_matches(_PARAGRAPH_PATTERN, raw_text)
    clause_refs = _extract_simple_matches(_CLAUSE_PATTERN, raw_text)
    schedule_refs = _extract_simple_matches(_SCHEDULE_PATTERN, raw_text)

    law_number_year_matches = list(_LAW_NUMBER_YEAR_PATTERN.finditer(raw_text))
    law_number = _collapse_ws(law_number_year_matches[0].group(1)) if law_number_year_matches else None
    law_year_from_number = _collapse_ws(law_number_year_matches[0].group(2) or "") if law_number_year_matches else ""
    law_title, title_number, title_year = _extract_law_title_and_refs(raw_text)
    if title_number and not law_number:
        law_number = title_number
    law_year = law_year_from_number or title_year or None

    lookup_phrase_match = _PROVISION_LOOKUP_PHRASE_PATTERN.search(raw_text)
    lookup_phrase = _collapse_ws(lookup_phrase_match.group(0)) if lookup_phrase_match else None

    article_identifier = article_matches[0][0] if article_matches else None
    subarticle_identifier = article_matches[0][1] if article_matches and article_matches[0][1] else None
    section_identifier = section_matches[0][0] if section_matches else None
    if not subarticle_identifier and section_matches and section_matches[0][1]:
        subarticle_identifier = section_matches[0][1]

    if not article_identifier:
        article_identifier = section_identifier or (paragraph_refs[0] if paragraph_refs else None)

    provision_refs_present = bool(
        article_matches or section_matches or paragraph_refs or clause_refs or schedule_refs
    )
    explicit_law_reference = bool(law_title or law_number or law_year)

    confidence = 0.0
    if provision_refs_present:
        confidence += 0.5
    if lookup_phrase:
        confidence += 0.2
    if explicit_law_reference:
        confidence += 0.2
    if subarticle_identifier:
        confidence += 0.1
    provision_lookup_confidence = round(min(0.99, confidence), 2)

    law_identifier = _resolve_law_identifier(
        title=law_title,
        law_number=law_number,
        law_year=law_year,
    )

    return {
        "resolver_version": RESOLUTION_VERSION,
        "law_identifier": law_identifier,
        "article_identifier": article_identifier,
        "subarticle_identifier": subarticle_identifier,
        "provision_lookup_confidence": provision_lookup_confidence,
        "resolved_doc_type_guess": _resolved_doc_type_guess(raw_text, law_title),
        "law_title": law_title,
        "law_number": law_number,
        "law_year": law_year,
        "section_identifier": section_identifier,
        "paragraph_identifier": paragraph_refs[0] if paragraph_refs else None,
        "clause_identifier": clause_refs[0] if clause_refs else None,
        "schedule_identifier": schedule_refs[0] if schedule_refs else None,
        "lookup_phrase": lookup_phrase,
        "article_refs": [item[0] for item in article_matches],
        "section_refs": [item[0] for item in section_matches],
        "paragraph_refs": paragraph_refs,
        "clause_refs": clause_refs,
        "schedule_refs": schedule_refs,
        "law_numbers": _uniq([law_number] if law_number else []),
        "law_years": _uniq([law_year] if law_year else []),
        "law_titles": _uniq([law_title] if law_title else []),
        "requires_structural_lookup": provision_refs_present,
        "has_explicit_law_reference": explicit_law_reference,
        "matched_signal_count": (
            int(bool(provision_refs_present))
            + int(bool(lookup_phrase))
            + int(bool(explicit_law_reference))
        ),
    }
