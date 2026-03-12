"""Offline title-page metadata normalization and case-family relation resolution."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from legal_rag_api.azure_llm import AzureLLMClient, AzureOpenAIConfig


NORMALIZATION_PROFILE_VERSION = "corpus_metadata_normalizer_v3"
TITLE_PAGE_PROMPT_SET_VERSION = "corpus_typed_title_identity_prompt_set_v1"
CASE_RELATION_PROMPT_VERSION = "corpus_case_relation_resolver_v1"
_ALLOWED_DOC_TYPES = {"law", "regulation", "enactment_notice", "case", "other"}
_ALLOWED_CASE_ROLES = {"judgment", "order", "reasons", "permission", "appeal", "other"}
_ALLOWED_CASE_RELATIONS = {"order_for", "reasons_for", "appeal_in", "permission_for", "related"}
_LEGISLATIVE_DOC_TYPES = {"law", "regulation", "enactment_notice"}
_PLACEHOLDER_TITLE_PATTERN = re.compile(r"(?i)^document\s+[a-z0-9._-]{8,}$")
_STRONG_CASE_ID_PATTERN = re.compile(
    r"\b((?:CA|CFI|DEC|ARB|ENF|TCD|S\s*CT|SCT)\s+\d{1,4}/(?:19|20)\d{2}(?:/\d+)?|"
    r"(?:CA|CFI|DEC|ARB|ENF|TCD|SCT)-\d{1,4}-(?:19|20)\d{2}(?:/\d+)?)\b",
    flags=re.IGNORECASE,
)
_CASE_ID_FALLBACK_PATTERN = re.compile(
    r"(?:CA|CFI|DEC|ARB|ENF|TCD|S\s*CT|SCT)\s+\d{1,4}/(?:19|20)\d{2}(?:/\d+)?|"
    r"(?:CA|CFI|DEC|ARB|ENF|TCD|SCT)-\d{1,4}-(?:19|20)\d{2}(?:/\d+)?",
    flags=re.IGNORECASE,
)
_CASE_TYPE_SPECIFIC_KEYS = {
    "case_number",
    "neutral_citation",
    "court_name",
    "court_level",
    "decision_date",
    "judgment_date",
    "claimant_names",
    "respondent_names",
    "appellant_names",
    "defendant_names",
    "judge_names",
    "presiding_judge",
    "procedural_stage",
}
_CASE_PROCESSING_CANDIDATE_KEYS = {
    "claim_number",
    "appeal_number",
    "document_role",
    "same_case_anchor_candidate",
}
_TYPE_SPECIFIC_KEYS_BY_DOC_TYPE = {
    "law": {
        "law_number",
        "law_year",
        "instrument_kind",
        "administering_authority",
        "promulgation_date",
        "commencement_date",
        "last_consolidated_date",
    },
    "regulation": {
        "regulation_number",
        "regulation_year",
        "regulation_type",
        "issuing_authority",
        "enabled_by_law_title",
        "status",
        "is_current_version",
    },
    "enactment_notice": {
        "notice_number",
        "notice_year",
        "notice_type",
        "issuing_authority",
        "target_title",
        "target_law_number",
        "target_law_year",
        "commencement_scope_type",
        "commencement_date",
    },
    "case": _CASE_TYPE_SPECIFIC_KEYS,
    "other": set(),
}
_PROCESSING_CANDIDATE_KEYS_BY_DOC_TYPE = {
    "law": {
        "consolidated_version_number",
        "consolidated_version_date",
        "enabled_by_law_number",
        "enabled_by_law_year",
        "family_anchor_candidate",
        "title_page_amending_law_refs",
    },
    "regulation": {
        "consolidated_version_number",
        "consolidated_version_date",
        "enabled_by_law_number",
        "enabled_by_law_year",
        "family_anchor_candidate",
        "title_page_amending_law_refs",
    },
    "enactment_notice": {"family_anchor_candidate"},
    "case": _CASE_PROCESSING_CANDIDATE_KEYS,
    "other": {"router_reason"},
}
_NEGATIVE_REVIEW_REASON_PATTERN = re.compile(
    r"(?i)\bno issues identified\b|\bno further review needed\b|\bno issues identified that require manual review\b"
)
_UNCERTAINTY_REVIEW_REASON_PATTERN = re.compile(
    r"(?i)\bmissing\b|\bambiguous\b|\bunclear\b|\binsufficient\b|\bfurther review\b|\bnot provided\b|"
    r"\bnot enough\b|\bcannot\b|\bunable\b|\bconflict\b|\bmultiple\b|\brequires manual review\b"
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(json.dumps(part, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
        hasher.update(b"\x1f")
    return f"{prefix}_{hasher.hexdigest()[:24]}"


def _load_prompt_markdown(name: str) -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "packages" / "prompts" / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _title_prompt_name(doc_type: str) -> str:
    normalized = str(doc_type or "").strip().lower()
    return {
        "law": "corpus_law_title_identity_v1",
        "regulation": "corpus_regulation_title_identity_v1",
        "enactment_notice": "corpus_enactment_notice_title_identity_v1",
        "case": "corpus_case_title_identity_v1",
    }.get(normalized, "corpus_other_title_router_v1")


def _title_schema_hint(doc_type: str) -> str:
    normalized = str(doc_type or "").strip().lower()
    if normalized == "law":
        return json.dumps(
            {
                "canonical_document": {
                    "doc_type": "law",
                    "title_raw": None,
                    "title_normalized": None,
                    "short_title": None,
                    "citation_title": None,
                    "language": None,
                    "jurisdiction": None,
                    "issued_date": None,
                    "effective_start_date": None,
                    "effective_end_date": None,
                    "ocr_used": False,
                    "extraction_confidence": 0.0,
                },
                "type_specific_document": {
                    "law_number": None,
                    "law_year": None,
                    "instrument_kind": None,
                    "administering_authority": None,
                    "promulgation_date": None,
                    "commencement_date": None,
                    "last_consolidated_date": None,
                },
                "processing_candidates": {
                    "consolidated_version_number": None,
                    "consolidated_version_date": None,
                    "enabled_by_law_number": None,
                    "enabled_by_law_year": None,
                    "family_anchor_candidate": None,
                    "title_page_amending_law_refs": [],
                },
                "review": {
                    "manual_review_required": False,
                    "manual_review_reasons": [],
                },
            },
            ensure_ascii=False,
        )
    if normalized == "regulation":
        return json.dumps(
            {
                "canonical_document": {
                    "doc_type": "regulation",
                    "title_raw": None,
                    "title_normalized": None,
                    "short_title": None,
                    "citation_title": None,
                    "language": None,
                    "jurisdiction": None,
                    "issued_date": None,
                    "effective_start_date": None,
                    "effective_end_date": None,
                    "ocr_used": False,
                    "extraction_confidence": 0.0,
                },
                "type_specific_document": {
                    "regulation_number": None,
                    "regulation_year": None,
                    "regulation_type": None,
                    "issuing_authority": None,
                    "enabled_by_law_title": None,
                    "status": None,
                    "is_current_version": None,
                },
                "processing_candidates": {
                    "consolidated_version_number": None,
                    "consolidated_version_date": None,
                    "enabled_by_law_number": None,
                    "enabled_by_law_year": None,
                    "family_anchor_candidate": None,
                    "title_page_amending_law_refs": [],
                },
                "review": {
                    "manual_review_required": False,
                    "manual_review_reasons": [],
                },
            },
            ensure_ascii=False,
        )
    if normalized == "enactment_notice":
        return json.dumps(
            {
                "canonical_document": {
                    "doc_type": "enactment_notice",
                    "title_raw": None,
                    "title_normalized": None,
                    "short_title": None,
                    "citation_title": None,
                    "language": None,
                    "jurisdiction": None,
                    "issued_date": None,
                    "effective_start_date": None,
                    "effective_end_date": None,
                    "ocr_used": False,
                    "extraction_confidence": 0.0,
                },
                "type_specific_document": {
                    "notice_number": None,
                    "notice_year": None,
                    "notice_type": None,
                    "issuing_authority": None,
                    "target_title": None,
                    "target_law_number": None,
                    "target_law_year": None,
                    "commencement_scope_type": None,
                    "commencement_date": None,
                },
                "processing_candidates": {
                    "family_anchor_candidate": None,
                },
                "review": {
                    "manual_review_required": False,
                    "manual_review_reasons": [],
                },
            },
            ensure_ascii=False,
        )
    if normalized == "case":
        return json.dumps(
            {
                "canonical_document": {
                    "doc_type": "case",
                    "title_raw": None,
                    "title_normalized": None,
                    "short_title": None,
                    "citation_title": None,
                    "language": None,
                    "jurisdiction": None,
                    "issued_date": None,
                    "effective_start_date": None,
                    "effective_end_date": None,
                    "ocr_used": False,
                    "extraction_confidence": 0.0,
                },
                "type_specific_document": {
                    "case_number": None,
                    "neutral_citation": None,
                    "court_name": None,
                    "court_level": None,
                    "decision_date": None,
                    "judgment_date": None,
                    "claimant_names": [],
                    "respondent_names": [],
                    "appellant_names": [],
                    "defendant_names": [],
                    "judge_names": [],
                    "presiding_judge": None,
                    "procedural_stage": None,
                },
                "processing_candidates": {
                    "claim_number": None,
                    "appeal_number": None,
                    "document_role": None,
                    "same_case_anchor_candidate": None,
                },
                "review": {
                    "manual_review_required": False,
                    "manual_review_reasons": [],
                },
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "canonical_document": {
                "doc_type": "other",
                "title_raw": None,
                "title_normalized": None,
                "short_title": None,
                "citation_title": None,
                "language": None,
                "jurisdiction": None,
                "issued_date": None,
                "effective_start_date": None,
                "effective_end_date": None,
                "ocr_used": False,
                "extraction_confidence": 0.0,
            },
            "type_specific_document": {},
            "processing_candidates": {},
            "review": {
                "manual_review_required": False,
                "manual_review_reasons": [],
            },
        },
        ensure_ascii=False,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalizer_cache_dir() -> Path:
    override = (os.getenv("CORPUS_METADATA_NORMALIZER_CACHE_DIR") or "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        path = _repo_root() / "reports" / "cache" / "corpus_metadata_normalizer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _request_spacing_seconds() -> float:
    raw = (os.getenv("CORPUS_METADATA_NORMALIZER_REQUEST_SPACING_SECONDS") or "").strip()
    try:
        return max(0.0, float(raw)) if raw else 2.5
    except ValueError:
        return 2.5


def _retry_limit() -> int:
    raw = (os.getenv("CORPUS_METADATA_NORMALIZER_RETRY_LIMIT") or "").strip()
    try:
        return max(1, int(raw)) if raw else 6
    except ValueError:
        return 6


def _retry_delay_seconds(attempt: int) -> float:
    raw = (os.getenv("CORPUS_METADATA_NORMALIZER_RETRY_BASE_SECONDS") or "").strip()
    try:
        base = max(0.1, float(raw)) if raw else 5.0
    except ValueError:
        base = 5.0
    return min(60.0, base * (2 ** max(0, attempt)))


def build_metadata_normalizer_client() -> AzureLLMClient:
    config = AzureOpenAIConfig.from_env()
    provider_override = (os.getenv("CORPUS_METADATA_NORMALIZER_PROVIDER") or "").strip().lower()
    if provider_override in {"azure", "openai"}:
        config.provider = provider_override
    deployment_override = (os.getenv("CORPUS_METADATA_NORMALIZER_DEPLOYMENT") or "").strip()
    model_override = (os.getenv("CORPUS_METADATA_NORMALIZER_MODEL") or "").strip()
    token_parameter_override = (os.getenv("CORPUS_METADATA_NORMALIZER_TOKEN_PARAMETER") or "").strip()
    reasoning_effort_override = (os.getenv("CORPUS_METADATA_NORMALIZER_REASONING_EFFORT") or "").strip()
    timeout_override = (os.getenv("CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS") or "").strip()
    max_tokens_override = (os.getenv("CORPUS_METADATA_NORMALIZER_MAX_TOKENS") or "").strip()
    if config.provider == "azure":
        if deployment_override:
            config.deployment = deployment_override
    else:
        if model_override:
            config.model = model_override
    selected_model_name = deployment_override or model_override or config.deployment or config.model or ""
    if selected_model_name.lower().startswith("gpt-5") and not reasoning_effort_override:
        config.reasoning_effort = "minimal"
        config.token_parameter = "max_completion_tokens"
    if reasoning_effort_override:
        config.reasoning_effort = reasoning_effort_override
        if not token_parameter_override:
            config.token_parameter = "max_completion_tokens"
    if token_parameter_override in {"max_tokens", "max_completion_tokens"}:
        config.token_parameter = token_parameter_override
    if timeout_override:
        try:
            config.timeout_seconds = float(timeout_override)
        except ValueError:
            pass
    if max_tokens_override:
        try:
            config.max_tokens = int(max_tokens_override)
        except ValueError:
            pass
    return AzureLLMClient(config=config)


def _rate_limit_error(exc: Exception) -> bool:
    return "429" in str(exc)


def _sleep(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)


def _cache_path(kind: str, key: str) -> Path:
    return _normalizer_cache_dir() / kind / f"{key}.json"


def _read_cache(kind: str, key: str) -> Dict[str, Any] | None:
    path = _cache_path(kind, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache(kind: str, key: str, payload: Dict[str, Any]) -> None:
    path = _cache_path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _compact_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def _normalize_date(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return f"{text}-01-01"

    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", text)
    if match:
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    match = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b", text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        day = int(match.group(2))
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _parse_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _normalize_case_identifier(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().upper())
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\bS\s*CT\b", "S CT", normalized)
    return normalized


def _case_family_anchor(value: str) -> str:
    candidate = _normalize_case_identifier(value)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", candidate.lower()).strip("_")


def _looks_like_case_identifier(value: Any) -> bool:
    candidate = _normalize_case_identifier(str(value or ""))
    if not candidate:
        return False
    return bool(_STRONG_CASE_ID_PATTERN.fullmatch(candidate))


def _extract_case_identifier_from_text(text: str) -> str | None:
    source = str(text or "").replace("_", " ")
    patterns = (
        re.compile(
            r"(?i)\b(?:claim|case|appeal)\s+no\.?\s*:?\s*"
            r"((?:CA|CFI|DEC|ARB|ENF|TCD|S\s*CT|SCT)\s+\d{1,4}/(?:19|20)\d{2}(?:/\d+)?|"
            r"(?:CA|CFI|DEC|ARB|ENF|TCD|SCT)-\d{1,4}-(?:19|20)\d{2}(?:/\d+)?)"
        ),
        _CASE_ID_FALLBACK_PATTERN,
    )
    for pattern in patterns:
        match = pattern.search(source)
        if not match:
            continue
        candidate = _normalize_case_identifier(match.group(1) if match.groups() else match.group(0))
        if _looks_like_case_identifier(candidate):
            return candidate
    return None


def _extract_title_page_amending_law_refs(text: str) -> List[Dict[str, Any]]:
    source = str(text or "").replace("_", " ")
    signals = ("is amended by", "as amended by", "laws amendment law", "amending law")
    if not any(signal in source.lower() for signal in signals):
        return []
    pattern = re.compile(
        r"(?i)(?:as amended by|is amended by|laws amendment law|amending law)\s+"
        r"((?:[A-Za-z][A-Za-z0-9&'()/-]*\s+){0,10}?"
        r"law\s+(?:difc\s+)?law\s+no\.?\s*([A-Za-z0-9./-]{1,24})\s+of\s+((?:19|20)\d{2}))"
    )
    refs: List[Dict[str, Any]] = []
    for index, match in enumerate(pattern.finditer(source), start=1):
        title = _compact_text(match.group(1), 200)
        law_number = str(match.group(2) or "").strip()
        year = str(match.group(3) or "").strip()
        refs.append(
            {
                "title": title or None,
                "law_number": law_number or None,
                "law_year": int(year) if year.isdigit() else None,
                "reference_phrase": _compact_text(match.group(0), 240),
                "order_index": index,
            }
        )
    return refs


def _case_role_from_text(text: str) -> str:
    lowered = (text or "").lower()
    heading = lowered[:500]
    if "order with reasons" in heading or ("orders" in heading and "reasons" in heading):
        return "reasons"
    if re.search(r"\borders?\b", heading):
        return "order"
    if re.search(r"\bjudgments?\b", heading):
        return "judgment"
    if "permission" in heading and "appeal" in heading:
        return "permission"
    if "appeal" in heading and "order" in heading:
        return "appeal"
    return "other"


def _merge_string(current: Any, incoming: Any) -> Any:
    candidate = str(incoming or "").strip()
    if not candidate:
        return current
    return candidate


def _merge_bool(current: Any, incoming: Any) -> Any:
    if incoming is None:
        return current
    return bool(incoming)


def _merge_float(current: Any, incoming: Any) -> Any:
    try:
        if incoming is None:
            return current
        value = float(incoming)
        return max(0.0, min(1.0, value))
    except Exception:
        return current


def _merge_int(current: Any, incoming: Any) -> Any:
    try:
        if incoming is None:
            return current
        return int(incoming)
    except Exception:
        return current


def _merge_list(current: Any, incoming: Any) -> Any:
    if not isinstance(incoming, list):
        return current
    out: List[Any] = []
    seen = set()
    for item in incoming:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _is_placeholder_title(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return bool(_PLACEHOLDER_TITLE_PATTERN.fullmatch(text))


def _seed_title_value(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _is_placeholder_title(text):
        return None
    return text


def _sanitize_reason_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    seen = set()
    for item in value:
        reason = str(item or "").strip()
        if not reason or reason in seen:
            continue
        seen.add(reason)
        out.append(reason)
    return out


def _reason_requires_manual_review(reason: str, *, doc_type: str) -> bool:
    text = str(reason or "").strip()
    if not text:
        return False
    if _NEGATIVE_REVIEW_REASON_PATTERN.search(text):
        return False
    if doc_type == "case" and re.search(r"(?i)\bcourt(?:/case)? document\b|\bcourt order\b|\bcase number\b", text):
        return bool(_UNCERTAINTY_REVIEW_REASON_PATTERN.search(text))
    return True


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _case_signals_from_payload(
    *,
    canonical_document: Dict[str, Any],
    type_specific_document: Dict[str, Any],
    processing_candidates: Dict[str, Any],
    context_text: str,
) -> bool:
    caseish_value = _first_non_empty(
        processing_candidates.get("same_case_anchor_candidate"),
        processing_candidates.get("claim_number"),
        processing_candidates.get("appeal_number"),
        type_specific_document.get("case_number"),
        type_specific_document.get("neutral_citation"),
        canonical_document.get("citation_title"),
        canonical_document.get("title_raw"),
        _extract_case_identifier_from_text(context_text),
    )
    if caseish_value and (
        _looks_like_case_identifier(caseish_value)
        or bool(re.search(r"\b(?:S\s*CT|TCD)\s+\d{1,4}/(?:19|20)\d{2}\b", _normalize_case_identifier(caseish_value)))
    ):
        return True
    lowered = str(context_text or "").lower()
    return bool(
        re.search(r"\bclaim\s+no\.?\b", lowered)
        or re.search(r"\bcourt\s+of\b", lowered)
        or re.search(r"\border with reasons\b", lowered)
        or re.search(r"\bv\s+[a-z]", lowered)
    )


def _has_legislative_number(type_specific_document: Dict[str, Any]) -> bool:
    return any(
        str(type_specific_document.get(key) or "").strip()
        for key in ("law_number", "regulation_number", "notice_number")
    )


def _case_type_specific_template(case_number: str | None, issued_date: str | None, role: str) -> Dict[str, Any]:
    return {
        "case_number": case_number,
        "neutral_citation": case_number,
        "court_name": None,
        "court_level": None,
        "decision_date": issued_date,
        "judgment_date": issued_date if role == "judgment" else None,
        "claimant_names": [],
        "respondent_names": [],
        "appellant_names": [],
        "defendant_names": [],
        "judge_names": [],
        "presiding_judge": None,
        "procedural_stage": role if role in _ALLOWED_CASE_ROLES else "other",
    }


def _case_processing_candidates_template(case_number: str | None, role: str) -> Dict[str, Any]:
    normalized_case_number = _normalize_case_identifier(case_number) if case_number else None
    return {
        "claim_number": normalized_case_number,
        "appeal_number": normalized_case_number if normalized_case_number and normalized_case_number.startswith("CA ") else None,
        "document_role": role if role in _ALLOWED_CASE_ROLES else "other",
        "same_case_anchor_candidate": _case_family_anchor(normalized_case_number) if normalized_case_number else None,
    }


def _prune_fields(section: Dict[str, Any], allowed: set[str]) -> Dict[str, Any]:
    return {key: value for key, value in section.items() if key in allowed}


def _merge_into_template(template: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = json.loads(json.dumps(template, ensure_ascii=False))
    for key, value in incoming.items():
        if key not in merged:
            continue
        current = merged.get(key)
        if isinstance(current, list):
            merged[key] = _merge_list(current, value)
        elif isinstance(current, bool):
            merged[key] = _merge_bool(current, value)
        elif isinstance(current, float):
            merged[key] = _merge_float(current, value)
        elif isinstance(current, int):
            merged[key] = _merge_int(current, value)
        elif key.endswith("_date") and isinstance(value, str):
            merged[key] = _normalize_date(value) or current
        else:
            merged[key] = _merge_string(current, value)
    return merged


def _sanitize_title_envelope(base: Dict[str, Any], merged: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = json.loads(json.dumps(merged, ensure_ascii=False))
    canonical_document = dict(sanitized.get("canonical_document") or {})
    type_specific_document = dict(sanitized.get("type_specific_document") or {})
    processing_candidates = dict(sanitized.get("processing_candidates") or {})
    review = dict(sanitized.get("review") or {})
    context = base.get("context") or {}
    context_text = f"{context.get('page_1_text', '')}\n{context.get('page_2_text', '')}".strip()
    base_doc_type = str(base.get("canonical_document", {}).get("doc_type", "")).strip().lower()
    doc_type = str(canonical_document.get("doc_type", "")).strip().lower()
    if doc_type not in _ALLOWED_DOC_TYPES:
        doc_type = base_doc_type if base_doc_type in _ALLOWED_DOC_TYPES else "other"

    derived_case_identifier = _first_non_empty(
        type_specific_document.get("case_number"),
        processing_candidates.get("claim_number"),
        processing_candidates.get("appeal_number"),
        type_specific_document.get("neutral_citation"),
        base.get("type_specific_document", {}).get("case_number"),
        base.get("processing_candidates", {}).get("claim_number"),
        base.get("processing_candidates", {}).get("appeal_number"),
        _extract_case_identifier_from_text(context_text),
    )
    if derived_case_identifier and _looks_like_case_identifier(derived_case_identifier):
        derived_case_identifier = _normalize_case_identifier(derived_case_identifier)
    else:
        derived_case_identifier = None
    case_like_signals = _case_signals_from_payload(
        canonical_document=canonical_document,
        type_specific_document=type_specific_document,
        processing_candidates=processing_candidates,
        context_text=context_text,
    )

    if (
        doc_type in _LEGISLATIVE_DOC_TYPES | {"other"}
        and not _has_legislative_number(type_specific_document)
        and case_like_signals
    ):
        doc_type = "case"
    elif doc_type not in _LEGISLATIVE_DOC_TYPES and base_doc_type in _LEGISLATIVE_DOC_TYPES and _has_legislative_number(type_specific_document):
        doc_type = base_doc_type

    canonical_document["doc_type"] = doc_type
    if doc_type == "case":
        role = str(processing_candidates.get("document_role") or type_specific_document.get("procedural_stage") or "").strip().lower()
        if role not in _ALLOWED_CASE_ROLES:
            role = _case_role_from_text(context_text)
        case_template = _case_type_specific_template(
            derived_case_identifier,
            _normalize_date(str(type_specific_document.get("decision_date") or canonical_document.get("issued_date") or "")) or canonical_document.get("issued_date"),
            role,
        )
        case_template["court_name"] = _merge_string(case_template.get("court_name"), base.get("type_specific_document", {}).get("court_name"))
        case_template["court_level"] = _merge_string(case_template.get("court_level"), base.get("type_specific_document", {}).get("court_level"))
        type_specific_document = _merge_into_template(case_template, _prune_fields(type_specific_document, _CASE_TYPE_SPECIFIC_KEYS))
        candidate_template = _case_processing_candidates_template(derived_case_identifier, role)
        processing_candidates = _merge_into_template(
            candidate_template,
            _prune_fields(processing_candidates, _CASE_PROCESSING_CANDIDATE_KEYS),
        )
        derived_anchor = _first_non_empty(
            processing_candidates.get("same_case_anchor_candidate"),
            _case_family_anchor(derived_case_identifier) if derived_case_identifier else None,
        )
        processing_candidates["same_case_anchor_candidate"] = _case_family_anchor(derived_anchor) if derived_anchor else None
        processing_candidates["claim_number"] = _merge_string(processing_candidates.get("claim_number"), derived_case_identifier)
        if derived_case_identifier and derived_case_identifier.startswith("CA "):
            processing_candidates["appeal_number"] = _merge_string(processing_candidates.get("appeal_number"), derived_case_identifier)
        type_specific_document["case_number"] = _merge_string(type_specific_document.get("case_number"), derived_case_identifier)
        type_specific_document["neutral_citation"] = _merge_string(type_specific_document.get("neutral_citation"), derived_case_identifier)
        type_specific_document["procedural_stage"] = role if role in _ALLOWED_CASE_ROLES else "other"
        canonical_document["effective_start_date"] = None
        canonical_document["effective_end_date"] = None
    else:
        allowed_specific = _TYPE_SPECIFIC_KEYS_BY_DOC_TYPE.get(doc_type, set())
        allowed_candidates = _PROCESSING_CANDIDATE_KEYS_BY_DOC_TYPE.get(doc_type, set())
        type_specific_document = _prune_fields(type_specific_document, allowed_specific)
        processing_candidates = _prune_fields(processing_candidates, allowed_candidates)

    reasons = [
        item
        for item in _sanitize_reason_list(review.get("manual_review_reasons"))
        if _reason_requires_manual_review(item, doc_type=doc_type)
    ]
    if doc_type == "case":
        reasons = [item for item in reasons if item != "missing_legislative_number"]
        if processing_candidates.get("same_case_anchor_candidate"):
            reasons = [item for item in reasons if item != "missing_case_anchor"]
        elif "missing_case_anchor" not in reasons:
            reasons.append("missing_case_anchor")
    elif doc_type in _LEGISLATIVE_DOC_TYPES:
        reasons = [item for item in reasons if item != "missing_case_anchor"]
        if _has_legislative_number(type_specific_document):
            reasons = [item for item in reasons if item != "missing_legislative_number"]
        elif "missing_legislative_number" not in reasons:
            reasons.append("missing_legislative_number")
    else:
        reasons = [item for item in reasons if item not in {"missing_case_anchor", "missing_legislative_number"}]

    review["manual_review_reasons"] = reasons
    review["manual_review_required"] = bool(reasons)
    sanitized["canonical_document"] = canonical_document
    sanitized["type_specific_document"] = type_specific_document
    sanitized["processing_candidates"] = processing_candidates
    sanitized["review"] = review
    return sanitized


def _stage_result(*, status: str, role: str, payload: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "role": role,
        "status": status,
        "payload": payload or {},
        "error": error,
        "updated_at": _utcnow().isoformat(),
    }


def _base_envelope(document: Dict[str, Any], pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    doc_type = str(document.get("doc_type", "other") or "other")
    first_page = pages[0] if pages else {}
    second_page = pages[1] if len(pages) > 1 else {}
    first_text = _compact_text(str(first_page.get("text", "") or ""), 2200)
    second_text = _compact_text(str(second_page.get("text", "") or ""), 1600)
    first_two = f"{first_text}\n{second_text}".strip()
    processing = document.get("processing") or {}
    title_page_amending_law_refs = _extract_title_page_amending_law_refs(first_two)

    canonical_document = {
        "doc_type": doc_type if doc_type in _ALLOWED_DOC_TYPES else "other",
        "title_raw": _seed_title_value(document.get("title_raw") or document.get("title")),
        "title_normalized": str(document.get("title_normalized") or "").strip() or None,
        "short_title": _seed_title_value(str(document.get("short_title") or document.get("title") or "")[:80]),
        "citation_title": _seed_title_value(document.get("citation_title") or document.get("title")),
        "language": str(document.get("language") or "unknown"),
        "jurisdiction": str(document.get("jurisdiction") or "unknown"),
        "issued_date": _normalize_date(str(document.get("issued_date") or "")) or None,
        "effective_start_date": _normalize_date(str(document.get("effective_start_date") or "")) or None,
        "effective_end_date": _normalize_date(str(document.get("effective_end_date") or "")) or None,
        "ocr_used": bool(document.get("ocr_used", False)),
        "extraction_confidence": float(document.get("extraction_confidence") or processing.get("classification_confidence") or 0.0),
    }

    processing_candidates: Dict[str, Any] = {}
    type_specific_document: Dict[str, Any] = {}

    if doc_type == "law":
        type_specific_document = {
            "law_number": document.get("law_number"),
            "law_year": document.get("year"),
            "instrument_kind": "law",
            "administering_authority": None,
            "promulgation_date": canonical_document["issued_date"],
            "commencement_date": canonical_document["effective_start_date"] or canonical_document["issued_date"],
            "last_consolidated_date": None,
        }
        processing_candidates = {
            "consolidated_version_number": None,
            "consolidated_version_date": None,
            "enabled_by_law_number": None,
            "enabled_by_law_year": None,
            "family_anchor_candidate": str(document.get("version_group_id") or "").split(":")[1] if ":" in str(document.get("version_group_id") or "") else None,
            "title_page_amending_law_refs": title_page_amending_law_refs,
        }
    elif doc_type == "regulation":
        type_specific_document = {
            "regulation_number": document.get("law_number"),
            "regulation_year": document.get("year"),
            "regulation_type": "regulation",
            "issuing_authority": None,
            "enabled_by_law_title": None,
            "status": "in_force" if document.get("is_current_version") else "repealed",
            "is_current_version": bool(document.get("is_current_version", True)),
        }
        processing_candidates = {
            "consolidated_version_number": None,
            "consolidated_version_date": None,
            "enabled_by_law_number": None,
            "enabled_by_law_year": None,
            "family_anchor_candidate": None,
            "title_page_amending_law_refs": title_page_amending_law_refs,
        }
    elif doc_type == "enactment_notice":
        type_specific_document = {
            "notice_number": document.get("law_number"),
            "notice_year": document.get("year"),
            "notice_type": "commencement_notice",
            "issuing_authority": None,
            "target_title": None,
            "target_law_number": document.get("law_number"),
            "target_law_year": document.get("year"),
            "commencement_scope_type": "partial" if processing.get("article_refs") else "full",
            "commencement_date": canonical_document["issued_date"],
        }
        processing_candidates = {
            "family_anchor_candidate": None,
        }
    elif doc_type == "case":
        role = _case_role_from_text(first_two)
        case_number = _normalize_case_identifier(str(document.get("case_id") or "")) if str(document.get("case_id") or "").strip() else None
        type_specific_document = _case_type_specific_template(case_number, canonical_document["issued_date"], role)
        processing_candidates = _case_processing_candidates_template(case_number, role)

    review = {
        "manual_review_required": False,
        "manual_review_reasons": [],
    }
    if canonical_document["doc_type"] in _LEGISLATIVE_DOC_TYPES and not _has_legislative_number(type_specific_document):
        review["manual_review_required"] = True
        review["manual_review_reasons"].append("missing_legislative_number")
    if canonical_document["doc_type"] == "case" and not processing_candidates.get("same_case_anchor_candidate"):
        review["manual_review_required"] = True
        review["manual_review_reasons"].append("missing_case_anchor")

    return {
        "canonical_document": canonical_document,
        "type_specific_document": type_specific_document,
        "processing_candidates": processing_candidates,
        "review": review,
        "context": {
            "page_1_text": first_text,
            "page_2_text": second_text,
            "source_page_ids": [str(page.get("source_page_id") or "") for page in pages[:2] if str(page.get("source_page_id") or "").strip()],
        },
    }


def _merge_title_envelope(base: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(llm_payload, dict):
        return _sanitize_title_envelope(base, base)
    merged = json.loads(json.dumps(base, ensure_ascii=False))

    for section in ("canonical_document", "type_specific_document", "processing_candidates", "review"):
        candidate = llm_payload.get(section)
        if not isinstance(candidate, dict):
            continue
        target = merged.setdefault(section, {})
        for key, value in candidate.items():
            current = target.get(key)
            if isinstance(current, list):
                target[key] = _merge_list(current, value)
            elif isinstance(current, bool):
                target[key] = _merge_bool(current, value)
            elif isinstance(current, float):
                target[key] = _merge_float(current, value)
            elif isinstance(current, int):
                target[key] = _merge_int(current, value)
            elif key.endswith("_date") and isinstance(value, str):
                target[key] = _normalize_date(value) or current
            else:
                target[key] = _merge_string(current, value)

    doc_type = str(merged.get("canonical_document", {}).get("doc_type", "")).strip().lower()
    if doc_type not in _ALLOWED_DOC_TYPES:
        merged["canonical_document"]["doc_type"] = base["canonical_document"]["doc_type"]
    role = str(merged.get("processing_candidates", {}).get("document_role", "")).strip().lower()
    if role and role not in _ALLOWED_CASE_ROLES:
        merged["processing_candidates"]["document_role"] = base["processing_candidates"].get("document_role")
    return _sanitize_title_envelope(base, merged)


def _title_page_prompt(envelope: Dict[str, Any], pdf_id: str) -> Tuple[str, str, str]:
    doc_type_hint = str(envelope.get("canonical_document", {}).get("doc_type") or "other").strip().lower()
    prompt_name = _title_prompt_name(doc_type_hint)
    guidance = _load_prompt_markdown(prompt_name)
    system_prompt = (
        "You extract structured metadata from legal document title pages. "
        "Return strict JSON only. Do not fabricate missing facts."
    )
    user_prompt = (
        f"Task: use the typed extraction contract `{prompt_name}`.\n"
        "The document type is already routed unless the evidence clearly contradicts it.\n"
        "Return strict JSON matching this schema template:\n"
        f"{_title_schema_hint(doc_type_hint)}\n\n"
        "Important constraints:\n"
        "- Extract facts only from page_1_text and page_2_text.\n"
        "- `review` is advisory only; use it only for blocking uncertainty, not for routine facts.\n"
        "- If the extracted identity is internally complete and consistent, leave review reasons empty.\n"
        "- For legislative documents, include title-page amendment references in `processing_candidates.title_page_amending_law_refs` when phrases such as `is amended by` or `as amended by` are present.\n\n"
        f"doc_type_hint: {doc_type_hint}\n"
        f"prompt_reference ({prompt_name}):\n{guidance[:2600]}\n\n"
        f"source_pdf_id: {pdf_id}\n\n"
        f"base_envelope:\n{json.dumps({k: v for k, v in envelope.items() if k != 'context'}, ensure_ascii=False)}\n\n"
        f"page_1_text:\n{envelope.get('context', {}).get('page_1_text', '')}\n\n"
        f"page_2_text:\n{envelope.get('context', {}).get('page_2_text', '')}\n"
    )
    return prompt_name, system_prompt, user_prompt


async def _run_title_page_llm(client: AzureLLMClient, *, envelope: Dict[str, Any], pdf_id: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    prompt_name, system_prompt, prompt = _title_page_prompt(envelope, pdf_id)
    completion, usage = await client.complete_chat(
        prompt,
        user_context={"task": "corpus_title_page_metadata_normalizer", "prompt_version": prompt_name, "pdf_id": pdf_id},
        system_prompt=system_prompt,
        max_tokens=700,
        temperature=None,
        top_p=None,
    )
    return _parse_json_object(completion), usage


def _title_page_llm(client: AzureLLMClient, *, envelope: Dict[str, Any], pdf_id: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    return asyncio.run(_run_title_page_llm(client, envelope=envelope, pdf_id=pdf_id))


def _resolve_case_relations_rules(group_key: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranked = sorted(
        docs,
        key=lambda item: (
            3 if item["document_role"] == "judgment" else 2 if item["document_role"] == "reasons" else 1 if item["document_role"] == "order" else 0,
            str(item.get("issued_date") or ""),
            str(item.get("document_id") or ""),
        ),
        reverse=True,
    )
    primary = ranked[0] if ranked else None
    relations: List[Dict[str, Any]] = []
    for item in ranked:
        if not primary or item["document_id"] == primary["document_id"]:
            continue
        role = item.get("document_role") or "other"
        relation_type = {
            "order": "order_for",
            "reasons": "reasons_for",
            "appeal": "appeal_in",
            "permission": "permission_for",
        }.get(role, "related")
        relations.append(
            {
                "source_document_id": item["document_id"],
                "target_document_id": primary["document_id"],
                "case_relation_type": relation_type,
                "confidence": 0.7,
            }
        )
    return {
        "case_family_id": group_key,
        "primary_merits_document_id": primary["document_id"] if primary else None,
        "document_role_confirmations": {item["document_id"]: item["document_role"] for item in ranked},
        "relations": relations,
        "family_review_required": False,
        "family_review_reasons": [],
    }


def _case_relation_prompt(group_key: str, docs: List[Dict[str, Any]]) -> Tuple[str, str]:
    guidance = _load_prompt_markdown(CASE_RELATION_PROMPT_VERSION)
    system_prompt = (
        "You resolve same-case document relations from normalized title-page metadata. "
        "Return strict JSON only."
    )
    user_prompt = (
        "Return JSON with keys "
        '{"case_family_id":"string|null","primary_merits_document_id":"string|null",'
        '"document_role_confirmations":{},"relations":[],"family_review_required":true,"family_review_reasons":[]}.\n\n'
        f"Prompt reference:\n{guidance[:1800]}\n\n"
        f"group_key: {group_key}\n\n"
        f"documents:\n{json.dumps(docs, ensure_ascii=False)}\n"
    )
    return system_prompt, user_prompt


async def _run_case_relation_llm(client: AzureLLMClient, *, group_key: str, docs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    system_prompt, prompt = _case_relation_prompt(group_key, docs)
    completion, usage = await client.complete_chat(
        prompt,
        user_context={"task": "corpus_case_relation_resolver", "prompt_version": CASE_RELATION_PROMPT_VERSION, "group_key": group_key},
        system_prompt=system_prompt,
        max_tokens=500,
        temperature=None,
        top_p=None,
    )
    return _parse_json_object(completion), usage


def _case_relation_llm(client: AzureLLMClient, *, group_key: str, docs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    return asyncio.run(_run_case_relation_llm(client, group_key=group_key, docs=docs))


def _title_cache_key(document: Dict[str, Any], envelope: Dict[str, Any], client: AzureLLMClient) -> str:
    prompt_name = _title_prompt_name(envelope.get("canonical_document", {}).get("doc_type"))
    return _stable_id(
        "title_cache",
        document.get("content_hash"),
        TITLE_PAGE_PROMPT_SET_VERSION,
        prompt_name,
        client.config.deployment or client.config.model or "disabled",
        envelope.get("context", {}).get("source_page_ids", []),
        envelope.get("canonical_document", {}).get("doc_type"),
    )


def _case_group_cache_key(group_key: str, docs: List[Dict[str, Any]], client: AzureLLMClient) -> str:
    compact_docs = [
        {
            "document_id": item.get("document_id"),
            "case_id": item.get("case_id"),
            "issued_date": item.get("issued_date"),
            "document_role": item.get("document_role"),
        }
        for item in sorted(docs, key=lambda row: str(row.get("document_id", "")))
    ]
    return _stable_id(
        "case_group_cache",
        group_key,
        CASE_RELATION_PROMPT_VERSION,
        client.config.deployment or client.config.model or "disabled",
        compact_docs,
    )


def _merge_case_resolution(base: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(llm_payload, dict):
        return base
    merged = json.loads(json.dumps(base, ensure_ascii=False))
    family_id = str(llm_payload.get("case_family_id", "")).strip()
    if family_id:
        merged["case_family_id"] = family_id
    primary_id = str(llm_payload.get("primary_merits_document_id", "")).strip()
    if primary_id:
        merged["primary_merits_document_id"] = primary_id
    confirmations = llm_payload.get("document_role_confirmations")
    if isinstance(confirmations, dict):
        cleaned: Dict[str, str] = {}
        for key, value in confirmations.items():
            role = str(value or "").strip().lower()
            if role in _ALLOWED_CASE_ROLES:
                cleaned[str(key)] = role
        if cleaned:
            merged["document_role_confirmations"] = cleaned
    relations = llm_payload.get("relations")
    if isinstance(relations, list):
        cleaned_relations: List[Dict[str, Any]] = []
        for item in relations:
            if not isinstance(item, dict):
                continue
            relation_type = str(item.get("case_relation_type", "")).strip().lower()
            if relation_type not in _ALLOWED_CASE_RELATIONS:
                continue
            source_id = str(item.get("source_document_id", "")).strip()
            target_id = str(item.get("target_document_id", "")).strip()
            if not source_id or not target_id:
                continue
            cleaned_relations.append(
                {
                    "source_document_id": source_id,
                    "target_document_id": target_id,
                    "case_relation_type": relation_type,
                    "confidence": _merge_float(0.7, item.get("confidence")),
                }
            )
        if cleaned_relations:
            merged["relations"] = cleaned_relations
    if "family_review_required" in llm_payload:
        merged["family_review_required"] = bool(llm_payload.get("family_review_required"))
    if isinstance(llm_payload.get("family_review_reasons"), list):
        merged["family_review_reasons"] = _merge_list([], llm_payload.get("family_review_reasons"))
    return merged


def _project_case_relation_edges(
    *,
    resolution: Dict[str, Any],
    docs_by_id: Dict[str, Dict[str, Any]],
    first_source_page_id_by_doc: Dict[str, str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in resolution.get("relations", []):
        if not isinstance(item, dict):
            continue
        source_document_id = str(item.get("source_document_id", "")).strip()
        target_document_id = str(item.get("target_document_id", "")).strip()
        case_relation_type = str(item.get("case_relation_type", "")).strip().lower()
        if not source_document_id or not target_document_id or case_relation_type not in _ALLOWED_CASE_RELATIONS:
            continue
        source_doc = docs_by_id.get(source_document_id, {})
        if not source_doc:
            continue
        out.append(
            {
                "edge_id": _stable_id("edge", "case_relation", resolution.get("case_family_id"), source_document_id, target_document_id, case_relation_type),
                "source_object_type": "document",
                "source_object_id": source_document_id,
                "target_object_type": "document",
                "target_object_id": target_document_id,
                "edge_type": "refers_to",
                "confidence_score": _merge_float(0.7, item.get("confidence")),
                "source_page_id": first_source_page_id_by_doc.get(source_document_id),
                "created_by": "case_relation_resolver",
                "case_family_id": resolution.get("case_family_id"),
                "case_relation_type": case_relation_type,
                "source_pdf_id": source_doc.get("pdf_id"),
            }
        )
    return out


def run_corpus_metadata_normalization(
    *,
    project_id: str,
    import_job_id: str,
    documents: List[Dict[str, Any]],
    pages: List[Dict[str, Any]],
    chunk_search_documents: List[Dict[str, Any]],
    relation_edges: List[Dict[str, Any]],
    document_bases: Optional[List[Dict[str, Any]]] = None,
    law_documents: Optional[List[Dict[str, Any]]] = None,
    regulation_documents: Optional[List[Dict[str, Any]]] = None,
    enactment_notice_documents: Optional[List[Dict[str, Any]]] = None,
    case_documents: Optional[List[Dict[str, Any]]] = None,
    llm_client: AzureLLMClient | None = None,
) -> Dict[str, Any]:
    client = llm_client or build_metadata_normalizer_client()
    pages_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for page in pages:
        pages_by_doc[str(page.get("document_id", ""))].append(page)
    for page_list in pages_by_doc.values():
        page_list.sort(key=lambda item: (int(item.get("page_num", 0) or 0), str(item.get("page_id", ""))))

    base_by_doc = {str(row.get("document_id", "")): dict(row) for row in (document_bases or [])}
    law_by_doc = {str(row.get("document_id", "")): dict(row) for row in (law_documents or [])}
    regulation_by_doc = {str(row.get("document_id", "")): dict(row) for row in (regulation_documents or [])}
    notice_by_doc = {str(row.get("document_id", "")): dict(row) for row in (enactment_notice_documents or [])}
    case_by_doc = {str(row.get("document_id", "")): dict(row) for row in (case_documents or [])}
    chunk_projections = {str(row.get("chunk_id", "")): dict(row) for row in chunk_search_documents}

    updated_documents: Dict[str, Dict[str, Any]] = {}
    updated_bases: Dict[str, Dict[str, Any]] = {}
    updated_law_docs: Dict[str, Dict[str, Any]] = {}
    updated_reg_docs: Dict[str, Dict[str, Any]] = {}
    updated_notice_docs: Dict[str, Dict[str, Any]] = {}
    updated_case_docs: Dict[str, Dict[str, Any]] = {}
    updated_chunk_projections: Dict[str, Dict[str, Any]] = {}
    document_stage_runs: Dict[str, Dict[str, Any]] = {}
    llm_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    cache_hit_count = 0
    rate_limit_retry_count = 0
    failed_document_ids: List[str] = []
    last_request_finished_at = 0.0

    for document in documents:
        document_id = str(document.get("document_id", ""))
        pdf_id = str(document.get("pdf_id", ""))
        pages_for_doc = pages_by_doc.get(document_id, [])
        envelope = _base_envelope(document, pages_for_doc)
        document_prompt_name = _title_prompt_name(envelope.get("canonical_document", {}).get("doc_type"))
        llm_payload: Dict[str, Any] = {}
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        mode = "rules_only"
        error = None
        if client.config.enabled:
            cache_key = _title_cache_key(document, envelope, client)
            cached = _read_cache("title_page", cache_key)
            if cached:
                llm_payload = cached.get("payload") if isinstance(cached.get("payload"), dict) else {}
                usage = cached.get("usage") if isinstance(cached.get("usage"), dict) else usage
                mode = "llm_merge" if llm_payload else "rules_only"
                cache_hit_count += 1
            else:
                for attempt in range(_retry_limit()):
                    elapsed = time.monotonic() - last_request_finished_at
                    wait_seconds = max(0.0, _request_spacing_seconds() - elapsed)
                    _sleep(wait_seconds)
                    try:
                        llm_payload, usage = _title_page_llm(client, envelope=envelope, pdf_id=pdf_id)
                        last_request_finished_at = time.monotonic()
                        if llm_payload:
                            mode = "llm_merge"
                            llm_calls += 1
                            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
                            _write_cache(
                                "title_page",
                                cache_key,
                                {
                                    "payload": llm_payload,
                                    "usage": usage,
                                    "cached_at": _utcnow().isoformat(),
                                },
                            )
                        break
                    except Exception as exc:
                        last_request_finished_at = time.monotonic()
                        if not _rate_limit_error(exc) or attempt >= (_retry_limit() - 1):
                            error = str(exc)
                            failed_document_ids.append(document_id)
                            break
                        rate_limit_retry_count += 1
                        _sleep(_retry_delay_seconds(attempt))
        merged = _merge_title_envelope(envelope, llm_payload)

        updated_doc = dict(document)
        canonical = merged.get("canonical_document", {})
        type_specific = merged.get("type_specific_document", {})
        candidates = merged.get("processing_candidates", {})
        review = merged.get("review", {})
        processing = dict(updated_doc.get("processing") or {})
        processing["metadata_normalization"] = {
            "status": "completed" if error is None else "failed",
            "mode": mode,
            "llm_enabled": bool(client.config.enabled),
            "llm_model_version": client.config.deployment or client.config.model or "disabled",
            "llm_prompt_version": document_prompt_name,
            "llm_prompt_set_version": TITLE_PAGE_PROMPT_SET_VERSION,
            "source_page_ids": envelope.get("context", {}).get("source_page_ids", []),
            "canonical_document": canonical,
            "type_specific_document": type_specific,
            "processing_candidates": candidates,
            "review": review,
            "updated_at": _utcnow().isoformat(),
        }
        if error:
            processing["metadata_normalization"]["error"] = error
        updated_doc["processing"] = processing
        updated_doc["doc_type"] = str(canonical.get("doc_type") or updated_doc.get("doc_type") or "other")
        updated_doc["title"] = _merge_string(updated_doc.get("title"), canonical.get("title_raw"))
        updated_doc["title_raw"] = _merge_string(updated_doc.get("title_raw"), canonical.get("title_raw"))
        title_normalized = _merge_string(updated_doc.get("title_normalized"), canonical.get("title_normalized"))
        if title_normalized:
            updated_doc["title_normalized"] = title_normalized
        updated_doc["short_title"] = _merge_string(updated_doc.get("short_title"), canonical.get("short_title"))
        updated_doc["citation_title"] = _merge_string(updated_doc.get("citation_title"), canonical.get("citation_title"))
        updated_doc["language"] = _merge_string(updated_doc.get("language"), canonical.get("language"))
        updated_doc["jurisdiction"] = _merge_string(updated_doc.get("jurisdiction"), canonical.get("jurisdiction"))
        updated_doc["issued_date"] = _merge_string(updated_doc.get("issued_date"), canonical.get("issued_date"))
        updated_doc["effective_start_date"] = _merge_string(updated_doc.get("effective_start_date"), canonical.get("effective_start_date"))
        updated_doc["effective_end_date"] = _merge_string(updated_doc.get("effective_end_date"), canonical.get("effective_end_date"))
        updated_doc["ocr_used"] = _merge_bool(updated_doc.get("ocr_used", False), canonical.get("ocr_used"))
        updated_doc["extraction_confidence"] = round(_merge_float(updated_doc.get("extraction_confidence", 0.0), canonical.get("extraction_confidence")), 4)

        doc_type = str(updated_doc.get("doc_type") or "")
        if doc_type == "law":
            updated_doc["law_number"] = _merge_string(updated_doc.get("law_number"), type_specific.get("law_number"))
            updated_doc["year"] = _merge_int(updated_doc.get("year"), type_specific.get("law_year"))
            updated_doc["case_id"] = None
        elif doc_type == "regulation":
            updated_doc["law_number"] = _merge_string(updated_doc.get("law_number"), type_specific.get("regulation_number"))
            updated_doc["year"] = _merge_int(updated_doc.get("year"), type_specific.get("regulation_year"))
            updated_doc["case_id"] = None
        elif doc_type == "enactment_notice":
            updated_doc["law_number"] = _merge_string(updated_doc.get("law_number"), type_specific.get("notice_number"))
            updated_doc["year"] = _merge_int(updated_doc.get("year"), type_specific.get("notice_year"))
            updated_doc["case_id"] = None
        elif doc_type == "case":
            updated_doc["case_id"] = _merge_string(updated_doc.get("case_id"), type_specific.get("case_number") or type_specific.get("neutral_citation"))
            updated_doc["law_number"] = None
            updated_doc["effective_start_date"] = None
            updated_doc["effective_end_date"] = None

        updated_documents[document_id] = updated_doc
        if document_id in base_by_doc:
            base = dict(base_by_doc[document_id])
            for key in (
                "doc_type",
                "title_raw",
                "title_normalized",
                "short_title",
                "citation_title",
                "language",
                "jurisdiction",
                "issued_date",
                "effective_start_date",
                "effective_end_date",
                "ocr_used",
                "extraction_confidence",
            ):
                if key in updated_doc:
                    base[key] = updated_doc.get(key)
            updated_bases[document_id] = base
        if document_id in law_by_doc and doc_type == "law":
            law_doc = dict(law_by_doc[document_id])
            mapping = {
                "law_number": "law_number",
                "law_year": "year",
                "instrument_kind": "instrument_kind",
                "administering_authority": "administering_authority",
                "promulgation_date": "promulgation_date",
                "commencement_date": "commencement_date",
                "last_consolidated_date": "last_consolidated_date",
            }
            for target_key, source_key in mapping.items():
                law_doc[target_key] = _merge_string(law_doc.get(target_key), type_specific.get(source_key))
            updated_law_docs[document_id] = law_doc
        if document_id in regulation_by_doc and doc_type == "regulation":
            reg_doc = dict(regulation_by_doc[document_id])
            reg_doc["regulation_number"] = _merge_string(reg_doc.get("regulation_number"), type_specific.get("regulation_number"))
            reg_doc["regulation_year"] = _merge_int(reg_doc.get("regulation_year"), type_specific.get("regulation_year"))
            reg_doc["regulation_type"] = _merge_string(reg_doc.get("regulation_type"), type_specific.get("regulation_type"))
            reg_doc["issuing_authority"] = _merge_string(reg_doc.get("issuing_authority"), type_specific.get("issuing_authority"))
            reg_doc["enabled_by_law_title"] = _merge_string(reg_doc.get("enabled_by_law_title"), type_specific.get("enabled_by_law_title"))
            reg_doc["is_current_version"] = _merge_bool(reg_doc.get("is_current_version"), type_specific.get("is_current_version"))
            updated_reg_docs[document_id] = reg_doc
        if document_id in notice_by_doc and doc_type == "enactment_notice":
            notice_doc = dict(notice_by_doc[document_id])
            notice_doc["notice_number"] = _merge_string(notice_doc.get("notice_number"), type_specific.get("notice_number"))
            notice_doc["notice_year"] = _merge_int(notice_doc.get("notice_year"), type_specific.get("notice_year"))
            notice_doc["notice_type"] = _merge_string(notice_doc.get("notice_type"), type_specific.get("notice_type"))
            notice_doc["issuing_authority"] = _merge_string(notice_doc.get("issuing_authority"), type_specific.get("issuing_authority"))
            notice_doc["target_title"] = _merge_string(notice_doc.get("target_title"), type_specific.get("target_title"))
            notice_doc["target_law_number"] = _merge_string(notice_doc.get("target_law_number"), type_specific.get("target_law_number"))
            notice_doc["target_law_year"] = _merge_int(notice_doc.get("target_law_year"), type_specific.get("target_law_year"))
            notice_doc["commencement_scope_type"] = _merge_string(notice_doc.get("commencement_scope_type"), type_specific.get("commencement_scope_type"))
            notice_doc["commencement_date"] = _merge_string(notice_doc.get("commencement_date"), type_specific.get("commencement_date"))
            updated_notice_docs[document_id] = notice_doc
        if document_id in case_by_doc and doc_type == "case":
            case_doc = dict(case_by_doc[document_id])
            case_doc["case_number"] = _merge_string(case_doc.get("case_number"), type_specific.get("case_number"))
            case_doc["neutral_citation"] = _merge_string(case_doc.get("neutral_citation"), type_specific.get("neutral_citation"))
            case_doc["court_name"] = _merge_string(case_doc.get("court_name"), type_specific.get("court_name"))
            case_doc["court_level"] = _merge_string(case_doc.get("court_level"), type_specific.get("court_level"))
            case_doc["decision_date"] = _merge_string(case_doc.get("decision_date"), type_specific.get("decision_date"))
            case_doc["judgment_date"] = _merge_string(case_doc.get("judgment_date"), type_specific.get("judgment_date"))
            case_doc["claimant_names"] = _merge_list(case_doc.get("claimant_names", []), type_specific.get("claimant_names"))
            case_doc["respondent_names"] = _merge_list(case_doc.get("respondent_names", []), type_specific.get("respondent_names"))
            case_doc["appellant_names"] = _merge_list(case_doc.get("appellant_names", []), type_specific.get("appellant_names"))
            case_doc["defendant_names"] = _merge_list(case_doc.get("defendant_names", []), type_specific.get("defendant_names"))
            case_doc["judge_names"] = _merge_list(case_doc.get("judge_names", []), type_specific.get("judge_names"))
            case_doc["presiding_judge"] = _merge_string(case_doc.get("presiding_judge"), type_specific.get("presiding_judge"))
            case_doc["procedural_stage"] = _merge_string(case_doc.get("procedural_stage"), type_specific.get("procedural_stage"))
            updated_case_docs[document_id] = case_doc

        for chunk_id, projection in chunk_projections.items():
            if str(projection.get("document_id")) != document_id:
                continue
            row = dict(projection)
            row["title_normalized"] = updated_doc.get("title_normalized")
            row["short_title"] = updated_doc.get("short_title")
            row["jurisdiction"] = updated_doc.get("jurisdiction")
            if doc_type in {"law", "regulation", "enactment_notice"}:
                row["is_current_version"] = updated_doc.get("is_current_version")
                row["effective_start_date"] = updated_doc.get("effective_start_date")
                row["effective_end_date"] = updated_doc.get("effective_end_date")
            if doc_type == "law":
                row["law_number"] = updated_doc.get("law_number")
                row["law_year"] = updated_doc.get("year")
            elif doc_type == "regulation":
                row["regulation_number"] = updated_doc.get("law_number")
                row["regulation_year"] = updated_doc.get("year")
            elif doc_type == "enactment_notice":
                row["notice_number"] = updated_doc.get("law_number")
                row["notice_year"] = updated_doc.get("year")
            elif doc_type == "case":
                row["case_number"] = updated_doc.get("case_id")
                row["court_name"] = type_specific.get("court_name") or row.get("court_name")
                row["decision_date"] = type_specific.get("decision_date") or row.get("decision_date")
            updated_chunk_projections[chunk_id] = row

        document_stage_runs[document_id] = {
            "title_page_normalizer": _stage_result(
                status="completed" if error is None else "failed",
                role="title_page_normalizer",
                payload={
                    "mode": mode,
                    "llm_enabled": bool(client.config.enabled),
                    "llm_model_version": client.config.deployment or client.config.model or "disabled",
                    "llm_prompt_version": document_prompt_name,
                    "llm_prompt_set_version": TITLE_PAGE_PROMPT_SET_VERSION,
                    "manual_review_required": bool(review.get("manual_review_required", False)),
                    "source_page_ids": envelope.get("context", {}).get("source_page_ids", []),
                    "keys": sorted((llm_payload or {}).keys()),
                },
                error=error,
            )
        }

    projected_edges: Dict[str, Dict[str, Any]] = {str(edge.get("edge_id")): dict(edge) for edge in relation_edges}
    first_source_page_id_by_doc = {
        doc_id: (pages_by_doc.get(doc_id, [{}])[0].get("source_page_id") if pages_by_doc.get(doc_id) else None)
        for doc_id in updated_documents.keys()
    }
    docs_by_id = updated_documents
    case_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc_id, document in updated_documents.items():
        if str(document.get("doc_type")) != "case":
            continue
        processing = document.get("processing") or {}
        normalization = (processing.get("metadata_normalization") or {})
        candidates = normalization.get("processing_candidates") or {}
        group_key = str(candidates.get("same_case_anchor_candidate") or "").strip()
        if not group_key:
            continue
        case_groups[group_key].append(
            {
                "document_id": doc_id,
                "pdf_id": document.get("pdf_id"),
                "case_id": document.get("case_id"),
                "issued_date": document.get("issued_date"),
                "document_role": str(candidates.get("document_role") or "other"),
                "source_page_ids": normalization.get("source_page_ids", []),
                "short_title": document.get("short_title"),
            }
        )

    case_group_stage_runs: Dict[str, Dict[str, Any]] = {}
    failed_group_ids: List[str] = []
    grouped_case_family_count = 0
    for group_key, group_docs in case_groups.items():
        if len(group_docs) < 2:
            continue
        grouped_case_family_count += 1
        resolution = _resolve_case_relations_rules(group_key, group_docs)
        mode = "rules_only"
        error = None
        if client.config.enabled:
            cache_key = _case_group_cache_key(group_key, group_docs, client)
            cached = _read_cache("case_group", cache_key)
            if cached:
                llm_payload = cached.get("payload") if isinstance(cached.get("payload"), dict) else {}
                if llm_payload:
                    resolution = _merge_case_resolution(resolution, llm_payload)
                    mode = "llm_merge"
                    cache_hit_count += 1
            else:
                for attempt in range(_retry_limit()):
                    elapsed = time.monotonic() - last_request_finished_at
                    wait_seconds = max(0.0, _request_spacing_seconds() - elapsed)
                    _sleep(wait_seconds)
                    try:
                        llm_payload, usage = _case_relation_llm(client, group_key=group_key, docs=group_docs)
                        last_request_finished_at = time.monotonic()
                        if llm_payload:
                            resolution = _merge_case_resolution(resolution, llm_payload)
                            mode = "llm_merge"
                            llm_calls += 1
                            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
                            _write_cache(
                                "case_group",
                                cache_key,
                                {
                                    "payload": llm_payload,
                                    "usage": usage,
                                    "cached_at": _utcnow().isoformat(),
                                },
                            )
                        break
                    except Exception as exc:
                        last_request_finished_at = time.monotonic()
                        if not _rate_limit_error(exc) or attempt >= (_retry_limit() - 1):
                            error = str(exc)
                            failed_group_ids.append(group_key)
                            break
                        rate_limit_retry_count += 1
                        _sleep(_retry_delay_seconds(attempt))

        relation_edges_for_group = _project_case_relation_edges(
            resolution=resolution,
            docs_by_id=docs_by_id,
            first_source_page_id_by_doc=first_source_page_id_by_doc,
        )
        for edge in relation_edges_for_group:
            projected_edges[str(edge.get("edge_id"))] = edge

        for item in group_docs:
            document_id = str(item["document_id"])
            processing = dict(updated_documents[document_id].get("processing") or {})
            processing["case_relation_resolution"] = {
                "status": "completed" if error is None else "failed",
                "mode": mode,
                "llm_enabled": bool(client.config.enabled),
                "llm_model_version": client.config.deployment or client.config.model or "disabled",
                "llm_prompt_version": CASE_RELATION_PROMPT_VERSION,
                "case_family_id": resolution.get("case_family_id"),
                "primary_merits_document_id": resolution.get("primary_merits_document_id"),
                "document_role_confirmed": resolution.get("document_role_confirmations", {}).get(document_id),
                "family_review_required": bool(resolution.get("family_review_required", False)),
                "family_review_reasons": resolution.get("family_review_reasons", []),
                "relation_targets": [edge for edge in relation_edges_for_group if str(edge.get("source_object_id")) == document_id],
                "updated_at": _utcnow().isoformat(),
            }
            if error:
                processing["case_relation_resolution"]["error"] = error
            updated_documents[document_id]["processing"] = processing
            if document_id in updated_case_docs:
                role = str(resolution.get("document_role_confirmations", {}).get(document_id) or "").strip()
                if role:
                    updated_case_docs[document_id]["procedural_stage"] = role

        case_group_stage_runs[group_key] = {
            "case_relation_resolver": _stage_result(
                status="completed" if error is None else "failed",
                role="case_relation_resolver",
                payload={
                    "mode": mode,
                    "llm_enabled": bool(client.config.enabled),
                    "llm_model_version": client.config.deployment or client.config.model or "disabled",
                    "llm_prompt_version": CASE_RELATION_PROMPT_VERSION,
                    "case_family_id": resolution.get("case_family_id"),
                    "primary_merits_document_id": resolution.get("primary_merits_document_id"),
                    "relation_count": len(relation_edges_for_group),
                },
                error=error,
            )
        }

    job = {
        "job_id": _stable_id("metadata_norm", project_id, import_job_id),
        "project_id": project_id,
        "import_job_id": import_job_id,
        "processing_profile_version": NORMALIZATION_PROFILE_VERSION,
        "llm_enabled": bool(client.config.enabled),
        "llm_model_version": client.config.deployment or client.config.model or "disabled",
        "title_page_prompt_version": TITLE_PAGE_PROMPT_SET_VERSION,
        "case_relation_prompt_version": CASE_RELATION_PROMPT_VERSION,
        "status": "completed" if not failed_document_ids and not failed_group_ids else "partial",
        "document_count": len(documents),
        "processed_document_count": len(documents),
        "grouped_case_family_count": grouped_case_family_count,
        "failed_document_ids": failed_document_ids,
        "failed_group_ids": failed_group_ids,
        "llm_calls": llm_calls,
        "cache_hit_count": cache_hit_count,
        "rate_limit_retry_count": rate_limit_retry_count,
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
        "document_stage_runs": document_stage_runs,
        "case_group_stage_runs": case_group_stage_runs,
        "created_at": _iso(_utcnow()),
        "updated_at": _iso(_utcnow()),
    }

    return {
        "job": job,
        "updated_documents": updated_documents,
        "updated_document_bases": updated_bases,
        "updated_law_documents": updated_law_docs,
        "updated_regulation_documents": updated_reg_docs,
        "updated_enactment_notice_documents": updated_notice_docs,
        "updated_case_documents": updated_case_docs,
        "updated_chunk_projections": updated_chunk_projections,
        "projected_relation_edges": sorted(projected_edges.values(), key=lambda item: str(item.get("edge_id"))),
    }
