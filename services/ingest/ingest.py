"""Corpus ingestion and indexing helpers for bootstrap runtime."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
from io import BytesIO
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from packages.contracts.corpus_scope import resolve_corpus_import_project_id

try:
    from legal_rag_api.storage import _utcnow
except Exception:  # pragma: no cover - local CLI fallback without API PYTHONPATH
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)


DOC_TYPE_HINTS: Dict[str, Tuple[str, ...]] = {
    "case": ("judgment", "court", "decision", "appeal", "claim no", "дело", "решение"),
    "enactment_notice": ("enactment notice", "notice", "enactment", "commencement", "gazette", "введение"),
    "regulation": ("regulations", "regulation", "rule", "rules", "order", "bylaw", "приказ", "положение"),
    "law": ("law no", "law", "act", "code", "statute", "закон", "кодекс"),
}

LEGAL_MARKER_PATTERNS: Tuple[str, ...] = (
    r"\bcase\s+no\b",
    r"\bcourt\b",
    r"\bjudgment\b",
    r"\border\b",
    r"\bclaimant\b",
    r"\bdefendant\b",
    r"\bart(?:icle|\.)\b",
    r"\blaw\b",
    r"\bregulation\b",
    r"\bsection\b",
    r"\btribunal\b",
    r"\benforcement\b",
)

SECTION_KIND_BY_DOC_TYPE: Dict[str, str] = {
    "law": "operative_provision",
    "regulation": "procedure",
    "enactment_notice": "cross_reference",
    "case": "reasoning",
    "other": "heading",
}
PROCESSING_PROFILE_VERSION = "parser_only_v1"
_OCR_SPLIT_WORD_ALLOWLIST: frozenset[str] = frozenset(
    {
        "appeal",
        "appellants",
        "between",
        "centre",
        "chief",
        "court",
        "courts",
        "dated",
        "defendant",
        "debtor",
        "dubai",
        "enforcement",
        "financial",
        "international",
        "justice",
        "martin",
        "order",
        "orders",
        "reasons",
        "upon",
        "wayne",
        "with",
    }
)
_OCR_JOIN_BLOCKLIST: frozenset[str] = frozenset({"A", "I", "IN", "NO", "OF", "ON", "OR", "THE", "TO", "V", "X"})
_MULTI_SINGLE_WITH_SUFFIX_PATTERN = re.compile(r"\b((?:[A-Z]\s+){2,})([A-Z]{2,6})\b")
_SINGLE_PLUS_SHORT_PATTERN = re.compile(r"\b([A-Z])\s+([A-Z]{2,6})\b")


def _join_if_allowlisted(left: str, right: str) -> str:
    if left in _OCR_JOIN_BLOCKLIST:
        return f"{left} {right}"
    candidate = f"{left}{right}".lower()
    if candidate in _OCR_SPLIT_WORD_ALLOWLIST:
        return f"{left}{right}"
    return f"{left} {right}"


def _repair_ocr_split_caps_line(line: str) -> str:
    if not re.search(r"\b[A-Z]{1,6}\s+[A-Z]{1,6}\b", line):
        return line

    repaired = _MULTI_SINGLE_WITH_SUFFIX_PATTERN.sub(lambda match: f"{match.group(1).replace(' ', '')}{match.group(2)}", line)
    repaired = _SINGLE_PLUS_SHORT_PATTERN.sub(lambda match: _join_if_allowlisted(match.group(1), match.group(2)), repaired)

    tokens = repaired.split()
    out: List[str] = []
    idx = 0
    while idx < len(tokens):
        current = tokens[idx]
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if re.fullmatch(r"[A-Z]{2,6}", current) and re.fullmatch(r"[A-Z]{2,6}", nxt):
                merged = _join_if_allowlisted(current, nxt)
                if " " not in merged:
                    out.append(merged)
                    idx += 2
                    continue
        out.append(current)
        idx += 1

    return re.sub(r"\s+", " ", " ".join(out)).strip()


def _looks_like_repeated_upper_heading(line: str) -> bool:
    letters = [char for char in line if char.isalpha()]
    if len(letters) < 12:
        return False
    upper_letters = sum(1 for char in letters if char.isupper())
    return (upper_letters / len(letters)) >= 0.78


def _looks_like_hex(text: str) -> bool:
    candidate = text.strip().lower()
    return len(candidate) >= 24 and bool(re.fullmatch(r"[a-f0-9]+", candidate))


def _uniq(values: Iterable[str], limit: int = 32) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        item = re.sub(r"\s+", " ", value).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _safe_pdf_id(member: str) -> str:
    base = Path(member).stem.replace(" ", "_") or member.replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)


def _stable_digest(*parts: Any) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            token = json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        elif part is None:
            token = "<none>"
        else:
            token = str(part)
        hasher.update(token.encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()


def _stable_id(prefix: str, *parts: Any, size: int = 24) -> str:
    return f"{prefix}_{_stable_digest(*parts)[:size]}"


def _source_pdf_output_dir(blob_url: str) -> Path:
    source = Path(blob_url).resolve()
    return source.parent / "_source_pdfs"


def _materialize_source_pdf(
    *,
    blob_url: str,
    pdf_id: str,
    content_hash: str,
    raw: bytes,
) -> str:
    out_dir = _source_pdf_output_dir(blob_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{pdf_id}_{content_hash[:12]}.pdf"
    if not target.exists():
        target.write_bytes(raw)
    return str(target)


def _extract_pdf_page_texts(raw: bytes) -> tuple[List[str], int, str | None]:
    try:
        from pypdf import PdfReader
    except Exception:
        return [], 0, "pdf_parser_unavailable"

    try:
        reader = PdfReader(BytesIO(raw))
        page_count = len(reader.pages)
        texts: List[str] = []
        for page in reader.pages:
            extracted = page.extract_text() or ""
            texts.append(_sanitize_preview_text(extracted))
        return texts, page_count, None
    except Exception:
        return [], 0, "pdf_parse_failed"


def _extract_preview_text(raw: bytes) -> str:
    decoded = raw.decode("latin-1", errors="ignore")
    chunks = re.findall(r"[A-Za-zА-Яа-я0-9№%$€£.,:;()/_\-]{8,}", decoded)
    pieces: List[str] = []
    total_len = 0
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk).strip()
        if len(normalized) < 16:
            continue
        pieces.append(normalized)
        total_len += len(normalized)
        if total_len >= 1800:
            break
    return " ".join(pieces)


def _sanitize_preview_text(text: str) -> str:
    without_nul = text.replace("\x00", " ")
    no_pdf_ops = re.sub(r"/[A-Za-z][A-Za-z0-9_-]*", " ", without_nul)
    no_object_noise = re.sub(r"\b\d+\s+\d+\s+obj\b", " ", no_pdf_ops, flags=re.IGNORECASE)
    normalized_breaks = no_object_noise.replace("\r\n", "\n").replace("\r", "\n")

    lines: List[str] = []
    seen_heading_keys: set[str] = set()
    for raw_line in normalized_breaks.split("\n"):
        normalized_line = re.sub(r"\s+", " ", raw_line).strip()
        if not normalized_line:
            continue
        repaired_line = _repair_ocr_split_caps_line(normalized_line)
        if not repaired_line:
            continue
        heading_key = re.sub(r"[^A-Za-z0-9]+", "", repaired_line).lower()
        if _looks_like_repeated_upper_heading(repaired_line) and len(heading_key) >= 16:
            if heading_key in seen_heading_keys:
                continue
            seen_heading_keys.add(heading_key)
        lines.append(repaired_line)

    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return cleaned


def _text_quality_features(text: str) -> Dict[str, float]:
    tokens = re.findall(r"\S+", text)
    words = re.findall(r"[A-Za-zА-Яа-я][A-Za-zА-Яа-я'-]{1,}", text)
    long_words = [w for w in words if len(w) >= 3]
    single_letter_tokens = re.findall(r"\b[A-Za-z]\b", text)
    slash_tokens = [token for token in tokens if token.startswith("/")]
    pdf_operator_hits = len(
        re.findall(
            r"/(?:Type|Catalog|Pages|Font|Filter|FlateDecode|XObject|Subtype|Length|ColorSpace|DeviceRGB)\b",
            text,
        )
    )
    legal_hits = 0
    lowered = text.lower()
    for pattern in LEGAL_MARKER_PATTERNS:
        if re.search(pattern, lowered):
            legal_hits += 1
    lexical_diversity = 0.0
    if long_words:
        lexical_diversity = len(set(w.lower() for w in long_words)) / len(long_words)

    non_printable = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t")
    token_count = len(tokens)
    word_count = len(words)

    return {
        "token_count": float(token_count),
        "word_count": float(word_count),
        "alpha_token_ratio": (word_count / token_count) if token_count else 0.0,
        "single_letter_ratio": (len(single_letter_tokens) / token_count) if token_count else 0.0,
        "slash_token_ratio": (len(slash_tokens) / token_count) if token_count else 0.0,
        "pdf_operator_hits": float(pdf_operator_hits),
        "lexical_diversity": lexical_diversity,
        "legal_hits": float(legal_hits),
        "non_printable_ratio": (non_printable / max(len(text), 1)),
        "repeated_chars_flag": 1.0 if re.search(r"(.)\1{10,}", text) else 0.0,
    }


def _text_quality_score(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0
    f = _text_quality_features(text)
    token_count = f["token_count"]
    if token_count < 20:
        return 0.0
    structure_score = min(1.0, token_count / 900.0)
    lexical_score = min(1.0, max(0.0, (f["lexical_diversity"] - 0.08) / 0.25))
    legal_signal_score = min(1.0, f["legal_hits"] / 4.0)
    single_letter_clean = max(0.0, min(1.0, 1.0 - (f["single_letter_ratio"] / 0.35)))
    noise_penalty = min(
        0.85,
        (f["slash_token_ratio"] * 1.8)
        + (f["non_printable_ratio"] * 8.0)
        + (f["pdf_operator_hits"] / 40.0)
        + (0.2 if f["repeated_chars_flag"] > 0 else 0.0),
    )
    score = (
        f["alpha_token_ratio"] * 0.30
        + lexical_score * 0.20
        + legal_signal_score * 0.25
        + structure_score * 0.15
        + single_letter_clean * 0.10
    ) - noise_penalty
    return max(0.0, min(1.0, score))


def _is_low_quality_text(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 80:
        return True
    f = _text_quality_features(text)
    if f["repeated_chars_flag"] > 0:
        return True
    if f["token_count"] < 40 or f["word_count"] < 25:
        return True
    if f["pdf_operator_hits"] >= 8 and f["legal_hits"] < 1:
        return True
    if f["alpha_token_ratio"] < 0.22 and f["slash_token_ratio"] > 0.08:
        return True
    score = _text_quality_score(text)
    return score < 0.58


def _split_paragraphs(text: str, max_chunk: int = 900) -> List[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    raw_parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    parts = raw_parts if raw_parts else [normalized]
    chunks: List[str] = []
    for part in parts:
        current = re.sub(r"\s+", " ", part).strip()
        while len(current) > max_chunk:
            cut = current.rfind(" ", 0, max_chunk)
            if cut < 200:
                cut = max_chunk
            chunk = current[:cut].strip()
            if chunk:
                chunks.append(chunk)
            current = current[cut:].strip()
        if current:
            chunks.append(current)
    return chunks[:12]


def _extract_refs(text: str) -> Dict[str, List[str]]:
    article_refs = _uniq(
        re.findall(r"(?i)\b(?:article|art\.?|статья|ст\.)\s*[0-9]+(?:[-.][0-9A-Za-z]+)?", text),
        limit=24,
    )
    law_refs = _uniq(
        re.findall(r"(?i)\b(?:law|act|code|закон)\s*(?:no\.?|№)?\s*[A-Za-z0-9./-]{1,24}", text),
        limit=24,
    )
    case_refs = _uniq(
        re.findall(r"(?i)\b(?:case|дело)\s*(?:no\.?|№)?\s*[A-Za-z0-9./-]{1,24}", text),
        limit=24,
    )
    dates = _uniq(
        re.findall(
            r"\b(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|(?:19|20)\d{2})\b",
            text,
        ),
        limit=24,
    )
    money_mentions = _uniq(
        re.findall(
            r"(?i)(?:[$€£₸]|(?:usd|eur|kzt|тенге))\s*[0-9]+(?:[.,][0-9]{1,2})?",
            text,
        ),
        limit=24,
    )
    entities = _uniq(
        re.findall(r"\b[A-ZА-Я][a-zа-я]{2,}(?:\s+[A-ZА-Я][a-zа-я]{2,}){0,2}\b", text),
        limit=24,
    )
    return {
        "article_refs": article_refs,
        "law_refs": law_refs,
        "case_refs": case_refs,
        "dates": dates,
        "money_mentions": money_mentions,
        "entities": entities,
    }


def _infer_doc_type(member: str, text: str) -> tuple[str, float]:
    source = f"{member.lower()} {text.lower()}"
    source = re.sub(r"[_-]+", " ", source)
    source = re.sub(r"\s+", " ", source).strip()
    scores: Dict[str, int] = {"other": 0}
    for doc_type, hints in DOC_TYPE_HINTS.items():
        score = 0
        for hint in hints:
            if " " in hint:
                score += source.count(hint)
            else:
                score += len(re.findall(rf"\b{re.escape(hint)}\b", source))
        scores[doc_type] = score

    strong_patterns: Dict[str, Tuple[str, ...]] = {
        "law": (r"\blaw\s+no\.?\b", r"\bdifc\s+law\b", r"\bcompanies\s+law\b"),
        "regulation": (r"\bregulations?\b", r"\bleasing\s+regulations?\b"),
        "enactment_notice": (r"\benactment\s+notice\b",),
        "case": (r"\bclaim\s+no\.?\b", r"\bjudgment\b", r"\bcourt\s+of\b", r"\bv\s+[A-Z]"),
    }
    for doc_type, patterns in strong_patterns.items():
        if any(re.search(pattern, source, flags=re.IGNORECASE) for pattern in patterns):
            scores[doc_type] = scores.get(doc_type, 0) + 4

    tie_breaker: Dict[str, int] = {
        "enactment_notice": 5,
        "law": 4,
        "regulation": 3,
        "case": 2,
        "other": 1,
    }
    best_type = max(scores.keys(), key=lambda doc_type: (scores.get(doc_type, 0), tie_breaker.get(doc_type, 0)))
    best_score = scores.get(best_type, 0)
    if best_score == 0:
        return "other", 0.2
    confidence = min(0.95, 0.30 + best_score * 0.12)
    return best_type, confidence


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if not match:
        return None
    return int(match.group(1))


def _extract_law_number(text: str) -> str | None:
    text = text.replace("_", " ")
    match = re.search(
        r"(?i)(?:law|act|code)\s*(?:no\.?|№)?\s*([A-Za-z0-9./-]{1,24})|(?:no\.?|№)\s*([A-Za-z0-9./-]{1,24})",
        text,
    )
    if not match:
        return None
    candidate = match.group(1) or match.group(2)
    if not candidate:
        return None
    return candidate.strip()


def _extract_case_id(text: str) -> str | None:
    match = re.search(r"(?i)(?:case|дело)\s*(?:no\.?|№)?\s*([A-Za-z0-9][A-Za-z0-9./-]{1,31})", text)
    if not match:
        return None
    candidate = match.group(1).strip()
    if candidate.lower().endswith(".pdf"):
        return None
    return candidate


def _compact_summary(text: str, fallback_title: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return f"No readable legal text extracted for '{fallback_title}'. OCR or parser fallback required."
    return normalized[:280]


def _build_ontology(
    doc_type: str,
    title: str,
    refs: Dict[str, List[str]],
    year: int | None,
    law_number: str | None,
    case_id: str | None,
) -> Dict[str, Any]:
    if doc_type == "law":
        return {
            "title": title,
            "citation_title": title,
            "law_number": law_number,
            "year": year,
            "articles": refs["article_refs"][:12],
            "amended_by": refs["law_refs"][:8],
            "legislative_authority": refs["entities"][:4],
        }
    if doc_type == "regulation":
        return {
            "title": title,
            "in_force_date": refs["dates"][0] if refs["dates"] else None,
            "enabling_law_refs": refs["law_refs"][:8],
            "penalties": refs["money_mentions"][:8],
            "definitions": refs["article_refs"][:8],
        }
    if doc_type == "enactment_notice":
        return {
            "enacted_law_title": title,
            "enactment_date": refs["dates"][0] if refs["dates"] else None,
            "commencement_rule": "explicit_date" if refs["dates"] else "not_detected",
            "legislative_authority": refs["entities"][:4],
        }
    if doc_type == "case":
        return {
            "case_id": case_id,
            "case_dates": refs["dates"][:8],
            "parties_by_role": refs["entities"][:8],
            "claim_value": refs["money_mentions"][:4],
            "referenced_prior_cases_laws": refs["case_refs"][:8] + refs["law_refs"][:8],
        }
    return {
        "title": title,
        "detected_refs": refs["law_refs"][:8] + refs["case_refs"][:8] + refs["article_refs"][:8],
    }


def _title_normalized(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _normalize_date_token(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    if re.fullmatch(r"(?:19|20)\d{2}", candidate):
        return f"{candidate}-01-01"
    normalized = candidate.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(normalized, fmt).date()
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def _first_date(dates: List[str]) -> str | None:
    for value in dates:
        normalized = _normalize_date_token(value)
        if normalized:
            return normalized
    return None


def _extract_effective_start_date(text: str, dates: List[str]) -> str | None:
    temporal_text = text.replace("_", " ")
    match = re.search(
        r"(?i)(?:effective\s+from|effective\s+on|in\s+force\s+from|commenc\w*\s+on|"
        r"commencement\s+date|вступает\s+в\s+силу\s+с|действует\s+с)\s*[:\-]?\s*"
        r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|(?:19|20)\d{2})",
        temporal_text,
    )
    if match:
        normalized = _normalize_date_token(match.group(1))
        if normalized:
            return normalized
    return _first_date(dates)


def _extract_effective_end_date(text: str, dates: List[str]) -> str | None:
    temporal_text = text.replace("_", " ")
    match = re.search(
        r"(?i)(?:effective\s+until|in\s+force\s+until|valid\s+until|until|till|through|"
        r"expires?\s+on|expires?|ceases?\s+to\s+have\s+effect\s+on|repealed\s+on|"
        r"утрачивает\s+силу\s+с|действует\s+до|по)\s*[:\-]?\s*"
        r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|(?:19|20)\d{2})",
        temporal_text,
    )
    if match:
        normalized = _normalize_date_token(match.group(1))
        if normalized:
            return normalized

    if re.search(r"(?i)\b(repealed|expired|superseded|cease)\b", temporal_text):
        candidates = [normalized for normalized in (_normalize_date_token(v) for v in dates) if normalized]
        if candidates:
            return sorted(candidates)[-1]
    return None


def _is_current_from_end_date(effective_end_date: str | None) -> bool:
    if not effective_end_date:
        return True
    normalized = _normalize_date_token(effective_end_date)
    if not normalized:
        return True
    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError:
        return True
    return parsed >= date.today()


def _resolve_duplicate_group_id(
    *,
    dedupe_enabled: bool,
    content_hash: str,
    canonical_doc_id: str,
    seen_hashes: Dict[str, str],
) -> str | None:
    """Return duplicate-group anchor for exact byte-identical files.

    The first seen document in a hash group is the anchor. Every later identical
    file points to that anchor via `duplicate_group_id`.
    """
    if not dedupe_enabled:
        return None
    anchor_doc_id = seen_hashes.get(content_hash)
    if anchor_doc_id is None:
        seen_hashes[content_hash] = canonical_doc_id
        return None
    return anchor_doc_id


def _resolve_version_group_id(
    *,
    doc_type: str,
    law_number: str | None,
    case_id: str | None,
    pdf_id: str,
) -> str:
    if doc_type in {"law", "regulation", "enactment_notice"} and law_number:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", law_number.strip().lower()).strip("_")
        if normalized:
            return f"{doc_type}:{normalized}"
    if doc_type == "case" and case_id:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", case_id.strip().lower()).strip("_")
        if normalized:
            return f"{doc_type}:{normalized}"
    return pdf_id


def _resolve_parse_warning(*, low_quality_text: bool) -> str | None:
    if low_quality_text:
        return "low_text_quality"
    return None


def _version_sort_key(row: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("effective_start_date") or ""),
        str(row.get("issued_date") or ""),
        str(row.get("document_id") or ""),
    )


def _apply_family_versioning(documents: List[Dict[str, Any]], document_bases: List[Dict[str, Any]]) -> None:
    docs_by_id = {str(row.get("document_id")): row for row in documents}
    base_by_id = {str(row.get("document_id")): row for row in document_bases}
    families: Dict[str, List[Dict[str, Any]]] = {}
    for row in documents:
        family_id = str(row.get("version_group_id") or "")
        if not family_id:
            continue
        if row.get("duplicate_group_id"):
            continue
        families.setdefault(family_id, []).append(row)

    for family_rows in families.values():
        ordered = sorted(family_rows, key=_version_sort_key)
        for index, row in enumerate(ordered, start=1):
            row["version_sequence"] = index
            row["supersedes_doc_id"] = None
            row["superseded_by_doc_id"] = None
            base = base_by_id.get(str(row.get("document_id")))
            if base is not None:
                base["version_sequence"] = index
                base["supersedes_doc_id"] = None
                base["superseded_by_doc_id"] = None
            docs_by_id[str(row.get("document_id"))] = row


def _detect_article_number(article_refs: List[str]) -> str | None:
    if not article_refs:
        return None
    match = re.search(r"([0-9]+(?:[-.][0-9A-Za-z]+)?)", article_refs[0])
    if not match:
        return None
    return match.group(1)


def _retrieval_text(title: str, chunk: str, refs: Dict[str, List[str]]) -> str:
    sections = [
        title,
        chunk,
        " ".join(refs.get("article_refs", [])),
        " ".join(refs.get("law_refs", [])),
        " ".join(refs.get("case_refs", [])),
    ]
    return re.sub(r"\s+", " ", " ".join(part for part in sections if part)).strip()[:2400]


def ingest_zip_stub(blob_url: str, project_id: str, parse_policy: str, dedupe_enabled: bool) -> Dict[str, List[Dict[str, Any]]]:
    """Create synthetic documents/pages/paragraphs from a zip for local bootstrap."""
    corpus_project_id = resolve_corpus_import_project_id(project_id)
    docs: List[Dict[str, Any]] = []
    document_bases: List[Dict[str, Any]] = []
    law_documents: List[Dict[str, Any]] = []
    regulation_documents: List[Dict[str, Any]] = []
    enactment_notice_documents: List[Dict[str, Any]] = []
    case_documents: List[Dict[str, Any]] = []
    pages: List[Dict[str, Any]] = []
    paragraphs: List[Dict[str, Any]] = []
    chunk_bases: List[Dict[str, Any]] = []
    law_chunk_facets: List[Dict[str, Any]] = []
    regulation_chunk_facets: List[Dict[str, Any]] = []
    enactment_notice_chunk_facets: List[Dict[str, Any]] = []
    case_chunk_facets: List[Dict[str, Any]] = []
    relation_edges: List[Dict[str, Any]] = []
    chunk_search_documents: List[Dict[str, Any]] = []

    if not os.path.exists(blob_url):
        # keep explicit contract-compatible behavior: no-op with failure payload
        return {
            "documents": docs,
            "document_bases": document_bases,
            "law_documents": law_documents,
            "regulation_documents": regulation_documents,
            "enactment_notice_documents": enactment_notice_documents,
            "case_documents": case_documents,
            "pages": pages,
            "paragraphs": paragraphs,
            "chunk_bases": chunk_bases,
            "law_chunk_facets": law_chunk_facets,
            "regulation_chunk_facets": regulation_chunk_facets,
            "enactment_notice_chunk_facets": enactment_notice_chunk_facets,
            "case_chunk_facets": case_chunk_facets,
            "relation_edges": relation_edges,
            "chunk_search_documents": chunk_search_documents,
        }

    seen_hashes: Dict[str, str] = {}
    ingested_at = _utcnow().isoformat()
    with zipfile.ZipFile(blob_url) as zf:
        pdf_members = sorted(
            (member for member in zf.namelist() if member.lower().endswith(".pdf")),
            key=lambda item: item.lower(),
        )
        for member in pdf_members:
            raw = zf.read(member)
            content_hash = hashlib.sha256(raw).hexdigest()
            pdf_id = _safe_pdf_id(member)
            canonical_doc_id = f"{pdf_id}-v1"
            parsed_page_texts, parsed_page_count, parse_error = _extract_pdf_page_texts(raw)
            parsed_joined_text = " ".join(t for t in parsed_page_texts if t).strip()
            preview_text_raw = parsed_joined_text if parsed_joined_text else _extract_preview_text(raw)
            preview_text = _sanitize_preview_text(preview_text_raw)
            quality_features = _text_quality_features(preview_text)
            low_quality_text = _is_low_quality_text(preview_text) or bool(parse_error)
            text_quality_score = _text_quality_score(preview_text)
            has_structured_legal_text = (
                quality_features["token_count"] >= 40
                and quality_features["word_count"] >= 25
                and quality_features["legal_hits"] >= 1
            )
            # Do not suppress semantic extraction when legal text is present.
            if low_quality_text and has_structured_legal_text and not parse_error:
                low_quality_text = False

            title_candidate = Path(member).stem.replace("_", " ").strip()
            if _looks_like_hex(title_candidate):
                title = f"Document {title_candidate[:12]}"
            else:
                title = title_candidate or pdf_id

            refs_source = f"{member} {preview_text}".strip() if preview_text else member
            refs = _extract_refs(refs_source)
            doc_type, classification_confidence = _infer_doc_type(member, preview_text)
            if low_quality_text and not has_structured_legal_text:
                classification_confidence = min(classification_confidence, 0.25)
            year = _extract_year(f"{member} {preview_text}")
            law_number = _extract_law_number(f"{member} {preview_text}")
            case_id = _extract_case_id(f"{member} {preview_text}")
            temporal_source = f"{member} {preview_text}"
            issued_date = _first_date(refs["dates"])
            effective_start_date = _extract_effective_start_date(temporal_source, refs["dates"])
            effective_end_date = _extract_effective_end_date(temporal_source, refs["dates"])
            is_current_version = _is_current_from_end_date(effective_end_date)
            historical_relation_type = "repealed" if effective_end_date and not is_current_version else "original"
            ontology = _build_ontology(doc_type, title, refs, year, law_number, case_id)
            summary_source = preview_text
            tags = _uniq(
                [
                    doc_type,
                    "needs_review" if low_quality_text else "",
                    "parser_fallback" if parse_error else "",
                    "has_articles" if refs["article_refs"] else "",
                    "has_law_refs" if refs["law_refs"] else "",
                    "has_case_refs" if refs["case_refs"] else "",
                    "has_money" if refs["money_mentions"] else "",
                    f"year_{year}" if year else "",
                ],
                limit=12,
            )
            duplicate_group_id = _resolve_duplicate_group_id(
                dedupe_enabled=dedupe_enabled,
                content_hash=content_hash,
                canonical_doc_id=canonical_doc_id,
                seen_hashes=seen_hashes,
            )
            parse_warning = _resolve_parse_warning(low_quality_text=low_quality_text)
            source_pdf_path = _materialize_source_pdf(
                blob_url=blob_url,
                pdf_id=pdf_id,
                content_hash=content_hash,
                raw=raw,
            )

            document_id = _stable_id("doc", canonical_doc_id, content_hash)
            page_count = parsed_page_count if parsed_page_count > 0 else 1
            title_normalized = _title_normalized(title)
            version_group_id = _resolve_version_group_id(
                doc_type=doc_type,
                law_number=law_number,
                case_id=case_id,
                pdf_id=pdf_id,
            )

            document_manifest = {
                "document_id": document_id,
                "project_id": corpus_project_id,
                "pdf_id": pdf_id,
                "canonical_doc_id": canonical_doc_id,
                "content_hash": content_hash,
                "doc_type": doc_type,
                "title": title,
                "citation_title": title,
                "law_number": law_number,
                "case_id": case_id,
                "year": year,
                "page_count": page_count,
                "duplicate_group_id": duplicate_group_id,
                "status": "parsed",
                "title_raw": title,
                "title_normalized": title_normalized,
                "short_title": title[:80],
                "language": "unknown",
                "jurisdiction": "unknown",
                "issued_date": issued_date,
                "effective_start_date": effective_start_date,
                "effective_end_date": effective_end_date,
                "repealed_date": None,
                "is_current_version": is_current_version,
                "version_group_id": version_group_id,
                "version_sequence": 0,
                "supersedes_doc_id": None,
                "superseded_by_doc_id": None,
                "parser_version": "stub-v1",
                "ocr_used": False,
                "extraction_confidence": round(classification_confidence, 4),
                "ingested_at": ingested_at,
                "last_reprocessed_at": None,
                "topic_tags": tags[:8],
                "legal_domains": tags[:5],
                "entity_names": refs["entities"][:12],
                "citation_keys": refs["law_refs"][:8] + refs["case_refs"][:8],
                "search_text_compact": _compact_summary(summary_source, title),
                "search_priority_score": round(0.25 + classification_confidence * 0.5, 4),
                "processing": {
                    "classification_confidence": classification_confidence,
                    "text_quality_score": text_quality_score,
                    "parse_warning": parse_warning,
                    "parse_error": parse_error,
                    "tags": tags,
                    "compact_summary": _compact_summary(summary_source, title),
                    "processing_profile_version": PROCESSING_PROFILE_VERSION,
                    "source_archive_path": blob_url,
                    "source_archive_member": member,
                    "source_pdf_path": source_pdf_path,
                    "ontology": ontology,
                    "entities": refs["entities"][:12],
                    "article_refs": refs["article_refs"][:12],
                    "law_refs": refs["law_refs"][:12],
                    "case_refs": refs["case_refs"][:12],
                    "dates": refs["dates"][:12],
                    "money_mentions": refs["money_mentions"][:12],
                },
            }
            docs.append(document_manifest)

            document_bases.append(
                {
                    "document_id": document_id,
                    "project_id": corpus_project_id,
                    "pdf_id": pdf_id,
                    "canonical_doc_id": canonical_doc_id,
                    "doc_type": doc_type,
                    "source_file_name": Path(member).name,
                    "source_sha256": content_hash,
                    "duplicate_group_id": duplicate_group_id,
                    "title_raw": title,
                    "title_normalized": title_normalized,
                    "short_title": title[:80],
                    "citation_title": title,
                    "language": "unknown",
                    "jurisdiction": "unknown",
                    "issued_date": issued_date,
                    "effective_start_date": effective_start_date,
                    "effective_end_date": effective_end_date,
                    "repealed_date": None,
                    "is_current_version": is_current_version,
                    "version_group_id": version_group_id,
                    "version_sequence": 0,
                    "supersedes_doc_id": None,
                    "superseded_by_doc_id": None,
                    "page_count": page_count,
                    "parser_version": "stub-v1",
                    "ocr_used": False,
                    "extraction_confidence": round(classification_confidence, 4),
                    "ingested_at": ingested_at,
                    "last_reprocessed_at": None,
                    "topic_tags": tags[:8],
                    "legal_domains": tags[:5],
                    "entity_names": refs["entities"][:12],
                    "citation_keys": refs["law_refs"][:8] + refs["case_refs"][:8],
                    "search_text_compact": _compact_summary(summary_source, title),
                    "search_priority_score": round(0.25 + classification_confidence * 0.5, 4),
                    "status": "parsed",
                }
            )

            if doc_type == "law":
                law_documents.append(
                    {
                        "document_id": document_id,
                        "law_number": law_number,
                        "law_year": year,
                        "instrument_kind": "law",
                        "administering_authority": refs["entities"][0] if refs["entities"] else None,
                        "promulgation_date": issued_date,
                        "commencement_date": issued_date,
                        "status": "in_force" if is_current_version else "repealed",
                        "amends_law_ids": refs["law_refs"][:5],
                        "amended_by_doc_ids": [],
                        "article_count": len(refs["article_refs"]),
                        "schedule_count": 0,
                        "defined_terms": refs["entities"][:6],
                        "regulated_subjects": tags[:4],
                        "cross_references": refs["article_refs"][:8],
                    }
                )
            elif doc_type == "regulation":
                enabled_law = refs["law_refs"][0] if refs["law_refs"] else None
                regulation_documents.append(
                    {
                        "document_id": document_id,
                        "regulation_number": law_number,
                        "regulation_year": year,
                        "regulation_type": "regulation",
                        "issuing_authority": refs["entities"][0] if refs["entities"] else None,
                        "enabled_by_law_id": enabled_law,
                        "enabled_by_law_title": enabled_law,
                        "enabled_by_article_refs": refs["article_refs"][:8],
                        "status": "in_force" if is_current_version else "repealed",
                        "is_current_version": is_current_version,
                        "regulated_entities": refs["entities"][:8],
                        "compliance_subjects": tags[:6],
                        "reporting_requirements": refs["article_refs"][:6],
                        "filing_requirements": refs["article_refs"][:4],
                        "penalty_or_consequence_present": bool(refs["money_mentions"]),
                        "procedural_steps": refs["article_refs"][:5],
                        "amends_regulation_ids": [],
                        "related_law_ids": refs["law_refs"][:8],
                        "cross_references": refs["article_refs"][:10],
                    }
                )
            elif doc_type == "enactment_notice":
                enactment_notice_documents.append(
                    {
                        "document_id": document_id,
                        "notice_number": law_number,
                        "notice_year": year,
                        "notice_type": "commencement_notice",
                        "issuing_authority": refs["entities"][0] if refs["entities"] else None,
                        "target_doc_id": refs["law_refs"][0] if refs["law_refs"] else None,
                        "target_doc_type": "law",
                        "target_title": refs["law_refs"][0] if refs["law_refs"] else None,
                        "target_law_number": law_number,
                        "target_law_year": year,
                        "commencement_scope_type": "partial" if refs["article_refs"] else "full",
                        "commencement_date": issued_date,
                        "commencement_date_text_raw": refs["dates"][0] if refs["dates"] else None,
                        "target_article_refs": refs["article_refs"][:12],
                        "excluded_article_refs": [],
                        "conditions_precedent": [],
                        "territorial_scope": None,
                        "exception_text_present": False,
                        "overrides_prior_notice_ids": [],
                        "related_notice_ids": [],
                        "linked_version_group_id": version_group_id,
                    }
                )
            elif doc_type == "case":
                case_documents.append(
                    {
                        "document_id": document_id,
                        "case_number": case_id,
                        "neutral_citation": case_id,
                        "court_name": refs["entities"][0] if refs["entities"] else None,
                        "court_level": "unknown",
                        "chamber_or_division": None,
                        "jurisdiction": "unknown",
                        "decision_date": issued_date,
                        "judgment_date": issued_date,
                        "claimant_names": refs["entities"][:2],
                        "respondent_names": refs["entities"][2:4],
                        "party_names_normalized": [value.lower() for value in refs["entities"][:8]],
                        "judge_names": refs["entities"][:2],
                        "presiding_judge": refs["entities"][0] if refs["entities"] else None,
                        "procedural_stage": "judgment",
                        "legal_topics": tags[:6],
                        "claim_amounts": refs["money_mentions"][:6],
                        "relief_sought": [],
                        "issues_present": refs["article_refs"][:8],
                        "final_disposition": "unknown",
                        "outcome_for_claimant": None,
                        "outcome_for_respondent": None,
                        "cited_law_ids": refs["law_refs"][:10],
                        "cited_article_refs": refs["article_refs"][:10],
                        "cited_case_ids": refs["case_refs"][:10],
                    }
                )

            page_paragraph_index = 0
            page_texts = parsed_page_texts if parsed_page_texts else [summary_source]
            for page_num, page_text in enumerate(page_texts):
                safe_page_text = _sanitize_preview_text(page_text)
                if not safe_page_text:
                    safe_page_text = _compact_summary(summary_source, title)
                source_page_id = f"{pdf_id}_{page_num}"
                page_id = _stable_id("page", document_id, source_page_id, content_hash)
                page_ref_source = safe_page_text if safe_page_text else member
                page_refs = _extract_refs(page_ref_source)
                page_temporal_source = f"{member} {safe_page_text}"
                page_effective_start_date = _extract_effective_start_date(page_temporal_source, page_refs["dates"]) or effective_start_date
                page_effective_end_date = _extract_effective_end_date(page_temporal_source, page_refs["dates"]) or effective_end_date
                page_is_current_version = _is_current_from_end_date(page_effective_end_date)
                pages.append(
                    {
                        "page_id": page_id,
                        "document_id": document_id,
                        "project_id": corpus_project_id,
                        "pdf_id": pdf_id,
                        "source_page_id": source_page_id,
                        "page_num": page_num,
                        "page_number": page_num,
                        "text": safe_page_text[:2200],
                        "page_text_raw": safe_page_text[:2200],
                        "page_text_clean": safe_page_text[:2200],
                        "page_class": "needs_review" if low_quality_text else "body",
                        "heading_path": [title[:40]],
                        "contains_dates": bool(page_refs["dates"]),
                        "contains_money": bool(page_refs["money_mentions"]),
                        "contains_party_names": doc_type == "case" and bool(page_refs["entities"]),
                        "contains_judges": doc_type == "case" and bool(page_refs["entities"]),
                        "contains_article_refs": bool(page_refs["article_refs"]),
                        "contains_schedule_refs": False,
                        "contains_amendment_language": bool(re.search(r"(?i)\bamend", safe_page_text)),
                        "contains_commencement_language": bool(re.search(r"(?i)\bcommenc", safe_page_text)),
                        "dominant_section_kind": SECTION_KIND_BY_DOC_TYPE.get(doc_type, "heading"),
                        "search_text_compact": safe_page_text[:400],
                        "effective_start_date": page_effective_start_date,
                        "effective_end_date": page_effective_end_date,
                        "is_current_version": page_is_current_version,
                        "created_at": ingested_at,
                        "entities": page_refs["entities"][:12],
                    }
                )

                paragraph_chunks = _split_paragraphs(safe_page_text)
                if not paragraph_chunks:
                    paragraph_chunks = [safe_page_text]
                for chunk in paragraph_chunks:
                    chunk_refs = _extract_refs(chunk)
                    chunk_temporal_source = f"{member} {chunk}"
                    chunk_effective_start_date = _extract_effective_start_date(chunk_temporal_source, chunk_refs["dates"]) or page_effective_start_date
                    chunk_effective_end_date = _extract_effective_end_date(chunk_temporal_source, chunk_refs["dates"]) or page_effective_end_date
                    chunk_is_current_version = _is_current_from_end_date(chunk_effective_end_date)
                    chunk_historical_relation_type = "repealed" if chunk_effective_end_date and not chunk_is_current_version else historical_relation_type
                    paragraph_class = "case_excerpt" if doc_type == "case" else "article_clause" if chunk_refs["article_refs"] else "body"
                    paragraph_id = _stable_id(
                        "para",
                        page_id,
                        page_paragraph_index,
                        chunk[:1400],
                    )
                    section_kind = (
                        "definition"
                        if "definition" in chunk.lower()
                        else "operative_provision"
                        if chunk_refs["article_refs"]
                        else SECTION_KIND_BY_DOC_TYPE.get(doc_type, "heading")
                    )
                    article_number = _detect_article_number(chunk_refs["article_refs"])
                    retrieval_text = _retrieval_text(title, chunk, chunk_refs)
                    canonical_concept_id = f"{pdf_id}:{article_number}" if article_number else f"{pdf_id}:document"
                    provision_kind = (
                        "definition"
                        if "definition" in chunk.lower()
                        else "obligation"
                        if "shall" in chunk.lower()
                        else "procedure"
                    )
                    edge_types: List[str] = []
                    if doc_type == "regulation" and chunk_refs["law_refs"]:
                        edge_types.append("enabled_by")
                    if chunk_refs["law_refs"] or chunk_refs["case_refs"] or chunk_refs["article_refs"]:
                        edge_types.append("refers_to")
                    paragraphs.append(
                        {
                            "paragraph_id": paragraph_id,
                            "page_id": page_id,
                            "document_id": document_id,
                            "project_id": corpus_project_id,
                            "paragraph_index": page_paragraph_index,
                            "heading_path": [doc_type, parse_policy],
                            "text": chunk[:1400],
                            "text_clean": chunk[:1400],
                            "text_compact": chunk[:700],
                            "retrieval_text": retrieval_text[:1800],
                            "summary_tag": tags[0] if tags else doc_type,
                            "paragraph_class": paragraph_class,
                            "chunk_type": "paragraph",
                            "chunk_index_on_page": page_paragraph_index,
                            "char_start": 0,
                            "char_end": len(chunk[:1400]),
                            "entities": chunk_refs["entities"][:12],
                            "entity_names_normalized": [value.lower() for value in chunk_refs["entities"][:12]],
                            "article_refs": chunk_refs["article_refs"][:12],
                            "law_refs": chunk_refs["law_refs"][:12],
                            "case_refs": chunk_refs["case_refs"][:12],
                            "dates": chunk_refs["dates"][:12],
                            "money_mentions": chunk_refs["money_mentions"][:12],
                            "version_lineage_id": canonical_doc_id,
                            "effective_start_date": chunk_effective_start_date,
                            "effective_end_date": chunk_effective_end_date,
                            "is_current_version": chunk_is_current_version,
                            "canonical_concept_id": canonical_concept_id,
                            "historical_relation_type": chunk_historical_relation_type,
                            "section_kind": section_kind,
                            "exact_terms": chunk_refs["article_refs"][:6] + chunk_refs["law_refs"][:6],
                            "search_keywords": tags[:6] + chunk_refs["entities"][:4],
                            "rank_hints": [doc_type, section_kind],
                            "answer_candidate_types": [doc_type],
                            "confidence_score": round(max(0.3, classification_confidence), 4),
                            "parser_flags": (
                                (["low_text_quality"] if low_quality_text else [])
                                + (["has_effective_end_date"] if chunk_effective_end_date else [])
                            ),
                            "extraction_method": "rules_stub",
                            "tagging_model_version": "rules-v1",
                            "last_tagged_at": ingested_at,
                        }
                    )
                    chunk_bases.append(
                        {
                            "chunk_id": paragraph_id,
                            "document_id": document_id,
                            "pdf_id": pdf_id,
                            "page_id": page_id,
                            "page_number": page_num,
                            "chunk_type": "paragraph",
                            "chunk_index_on_page": page_paragraph_index,
                            "char_start": 0,
                            "char_end": len(chunk[:1400]),
                            "text_raw": chunk[:1400],
                            "text_clean": chunk[:1400],
                            "text_compact": chunk[:700],
                            "retrieval_text": retrieval_text[:1800],
                            "embedding_text": retrieval_text[:1800],
                            "heading_path": [doc_type, parse_policy],
                            "section_kind": section_kind,
                            "structural_level": 1,
                            "parent_section_id": None,
                            "prev_chunk_id": None,
                            "next_chunk_id": None,
                            "entity_names": chunk_refs["entities"][:12],
                            "entity_names_normalized": [value.lower() for value in chunk_refs["entities"][:12]],
                            "article_refs": chunk_refs["article_refs"][:12],
                            "schedule_refs": [],
                            "law_refs": chunk_refs["law_refs"][:12],
                            "case_refs": chunk_refs["case_refs"][:12],
                            "dates": chunk_refs["dates"][:12],
                            "money_values": chunk_refs["money_mentions"][:12],
                            "roles": [],
                            "topic_tags": tags[:8],
                            "legal_action_tags": [doc_type],
                            "effective_start_date": chunk_effective_start_date,
                            "effective_end_date": chunk_effective_end_date,
                            "is_current_version": chunk_is_current_version,
                            "version_lineage_id": canonical_doc_id,
                            "canonical_concept_id": canonical_concept_id,
                            "historical_relation_type": chunk_historical_relation_type,
                            "exact_terms": chunk_refs["article_refs"][:6] + chunk_refs["law_refs"][:6],
                            "search_keywords": tags[:6] + chunk_refs["entities"][:4],
                            "rank_hints": [doc_type, section_kind],
                            "answer_candidate_types": [doc_type],
                            "confidence_score": round(max(0.3, classification_confidence), 4),
                            "parser_flags": (
                                (["low_text_quality"] if low_quality_text else [])
                                + (["has_effective_end_date"] if chunk_effective_end_date else [])
                            ),
                            "extraction_method": "rules_stub",
                            "tagging_model_version": "rules-v1",
                            "last_tagged_at": ingested_at,
                        }
                    )

                    if doc_type == "law":
                        law_chunk_facets.append(
                            {
                                "chunk_id": paragraph_id,
                                "law_number": law_number,
                                "law_year": year,
                                "article_number": article_number,
                                "article_number_normalized": article_number,
                                "article_title": chunk_refs["article_refs"][0] if chunk_refs["article_refs"] else None,
                                "section_ref": chunk_refs["article_refs"][0] if chunk_refs["article_refs"] else None,
                                "provision_kind": provision_kind,
                                "administering_authority": refs["entities"][0] if refs["entities"] else None,
                                "amends_law_ids": refs["law_refs"][:4],
                                "amended_by_doc_ids": [],
                            }
                        )
                    elif doc_type == "regulation":
                        regulation_chunk_facets.append(
                            {
                                "chunk_id": paragraph_id,
                                "regulation_number": law_number,
                                "regulation_year": year,
                                "regulation_type": "regulation",
                                "enabled_by_law_id": refs["law_refs"][0] if refs["law_refs"] else None,
                                "enabled_by_article_refs": refs["article_refs"][:6],
                                "provision_number": article_number,
                                "provision_kind": provision_kind,
                                "regulated_entities": chunk_refs["entities"][:8],
                                "compliance_subjects": tags[:5],
                                "reporting_requirement_present": "report" in chunk.lower(),
                                "filing_requirement_present": "file" in chunk.lower(),
                            }
                        )
                    elif doc_type == "enactment_notice":
                        enactment_notice_chunk_facets.append(
                            {
                                "chunk_id": paragraph_id,
                                "notice_number": law_number,
                                "notice_year": year,
                                "target_doc_id": refs["law_refs"][0] if refs["law_refs"] else None,
                                "target_law_number": law_number,
                                "target_article_refs": refs["article_refs"][:8],
                                "excluded_article_refs": [],
                                "commencement_scope_type": "partial" if refs["article_refs"] else "full",
                                "commencement_date": issued_date,
                                "rule_type": "commence",
                                "condition_text_present": "condition" in chunk.lower(),
                            }
                        )
                    elif doc_type == "case":
                        case_chunk_facets.append(
                            {
                                "chunk_id": paragraph_id,
                                "case_number": case_id,
                                "neutral_citation": case_id,
                                "court_name": refs["entities"][0] if refs["entities"] else None,
                                "court_level": "unknown",
                                "decision_date": issued_date,
                                "section_kind_case": "reasoning",
                                "party_names": chunk_refs["entities"][:8],
                                "party_roles_present": [],
                                "judge_names": chunk_refs["entities"][:2],
                                "presiding_judge": chunk_refs["entities"][0] if chunk_refs["entities"] else None,
                                "claim_amounts": chunk_refs["money_mentions"][:6],
                                "relief_sought": [],
                                "disposition_label": "unknown",
                                "outcome_side": None,
                                "cited_law_ids": chunk_refs["law_refs"][:6],
                                "cited_case_ids": chunk_refs["case_refs"][:6],
                            }
                        )

                    chunk_search_documents.append(
                        {
                            "chunk_id": paragraph_id,
                            "document_id": document_id,
                            "pdf_id": pdf_id,
                            "page_id": page_id,
                            "page_number": page_num,
                            "doc_type": doc_type,
                            "title_normalized": title_normalized,
                            "short_title": title[:80],
                            "jurisdiction": "unknown",
                            "status": "parsed",
                            "is_current_version": chunk_is_current_version,
                            "effective_start_date": chunk_effective_start_date,
                            "effective_end_date": chunk_effective_end_date,
                            "heading_path": [doc_type, parse_policy],
                            "section_kind": section_kind,
                            "text_clean": chunk[:1400],
                            "retrieval_text": retrieval_text[:1800],
                            "entity_names": chunk_refs["entities"][:12],
                            "article_refs": chunk_refs["article_refs"][:12],
                            "dates": chunk_refs["dates"][:12],
                            "money_values": chunk_refs["money_mentions"][:12],
                            "exact_terms": chunk_refs["article_refs"][:6] + chunk_refs["law_refs"][:6],
                            "search_keywords": tags[:6] + chunk_refs["entities"][:4],
                            "version_lineage_id": canonical_doc_id,
                            "canonical_concept_id": canonical_concept_id,
                            "historical_relation_type": chunk_historical_relation_type,
                            "law_number": law_number if doc_type == "law" else None,
                            "law_year": year if doc_type == "law" else None,
                            "regulation_number": law_number if doc_type == "regulation" else None,
                            "regulation_year": year if doc_type == "regulation" else None,
                            "notice_number": law_number if doc_type == "enactment_notice" else None,
                            "notice_year": year if doc_type == "enactment_notice" else None,
                            "case_number": case_id if doc_type == "case" else None,
                            "court_name": refs["entities"][0] if doc_type == "case" and refs["entities"] else None,
                            "decision_date": issued_date if doc_type == "case" else None,
                            "article_number": article_number,
                            "section_ref": chunk_refs["article_refs"][0] if chunk_refs["article_refs"] else None,
                            "schedule_number": None,
                            "provision_kind": provision_kind,
                            "administering_authority": refs["entities"][0] if doc_type == "law" and refs["entities"] else None,
                            "enabled_by_law_id": refs["law_refs"][0] if doc_type == "regulation" and refs["law_refs"] else None,
                            "target_doc_id": refs["law_refs"][0] if doc_type == "enactment_notice" and refs["law_refs"] else None,
                            "target_article_refs": refs["article_refs"][:8] if doc_type == "enactment_notice" else [],
                            "commencement_date": issued_date if doc_type == "enactment_notice" else None,
                            "commencement_scope_type": "partial" if doc_type == "enactment_notice" and refs["article_refs"] else "full" if doc_type == "enactment_notice" else None,
                            "judge_names": chunk_refs["entities"][:2] if doc_type == "case" else [],
                            "party_names_normalized": [value.lower() for value in chunk_refs["entities"][:6]] if doc_type == "case" else [],
                            "final_disposition": "unknown" if doc_type == "case" else None,
                            "edge_types": edge_types,
                        }
                    )

                    for law_ref_index, law_ref in enumerate(chunk_refs["law_refs"][:6]):
                        relation_edges.append(
                            {
                                "edge_id": _stable_id(
                                    "edge",
                                    paragraph_id,
                                    "law",
                                    law_ref_index,
                                    law_ref,
                                ),
                                "source_object_type": "chunk",
                                "source_object_id": paragraph_id,
                                "target_object_type": "document",
                                "target_object_id": law_ref,
                                "edge_type": "enabled_by" if doc_type == "regulation" else "refers_to",
                                "confidence_score": round(classification_confidence, 4),
                                "source_page_id": source_page_id,
                                "created_by": "ingest_stub",
                            }
                        )
                    for case_ref_index, case_ref in enumerate(chunk_refs["case_refs"][:4]):
                        relation_edges.append(
                            {
                                "edge_id": _stable_id(
                                    "edge",
                                    paragraph_id,
                                    "case",
                                    case_ref_index,
                                    case_ref,
                                ),
                                "source_object_type": "chunk",
                                "source_object_id": paragraph_id,
                                "target_object_type": "document",
                                "target_object_id": case_ref,
                                "edge_type": "cites",
                                "confidence_score": round(classification_confidence, 4),
                                "source_page_id": source_page_id,
                                "created_by": "ingest_stub",
                            }
                        )
                    page_paragraph_index += 1

    _apply_family_versioning(docs, document_bases)

    return {
        "documents": docs,
        "document_bases": document_bases,
        "law_documents": law_documents,
        "regulation_documents": regulation_documents,
        "enactment_notice_documents": enactment_notice_documents,
        "case_documents": case_documents,
        "pages": pages,
        "paragraphs": paragraphs,
        "chunk_bases": chunk_bases,
        "law_chunk_facets": law_chunk_facets,
        "regulation_chunk_facets": regulation_chunk_facets,
        "enactment_notice_chunk_facets": enactment_notice_chunk_facets,
        "case_chunk_facets": case_chunk_facets,
        "relation_edges": relation_edges,
        "chunk_search_documents": chunk_search_documents,
    }


def build_ingest_diagnostics(result: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    documents = list(result.get("documents", []))
    pages = list(result.get("pages", []))
    paragraphs = list(result.get("paragraphs", []))
    relation_edges = list(result.get("relation_edges", []))

    pages_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for page in pages:
        pages_by_doc.setdefault(str(page.get("document_id", "")), []).append(page)

    paragraphs_by_page: Dict[str, List[Dict[str, Any]]] = {}
    for paragraph in paragraphs:
        paragraphs_by_page.setdefault(str(paragraph.get("page_id", "")), []).append(paragraph)

    document_rows: List[Dict[str, Any]] = []
    for document in sorted(
        documents,
        key=lambda row: (
            str(row.get("canonical_doc_id", "")),
            str(row.get("document_id", "")),
        ),
    ):
        processing = document.get("processing") if isinstance(document.get("processing"), dict) else {}
        doc_id = str(document.get("document_id", ""))
        doc_pages = sorted(
            pages_by_doc.get(doc_id, []),
            key=lambda row: (
                int(row.get("page_num", 0) or 0),
                str(row.get("page_id", "")),
            ),
        )
        page_artifacts: List[Dict[str, Any]] = []
        paragraph_count = 0
        for page in doc_pages:
            page_id = str(page.get("page_id", ""))
            page_paragraphs = sorted(
                paragraphs_by_page.get(page_id, []),
                key=lambda row: (
                    int(row.get("paragraph_index", 0) or 0),
                    str(row.get("paragraph_id", "")),
                ),
            )
            paragraph_ids = [str(item.get("paragraph_id", "")) for item in page_paragraphs]
            paragraph_count += len(paragraph_ids)
            page_artifacts.append(
                {
                    "page_id": page_id,
                    "source_page_id": str(page.get("source_page_id", "")),
                    "page_num": int(page.get("page_num", 0) or 0),
                    "paragraph_count": len(paragraph_ids),
                    "paragraph_fingerprint": _stable_digest(paragraph_ids),
                }
            )

        artifact_fingerprint = _stable_digest(
            doc_id,
            str(document.get("canonical_doc_id", "")),
            page_artifacts,
        )
        document_rows.append(
            {
                "document_id": doc_id,
                "canonical_doc_id": str(document.get("canonical_doc_id", "")),
                "pdf_id": str(document.get("pdf_id", "")),
                "content_hash": str(document.get("content_hash", "")),
                "duplicate_group_id": document.get("duplicate_group_id"),
                "page_count": int(document.get("page_count", 0) or 0),
                "paragraph_count": paragraph_count,
                "parse_warning": processing.get("parse_warning"),
                "parse_error": processing.get("parse_error"),
                "text_quality_score": processing.get("text_quality_score"),
                "artifact_fingerprint": artifact_fingerprint,
                "page_artifacts": page_artifacts,
            }
        )

    summary = {
        "documents": len(documents),
        "pages": len(pages),
        "paragraphs": len(paragraphs),
        "relation_edges": len(relation_edges),
        "duplicate_documents": sum(1 for row in document_rows if row.get("duplicate_group_id")),
        "parse_errors": sum(1 for row in document_rows if row.get("parse_error")),
        "parse_warnings": sum(1 for row in document_rows if row.get("parse_warning")),
    }

    identity_fingerprint = _stable_digest(
        [
            {
                "document_id": row["document_id"],
                "canonical_doc_id": row["canonical_doc_id"],
                "pdf_id": row["pdf_id"],
                "content_hash": row["content_hash"],
                "page_artifacts": row["page_artifacts"],
            }
            for row in document_rows
        ]
    )
    artifact_fingerprint = _stable_digest([row["artifact_fingerprint"] for row in document_rows])

    return {
        "diagnostics_version": "ingest_diagnostics_v1",
        "summary": summary,
        "identity_fingerprint": identity_fingerprint,
        "artifact_fingerprint": artifact_fingerprint,
        "documents": document_rows,
    }


def compact_ingest_diagnostics(diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    rows = diagnostics.get("documents")
    if not isinstance(rows, list):
        rows = []
    compact_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        compact_rows.append(
            {
                "document_id": row.get("document_id"),
                "canonical_doc_id": row.get("canonical_doc_id"),
                "pdf_id": row.get("pdf_id"),
                "duplicate_group_id": row.get("duplicate_group_id"),
                "page_count": row.get("page_count"),
                "paragraph_count": row.get("paragraph_count"),
                "artifact_fingerprint": row.get("artifact_fingerprint"),
            }
        )
    return {
        "diagnostics_version": diagnostics.get("diagnostics_version"),
        "summary": diagnostics.get("summary", {}),
        "identity_fingerprint": diagnostics.get("identity_fingerprint"),
        "artifact_fingerprint": diagnostics.get("artifact_fingerprint"),
        "documents": compact_rows,
    }


def run_deterministic_ingest(
    *,
    blob_url: str,
    project_id: str,
    parse_policy: str,
    dedupe_enabled: bool,
) -> Dict[str, Any]:
    corpus_project_id = resolve_corpus_import_project_id(project_id)
    result = ingest_zip_stub(
        blob_url=blob_url,
        project_id=corpus_project_id,
        parse_policy=parse_policy,
        dedupe_enabled=dedupe_enabled,
    )
    diagnostics = build_ingest_diagnostics(result)
    return {"result": result, "diagnostics": diagnostics}


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic ingest helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    deterministic = sub.add_parser("deterministic", help="Run deterministic ingest and print diagnostics baseline")
    deterministic.add_argument("--project-id", default="")
    deterministic.add_argument("--blob-url", required=True)
    deterministic.add_argument("--parse-policy", default="balanced")
    deterministic.add_argument("--dedupe-enabled", action="store_true", default=True)
    deterministic.add_argument("--no-dedupe", dest="dedupe_enabled", action="store_false")
    deterministic.add_argument("--output", default="")
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    if args.command != "deterministic":
        parser.error(f"unsupported command: {args.command}")

    payload = run_deterministic_ingest(
        blob_url=str(args.blob_url),
        project_id=str(args.project_id),
        parse_policy=str(args.parse_policy),
        dedupe_enabled=bool(args.dedupe_enabled),
    )
    corpus_project_id = resolve_corpus_import_project_id(args.project_id)
    rendered = json.dumps(
        {
            "command": "deterministic",
            "project_id": corpus_project_id,
            "blob_url": str(args.blob_url),
            "parse_policy": str(args.parse_policy),
            "dedupe_enabled": bool(args.dedupe_enabled),
            "diagnostics": payload["diagnostics"],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{rendered}\n", encoding="utf-8")
    sys.stdout.write(f"{rendered}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
