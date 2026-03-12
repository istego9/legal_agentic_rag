from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, Optional


_CASE_PREFIX_PATTERN = re.compile(r"\b([A-Z]{2,4}|S\s*CT)\s+\d{1,5}/\d{4}\b", flags=re.IGNORECASE)
_BAD_COURT_NAME_MARKERS = ("IN THE ", " BETWEEN ", "COUNSEL", "HEARING", "JUDGMENT :", "ORDER WITH REASONS")


def _registry_path() -> Path:
    return Path(__file__).with_name("court_registry_v1.json")


@lru_cache(maxsize=1)
def load_court_registry() -> Dict[str, Any]:
    return json.loads(_registry_path().read_text(encoding="utf-8"))


def _normalize_source(value: str) -> str:
    compact = re.sub(r"\s+", " ", str(value or "").upper()).strip()
    compact = re.sub(r"\bS\s*CT\b", "SCT", compact)
    return compact


def _case_prefix(case_number: str | None) -> str | None:
    normalized = _normalize_source(str(case_number or ""))
    match = _CASE_PREFIX_PATTERN.search(normalized)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _looks_like_bad_court_name(value: str | None) -> bool:
    text = _normalize_source(str(value or ""))
    if not text:
        return True
    return any(marker in text for marker in _BAD_COURT_NAME_MARKERS)


def _match_stream(source: str) -> Optional[Dict[str, Any]]:
    registry = load_court_registry()
    for stream in registry.get("document_streams", []):
        if any(_normalize_source(alias) in source for alias in stream.get("aliases", [])):
            return stream
    return None


def _match_court(source: str, case_prefix: str | None) -> Optional[Dict[str, Any]]:
    registry = load_court_registry()
    ordered = sorted(
        registry.get("courts", []),
        key=lambda item: (item.get("court_kind") == "division", len(item.get("aliases", []))),
        reverse=True,
    )
    for court in ordered:
        aliases = [_normalize_source(alias) for alias in court.get("aliases", [])]
        if any(alias and alias in source for alias in aliases):
            return court
        prefixes = [str(prefix or "").upper() for prefix in court.get("case_number_prefixes", [])]
        if case_prefix and case_prefix.upper() in prefixes:
            return court
    return None


def normalize_case_court_structure(
    *,
    case_number: str | None,
    context_text: str,
    current_court_name: str | None,
    current_court_level: str | None,
) -> Dict[str, Any]:
    source = _normalize_source(context_text)
    registry = load_court_registry()
    system = registry.get("court_systems", [{}])[0]
    prefix = _case_prefix(case_number)
    court = _match_court(source, prefix)
    stream = _match_stream(source)
    if not court and not stream and not prefix and not any(alias in source for alias in [_normalize_source(a) for a in system.get("aliases", [])]):
        return {}

    matched_alias = None
    if court:
        for alias in court.get("aliases", []):
            if _normalize_source(alias) in source:
                matched_alias = alias
                break
        if matched_alias is None and prefix:
            matched_alias = prefix

    normalized_court_name = str(current_court_name or "").strip()
    normalized_court_level = str(current_court_level or "").strip()

    if court and _looks_like_bad_court_name(current_court_name):
        normalized_court_name = str(court.get("court_name") or "").strip()
    if court and (not normalized_court_level or normalized_court_level.lower() == "unknown"):
        normalized_court_level = str(court.get("court_level") or "").strip()

    return {
        "registry_version": registry.get("registry_version"),
        "court_system_key": system.get("court_system_key"),
        "court_system_name": system.get("court_system_name"),
        "court_key": court.get("court_key") if court else None,
        "court_name": normalized_court_name or None,
        "court_level": normalized_court_level or None,
        "court_kind": court.get("court_kind") if court else None,
        "court_division_name": court.get("division_name") if court else None,
        "document_stream_key": stream.get("stream_key") if stream else None,
        "document_stream_name": stream.get("stream_name") if stream else None,
        "matched_alias": matched_alias,
        "source_urls": court.get("source_urls") if court else [],
    }
