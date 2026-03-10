"""Offline corpus enrichment with chunk-first legal frame extraction."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from legal_rag_api.azure_llm import AzureLLMClient

ENRICHMENT_PROFILE_VERSION = "agentic_corpus_enrichment_v1"
CHUNK_INTERPRETER_PROMPT_VERSION = "chunk_ontology_frame.v1"
ACTIVE_CREATED_BY = "ontology_seed"
AGENT_CREATED_BY = "agentic_enrichment"
ACTIVE_ONTOLOGY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "object_type": {
        "actor": ("Actor",),
        "defined_term": ("Defined Term",),
        "legal_object": ("Legal Object",),
        "beneficiary": ("Beneficiary",),
        "law_reference": ("Law Reference",),
        "case_reference": ("Case Reference",),
        "condition": ("Condition",),
        "temporal_scope": ("Temporal Scope",),
    },
    "relation_type": {
        "defines": ("Defines",),
        "requires": ("Requires",),
        "prohibits": ("Prohibits",),
        "permits": ("Permits",),
        "penalizes": ("Penalizes",),
        "governs": ("Governs",),
        "empowers": ("Empowers",),
        "excepts": ("Excepts",),
        "refers_to": ("Refers To",),
        "enabled_by": ("Enabled By",),
        "comes_into_force_via": ("Comes Into Force Via",),
        "same_legal_concept_as": ("Same Legal Concept As",),
    },
    "property_type": {
        "modality": ("Modality",),
        "action": ("Action",),
        "beneficiary": ("Beneficiary",),
        "condition_text": ("Condition Text",),
        "exception_text": ("Exception Text",),
        "temporal_scope": ("Temporal Scope",),
        "citation_ref": ("Citation Ref",),
        "confidence": ("Confidence",),
    },
}
MODALITY_TO_RELATION = {
    "definition": "defines",
    "obligation": "requires",
    "prohibition": "prohibits",
    "permission": "permits",
    "penalty": "penalizes",
    "power": "empowers",
    "procedure": "governs",
    "exception": "excepts",
}
MODALITY_ORDER = (
    ("prohibition", re.compile(r"\bshall\s+not\b|\bmust\s+not\b|\bprohibited\b|\bforbidden\b", re.I)),
    ("obligation", re.compile(r"\bshall\b|\bmust\b|\bis required to\b|\bobliged\b", re.I)),
    ("permission", re.compile(r"\bmay\b|\bpermitted\b|\bauthorized\b", re.I)),
    ("penalty", re.compile(r"\bpenalt(?:y|ies)\b|\bfine\b|\bimprisonment\b|\bsanction\b", re.I)),
    ("exception", re.compile(r"\bunless\b|\bexcept\b|\bprovided that\b", re.I)),
    ("procedure", re.compile(r"\bprocedure\b|\bsubmit\b|\bfile\b|\bwithin\b|\bapplication\b", re.I)),
    ("power", re.compile(r"\bminister may\b|\bauthority may\b|\bcourt may\b|\bpower to\b", re.I)),
    ("definition", re.compile(r"\bmeans\b|\brefers to\b|\bis defined as\b", re.I)),
)
ACTOR_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("minister", re.compile(r"\bminister\b", re.I)),
    ("authority", re.compile(r"\bauthority\b", re.I)),
    ("court", re.compile(r"\bcourt\b", re.I)),
    ("employer", re.compile(r"\bemployer\b", re.I)),
    ("employee", re.compile(r"\bemployee\b", re.I)),
    ("company", re.compile(r"\bcompany\b|\bcorporation\b", re.I)),
    ("person", re.compile(r"\bperson\b|\bindividual\b", re.I)),
)
ACTION_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(shall|must|may|is required to|is prohibited from)\s+([a-z][a-z -]{2,48})", re.I),
    re.compile(r"\b([a-z][a-z -]{2,48})\s+shall\b", re.I),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(prefix: str, *parts: Any) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(json.dumps(part, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
        hasher.update(b"\x1f")
    return f"{prefix}_{hasher.hexdigest()[:24]}"


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_") or "unknown"


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        token = re.sub(r"\s+", " ", str(value).strip())
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _seed_registry() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for kind, mapping in ACTIVE_ONTOLOGY.items():
        for key, aliases in mapping.items():
            entry = {
                "entry_id": _stable_id("ontology", kind, key),
                "kind": kind,
                "key": key,
                "label": aliases[0],
                "status": "active",
                "parent_key": None,
                "aliases": list(aliases[1:]),
                "usage_count": 0,
                "sample_chunk_ids": [],
                "created_by": ACTIVE_CREATED_BY,
            }
            out[key] = entry
    return out


def _merge_existing_registry(
    registry: Dict[str, Dict[str, Any]],
    existing_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    for item in existing_entries or []:
        if not isinstance(item, dict):
            continue
        key = _normalize_key(str(item.get("key", "")))
        if not key:
            continue
        registry[key] = {**item, "key": key}
    return registry


def _stage_result(*, status: str, role: str, payload: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "role": role,
        "status": status,
        "payload": payload or {},
        "error": error,
        "updated_at": _utcnow().isoformat(),
    }


def _modality_from_chunk(text: str, llm_payload: Dict[str, Any]) -> str:
    llm_modality = _normalize_key(str(llm_payload.get("modality", "")))
    if llm_modality in {key for key, _ in MODALITY_ORDER}:
        return llm_modality
    section_type = _normalize_key(str(llm_payload.get("section_type", "")))
    if section_type in {"definition", "obligation", "prohibition", "procedure", "penalty"}:
        return section_type
    for label, pattern in MODALITY_ORDER:
        if pattern.search(text):
            return label
    return "procedure"


def _subject_from_chunk(paragraph: Dict[str, Any], text: str, modality: str, llm_payload: Dict[str, Any]) -> Tuple[str, str]:
    llm_subject_type = _normalize_key(str(llm_payload.get("subject_type", "")))
    llm_subject_text = re.sub(r"\s+", " ", str(llm_payload.get("subject_text", "")).strip())
    if llm_subject_type and llm_subject_text:
        return llm_subject_type, llm_subject_text

    entities = [str(value) for value in paragraph.get("entities", []) if str(value).strip()]
    if modality == "definition":
        article_refs = [str(value) for value in paragraph.get("article_refs", []) if str(value).strip()]
        if article_refs:
            return "defined_term", article_refs[0]
    if entities:
        return "actor", entities[0]
    for subject_text, pattern in ACTOR_PATTERNS:
        if pattern.search(text):
            return "actor", subject_text
    return "actor", "unspecified actor"


def _object_from_chunk(paragraph: Dict[str, Any], text: str, modality: str, llm_payload: Dict[str, Any]) -> Tuple[str, str]:
    llm_object_type = _normalize_key(str(llm_payload.get("object_type", "")))
    llm_object_text = re.sub(r"\s+", " ", str(llm_payload.get("object_text", "")).strip())
    if llm_object_type and llm_object_text:
        return llm_object_type, llm_object_text

    if modality == "definition":
        match = re.search(r"\bmeans\b\s+(.+?)(?:[.;]|$)", text, re.I)
        if match:
            return "legal_object", match.group(1).strip()[:160]

    law_refs = [str(value) for value in paragraph.get("law_refs", []) if str(value).strip()]
    if law_refs:
        return "law_reference", law_refs[0]
    case_refs = [str(value) for value in paragraph.get("case_refs", []) if str(value).strip()]
    if case_refs:
        return "case_reference", case_refs[0]
    article_refs = [str(value) for value in paragraph.get("article_refs", []) if str(value).strip()]
    if article_refs:
        return "legal_object", article_refs[0]

    sentence = re.sub(r"\s+", " ", text).strip()
    return "legal_object", sentence[:160] if sentence else "unspecified object"


def _extract_action(text: str, llm_payload: Dict[str, Any]) -> str | None:
    llm_action = re.sub(r"\s+", " ", str(llm_payload.get("action", "")).strip())
    if llm_action:
        return llm_action[:120]
    for pattern in ACTION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        action = match.group(match.lastindex or 1).strip()
        return re.sub(r"\s+", " ", action)[:120]
    return None


def _extract_condition(text: str, llm_payload: Dict[str, Any]) -> str | None:
    llm_condition = re.sub(r"\s+", " ", str(llm_payload.get("condition_text", "")).strip())
    if llm_condition:
        return llm_condition[:180]
    match = re.search(r"\b(if|when|where)\b\s+(.+?)(?:[.;]|$)", text, re.I)
    if not match:
        return None
    return f"{match.group(1).lower()} {match.group(2).strip()}"[:180]


def _extract_exception(text: str, llm_payload: Dict[str, Any]) -> str | None:
    llm_exception = re.sub(r"\s+", " ", str(llm_payload.get("exception_text", "")).strip())
    if llm_exception:
        return llm_exception[:180]
    match = re.search(r"\b(unless|except|provided that)\b\s+(.+?)(?:[.;]|$)", text, re.I)
    if not match:
        return None
    return f"{match.group(1).lower()} {match.group(2).strip()}"[:180]


def _extract_temporal_scope(paragraph: Dict[str, Any], llm_payload: Dict[str, Any]) -> str | None:
    llm_scope = re.sub(r"\s+", " ", str(llm_payload.get("temporal_scope", "")).strip())
    if llm_scope:
        return llm_scope[:120]
    dates = [str(value) for value in paragraph.get("dates", []) if str(value).strip()]
    if not dates:
        return None
    return ", ".join(dates[:4])[:120]


def _extract_beneficiary(paragraph: Dict[str, Any], subject_text: str, llm_payload: Dict[str, Any]) -> str | None:
    llm_beneficiary = re.sub(r"\s+", " ", str(llm_payload.get("beneficiary", "")).strip())
    if llm_beneficiary:
        return llm_beneficiary[:120]
    entities = [str(value) for value in paragraph.get("entities", []) if str(value).strip()]
    for value in entities:
        if value != subject_text:
            return value
    return None


async def _run_llm_chunk_frame(client: AzureLLMClient, paragraph: Dict[str, Any]) -> Dict[str, Any]:
    text = re.sub(r"\s+", " ", str(paragraph.get("text", "")).strip())
    if not text:
        return {}
    prompt = (
        "Return strict JSON only. "
        "Schema: {subject_type,subject_text,relation_type,object_type,object_text,modality,action,beneficiary,condition_text,exception_text,temporal_scope}. "
        "Use concise values. "
        f"Chunk text: {text[:1800]}"
    )
    completion, _ = await client.complete_chat(
        prompt,
        user_context={"task": "chunk_ontology_frame", "paragraph_id": paragraph.get("paragraph_id")},
        system_prompt="You extract grounded legal ontology frames from chunk text as strict JSON.",
        max_tokens=260,
        temperature=0.1,
    )
    return _extract_json_object(completion)


def _llm_chunk_frame(client: AzureLLMClient, paragraph: Dict[str, Any]) -> Dict[str, Any]:
    if not client.config.enabled:
        return {}
    try:
        return asyncio.run(_run_llm_chunk_frame(client, paragraph))
    except Exception:
        return {}


def _chunk_interpreter_step(client: AzureLLMClient, paragraph: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    llm_payload = _llm_chunk_frame(client, paragraph)
    mode = "llm_merge" if llm_payload else "rules_only"
    return llm_payload, _stage_result(
        status="completed",
        role="chunk_interpreter",
        payload={
            "mode": mode,
            "paragraph_id": paragraph.get("paragraph_id"),
            "keys": sorted(llm_payload.keys()),
            "llm_enabled": bool(client.config.enabled),
            "llm_model_version": client.config.deployment or "disabled",
            "llm_prompt_version": CHUNK_INTERPRETER_PROMPT_VERSION,
        },
    )


def _candidate_property_entries(paragraph: Dict[str, Any]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    section_kind = _normalize_key(str(paragraph.get("section_kind", "")))
    if section_kind:
        out.append((f"section_kind_{section_kind}", f"Section Kind {section_kind}"))
    paragraph_class = _normalize_key(str(paragraph.get("paragraph_class", "")))
    if paragraph_class:
        out.append((f"paragraph_class_{paragraph_class}", f"Paragraph Class {paragraph_class}"))
    return out


def _ensure_registry_entry(
    registry: Dict[str, Dict[str, Any]],
    *,
    kind: str,
    key: str,
    label: str,
    status: str,
    sample_chunk_id: str,
) -> None:
    normalized_key = _normalize_key(key)
    existing = registry.get(normalized_key)
    if existing:
        existing["usage_count"] = int(existing.get("usage_count", 0)) + 1
        sample_chunk_ids = list(existing.get("sample_chunk_ids", []))
        if sample_chunk_id not in sample_chunk_ids:
            sample_chunk_ids.append(sample_chunk_id)
        existing["sample_chunk_ids"] = sample_chunk_ids[:12]
        registry[normalized_key] = existing
        return
    registry[normalized_key] = {
        "entry_id": _stable_id("ontology", kind, normalized_key),
        "kind": kind,
        "key": normalized_key,
        "label": label,
        "status": status,
        "parent_key": None,
        "aliases": [],
        "usage_count": 1,
        "sample_chunk_ids": [sample_chunk_id],
        "created_by": ACTIVE_CREATED_BY if status == "active" else AGENT_CREATED_BY,
    }


def _chunk_assertion(
    *,
    paragraph: Dict[str, Any],
    page: Dict[str, Any],
    document: Dict[str, Any],
    llm_payload: Dict[str, Any],
) -> Dict[str, Any]:
    text = str(paragraph.get("text", "") or "")
    modality = _modality_from_chunk(text, llm_payload)
    subject_type, subject_text = _subject_from_chunk(paragraph, text, modality, llm_payload)
    object_type, object_text = _object_from_chunk(paragraph, text, modality, llm_payload)
    relation_type = _normalize_key(str(llm_payload.get("relation_type", ""))) or MODALITY_TO_RELATION.get(modality, "governs")
    action = _extract_action(text, llm_payload)
    condition_text = _extract_condition(text, llm_payload)
    exception_text = _extract_exception(text, llm_payload)
    temporal_scope = _extract_temporal_scope(paragraph, llm_payload)
    beneficiary = _extract_beneficiary(paragraph, subject_text, llm_payload)
    citation_refs = _uniq(
        [
            *[str(value) for value in paragraph.get("article_refs", [])],
            *[str(value) for value in paragraph.get("law_refs", [])],
            *[str(value) for value in paragraph.get("case_refs", [])],
        ]
    )
    properties = {
        "doc_type": document.get("doc_type"),
        "section_kind": paragraph.get("section_kind"),
        "paragraph_class": paragraph.get("paragraph_class"),
        "source_page_id": page.get("source_page_id"),
    }
    confidence = 0.45
    if subject_text and object_text:
        confidence += 0.15
    if citation_refs:
        confidence += 0.1
    if action:
        confidence += 0.1
    if condition_text or exception_text:
        confidence += 0.05
    if llm_payload:
        confidence += 0.1
    confidence = max(0.0, min(0.95, confidence))
    provenance = "merged" if llm_payload else "rules"
    return {
        "assertion_id": _stable_id(
            "assertion",
            paragraph.get("paragraph_id"),
            subject_type,
            relation_type,
            object_type,
            object_text,
        ),
        "paragraph_id": paragraph.get("paragraph_id"),
        "page_id": page.get("page_id"),
        "document_id": paragraph.get("document_id"),
        "source_page_id": page.get("source_page_id"),
        "subject_type": subject_type,
        "subject_text": subject_text[:160],
        "relation_type": relation_type,
        "object_type": object_type,
        "object_text": object_text[:180],
        "modality": modality,
        "action": action,
        "beneficiary": beneficiary,
        "properties": properties,
        "condition_text": condition_text,
        "exception_text": exception_text,
        "temporal_scope": temporal_scope,
        "citation_refs": citation_refs,
        "confidence": round(confidence, 4),
        "provenance": provenance,
    }


def _validate_assertion(assertion: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(assertion)
    for key in ("subject_type", "relation_type", "object_type"):
        normalized[key] = _normalize_key(str(normalized.get(key, ""))) or "unknown"
    normalized["subject_text"] = re.sub(r"\s+", " ", str(normalized.get("subject_text", "")).strip()) or "unspecified actor"
    normalized["object_text"] = re.sub(r"\s+", " ", str(normalized.get("object_text", "")).strip()) or "unspecified object"
    confidence = float(normalized.get("confidence", 0.0) or 0.0)
    normalized["confidence"] = max(0.0, min(1.0, confidence))
    normalized["citation_refs"] = _uniq(normalized.get("citation_refs", []))
    properties = normalized.get("properties")
    normalized["properties"] = properties if isinstance(properties, dict) else {}
    return normalized


def _chunk_validator_step(assertion: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized = _validate_assertion(assertion)
    return normalized, _stage_result(
        status="completed",
        role="chunk_validator",
        payload={
            "assertion_id": normalized.get("assertion_id"),
            "modality": normalized.get("modality"),
            "confidence": normalized.get("confidence"),
        },
    )


def _document_ontology_view(
    *,
    document: Dict[str, Any],
    assertions: List[Dict[str, Any]],
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    object_types = _uniq(
        [str(item.get("subject_type", "")) for item in assertions]
        + [str(item.get("object_type", "")) for item in assertions]
    )
    relation_types = _uniq(str(item.get("relation_type", "")) for item in assertions)
    property_types = _uniq(
        key
        for item in assertions
        for key in list((item.get("properties") or {}).keys())
    )
    actor_summary = [label for label, _ in Counter(str(item.get("subject_text", "")) for item in assertions).most_common(6)]
    beneficiary_summary = [label for label, _ in Counter(str(item.get("beneficiary", "")) for item in assertions if item.get("beneficiary")).most_common(6)]
    conflicts: Dict[str, set[str]] = defaultdict(set)
    for item in assertions:
        conflict_key = f"{item.get('subject_text')}::{item.get('relation_type')}"
        conflicts[conflict_key].add(str(item.get("object_text", "")))
    conflict_map = {
        key: sorted(values)
        for key, values in conflicts.items()
        if len(values) > 1
    }
    candidate_entry_keys = sorted(
        key
        for key in set(object_types + relation_types + property_types)
        if registry.get(key, {}).get("status") == "candidate"
    )
    active_entry_keys = sorted(
        key
        for key in set(object_types + relation_types + property_types)
        if registry.get(key, {}).get("status") == "active"
    )
    return {
        "document_id": document.get("document_id"),
        "project_id": document.get("project_id"),
        "source_page_ids": _uniq(str(item.get("source_page_id", "")) for item in assertions if item.get("source_page_id")),
        "chunk_assertion_ids": [str(item.get("assertion_id")) for item in assertions],
        "object_types": object_types,
        "relation_types": relation_types,
        "property_types": property_types,
        "candidate_entry_keys": candidate_entry_keys,
        "active_entry_keys": active_entry_keys,
        "actor_summary": actor_summary,
        "beneficiary_summary": beneficiary_summary,
        "conflict_map": conflict_map,
        "assertion_count": len(assertions),
        "created_by": "document_synthesizer",
        "updated_at": _utcnow().isoformat(),
    }


def _document_synthesizer_step(
    *,
    document: Dict[str, Any],
    assertions: List[Dict[str, Any]],
    registry: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    view = _document_ontology_view(document=document, assertions=assertions, registry=registry)
    return view, _stage_result(
        status="completed",
        role="document_synthesizer",
        payload={
            "document_id": document.get("document_id"),
            "assertion_count": view.get("assertion_count", 0),
            "candidate_entry_keys": view.get("candidate_entry_keys", []),
            "active_entry_keys": view.get("active_entry_keys", []),
        },
    )


def _projection_updates(
    *,
    assertion: Dict[str, Any],
    paragraph: Dict[str, Any],
    chunk_projection: Dict[str, Any],
    registry: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    paragraph_update = dict(paragraph)
    chunk_projection_update = dict(chunk_projection)
    assertion_id = str(assertion.get("assertion_id"))
    modality = str(assertion.get("modality"))
    paragraph_update["agentic_status"] = "completed"
    paragraph_update["agentic_assertion_ids"] = _uniq([*paragraph_update.get("agentic_assertion_ids", []), assertion_id])
    paragraph_update["agentic_modalities"] = _uniq([*paragraph_update.get("agentic_modalities", []), modality])
    paragraph_update["agentic_last_enriched_at"] = _utcnow().isoformat()
    paragraph_update["agentic_payload"] = {
        "assertion_id": assertion_id,
        "subject_text": assertion.get("subject_text"),
        "relation_type": assertion.get("relation_type"),
        "object_text": assertion.get("object_text"),
        "modality": modality,
    }
    active_keywords: List[str] = []
    relation_key = _normalize_key(str(assertion.get("relation_type", "")))
    modality_key = _normalize_key(str(modality))
    if registry.get(relation_key, {}).get("status") == "active":
        active_keywords.append(relation_key)
    if registry.get(modality_key, {}).get("status") == "active":
        active_keywords.append(modality_key)
    chunk_projection_update["search_keywords"] = _uniq(
        [*chunk_projection_update.get("search_keywords", []), *active_keywords]
    )[:24]
    chunk_projection_update["edge_types"] = _uniq(
        [*chunk_projection_update.get("edge_types", []), "refers_to" if assertion.get("citation_refs") else ""]
    )[:12]
    new_edges: List[Dict[str, Any]] = []
    for citation_ref in assertion.get("citation_refs", []):
        edge_type = "refers_to"
        target_object_type = "document"
        lowered = str(citation_ref).lower()
        if "case" in lowered:
            edge_type = "cites"
        if any(token in lowered for token in ("law", "act", "code", "article", "art.")):
            target_object_type = "document"
        new_edges.append(
            {
                "edge_id": _stable_id("edge", assertion_id, edge_type, citation_ref),
                "source_object_type": "chunk",
                "source_object_id": paragraph.get("paragraph_id"),
                "target_object_type": target_object_type,
                "target_object_id": citation_ref,
                "edge_type": edge_type,
                "confidence_score": assertion.get("confidence"),
                "source_page_id": assertion.get("source_page_id"),
                "created_by": "projection_agent",
            }
        )
    return paragraph_update, chunk_projection_update, new_edges


def _projection_agent_step(
    *,
    assertion: Dict[str, Any],
    paragraph: Dict[str, Any],
    chunk_projection: Dict[str, Any],
    registry: Dict[str, Dict[str, Any]],
) -> Tuple[Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]], Dict[str, Any]]:
    updates = _projection_updates(assertion=assertion, paragraph=paragraph, chunk_projection=chunk_projection, registry=registry)
    _, _, edges = updates
    return updates, _stage_result(
        status="completed",
        role="projection_agent",
        payload={
            "assertion_id": assertion.get("assertion_id"),
            "edge_count": len(edges),
            "chunk_id": paragraph.get("paragraph_id"),
        },
    )


def run_agentic_corpus_enrichment(
    *,
    project_id: str,
    import_job_id: str,
    documents: List[Dict[str, Any]],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    chunk_search_documents: List[Dict[str, Any]],
    relation_edges: List[Dict[str, Any]],
    existing_registry_entries: Optional[List[Dict[str, Any]]] = None,
    target_document_ids: Optional[List[str]] = None,
    target_paragraph_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    registry = _merge_existing_registry(_seed_registry(), existing_registry_entries)
    page_by_id = {str(item.get("page_id")): item for item in pages}
    doc_by_id = {str(item.get("document_id")): item for item in documents}
    chunk_projection_by_id = {str(item.get("chunk_id")): item for item in chunk_search_documents}
    client = AzureLLMClient()
    target_document_set = {str(item) for item in (target_document_ids or []) if str(item).strip()}
    target_paragraph_set = {str(item) for item in (target_paragraph_ids or []) if str(item).strip()}
    selected_paragraphs = [
        paragraph
        for paragraph in paragraphs
        if (
            not target_paragraph_set
            or str(paragraph.get("paragraph_id", "")) in target_paragraph_set
        )
        and (
            not target_document_set
            or str(paragraph.get("document_id", "")) in target_document_set
        )
    ]
    selected_document_ids = {
        str(paragraph.get("document_id", ""))
        for paragraph in selected_paragraphs
        if str(paragraph.get("document_id", "")).strip()
    }
    selected_documents = [
        document
        for document in documents
        if not selected_document_ids or str(document.get("document_id", "")) in selected_document_ids
    ]
    job = {
        "job_id": _stable_id(
            "enrichment",
            project_id,
            import_job_id,
            ENRICHMENT_PROFILE_VERSION,
            sorted(target_document_set),
            sorted(target_paragraph_set),
        ),
        "project_id": project_id,
        "import_job_id": import_job_id,
        "processing_profile_version": ENRICHMENT_PROFILE_VERSION,
        "llm_enabled": bool(client.config.enabled),
        "llm_model_version": client.config.deployment or "disabled",
        "llm_prompt_version": CHUNK_INTERPRETER_PROMPT_VERSION,
        "status": "queued",
        "document_count": len(selected_documents),
        "chunk_count": len(selected_paragraphs),
        "processed_document_count": 0,
        "processed_chunk_count": 0,
        "failed_document_ids": [],
        "failed_chunk_ids": [],
        "candidate_entry_count": 0,
        "active_entry_count": len(registry),
        "role_sequence": [
            "chunk_interpreter",
            "chunk_validator",
            "document_synthesizer",
            "projection_agent",
        ],
        "chunk_stage_runs": {},
        "document_stage_runs": {},
        "retryable_targets": {"chunks": [], "documents": []},
        "error_message": None,
        "created_at": _utcnow().isoformat(),
        "updated_at": _utcnow().isoformat(),
    }

    assertions: List[Dict[str, Any]] = []
    document_views: List[Dict[str, Any]] = []
    updated_paragraphs: Dict[str, Dict[str, Any]] = {}
    updated_documents: Dict[str, Dict[str, Any]] = {}
    updated_chunk_projections: Dict[str, Dict[str, Any]] = {}
    projected_edges: Dict[str, Dict[str, Any]] = {str(edge.get("edge_id")): edge for edge in relation_edges}

    job["status"] = "running"
    for paragraph in selected_paragraphs:
        paragraph_id = str(paragraph.get("paragraph_id", ""))
        page = page_by_id.get(str(paragraph.get("page_id", "")), {})
        document = doc_by_id.get(str(paragraph.get("document_id", "")), {})
        chunk_projection = chunk_projection_by_id.get(paragraph_id, {})
        try:
            llm_payload, interpreter_stage = _chunk_interpreter_step(client, paragraph)
            assertion, validator_stage = _chunk_validator_step(
                _chunk_assertion(paragraph=paragraph, page=page, document=document, llm_payload=llm_payload)
            )
            assertions.append(assertion)
            (
                updated_paragraph,
                updated_chunk_projection,
                new_edges,
            ), projection_stage = _projection_agent_step(
                assertion=assertion,
                paragraph=paragraph,
                chunk_projection=chunk_projection,
                registry=registry,
            )
            updated_paragraphs[paragraph_id] = updated_paragraph
            if chunk_projection:
                updated_chunk_projections[paragraph_id] = updated_chunk_projection
            for new_edge in new_edges:
                projected_edges[str(new_edge.get("edge_id"))] = new_edge

            sample_chunk_id = paragraph_id
            for kind, key, label in (
                ("object_type", str(assertion.get("subject_type", "")), str(assertion.get("subject_type", ""))),
                ("object_type", str(assertion.get("object_type", "")), str(assertion.get("object_type", ""))),
                ("relation_type", str(assertion.get("relation_type", "")), str(assertion.get("relation_type", ""))),
            ):
                status = "active" if _normalize_key(key) in ACTIVE_ONTOLOGY.get(kind, {}) else "candidate"
                _ensure_registry_entry(
                    registry,
                    kind=kind,
                    key=key,
                    label=label.replace("_", " ").title(),
                    status=status,
                    sample_chunk_id=sample_chunk_id,
                )
            for property_key, label in _candidate_property_entries(paragraph):
                _ensure_registry_entry(
                    registry,
                    kind="property_type",
                    key=property_key,
                    label=label,
                    status="candidate",
                    sample_chunk_id=sample_chunk_id,
                )

            job["processed_chunk_count"] = int(job.get("processed_chunk_count", 0)) + 1
            job["chunk_stage_runs"][paragraph_id] = {
                "chunk_interpreter": interpreter_stage,
                "chunk_validator": validator_stage,
                "projection_agent": projection_stage,
            }
        except Exception as exc:
            job["failed_chunk_ids"].append(paragraph_id)
            job["retryable_targets"]["chunks"].append(paragraph_id)
            job["chunk_stage_runs"][paragraph_id] = {
                "chunk_interpreter": _stage_result(status="failed", role="chunk_interpreter", error=str(exc)[:300]),
                "chunk_validator": _stage_result(status="queued", role="chunk_validator"),
                "projection_agent": _stage_result(status="queued", role="projection_agent"),
            }

    assertions_by_document: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for assertion in assertions:
        assertions_by_document[str(assertion.get("document_id"))].append(assertion)

    for document in selected_documents:
        document_id = str(document.get("document_id", ""))
        try:
            view, document_stage = _document_synthesizer_step(
                document=document,
                assertions=assertions_by_document.get(document_id, []),
                registry=registry,
            )
            document_views.append(view)
            doc_chunk_count = sum(1 for item in selected_paragraphs if str(item.get("document_id")) == document_id)
            processing = document.get("processing") if isinstance(document.get("processing"), dict) else {}
            processing["processing_profile_version"] = processing.get("processing_profile_version") or ENRICHMENT_PROFILE_VERSION
            processing["agentic_enrichment"] = {
                "job_id": job["job_id"],
                "status": "completed",
                "assertion_count": view["assertion_count"],
                "candidate_entry_count": len(view["candidate_entry_keys"]),
                "active_entry_count": len(view["active_entry_keys"]),
                "chunk_coverage_ratio": round(
                    (len(view["chunk_assertion_ids"]) / max(1, doc_chunk_count)),
                    4,
                ),
                "document_conflict_count": len(view["conflict_map"]),
                "llm_enabled": job["llm_enabled"],
                "llm_model_version": job["llm_model_version"],
                "llm_prompt_version": job["llm_prompt_version"],
                "updated_at": _utcnow().isoformat(),
            }
            processing["ontology"] = {
                "object_types": view["object_types"],
                "relation_types": view["relation_types"],
                "property_types": view["property_types"],
                "actor_summary": view["actor_summary"],
                "beneficiary_summary": view["beneficiary_summary"],
            }
            updated_document = dict(document)
            updated_document["processing"] = processing
            updated_documents[document_id] = updated_document
            job["processed_document_count"] = int(job.get("processed_document_count", 0)) + 1
            job["document_stage_runs"][document_id] = {"document_synthesizer": document_stage}
        except Exception as exc:
            job["failed_document_ids"].append(document_id)
            job["retryable_targets"]["documents"].append(document_id)
            job["document_stage_runs"][document_id] = {
                "document_synthesizer": _stage_result(
                    status="failed",
                    role="document_synthesizer",
                    error=str(exc)[:300],
                )
            }

    candidate_count = sum(1 for entry in registry.values() if entry.get("status") == "candidate")
    active_count = sum(1 for entry in registry.values() if entry.get("status") == "active")
    job["candidate_entry_count"] = candidate_count
    job["active_entry_count"] = active_count
    if job["failed_chunk_ids"] or job["failed_document_ids"]:
        job["status"] = "partial" if job["processed_chunk_count"] or job["processed_document_count"] else "failed"
    else:
        job["status"] = "completed"
    job["updated_at"] = _utcnow().isoformat()

    return {
        "job": job,
        "registry_entries": sorted(registry.values(), key=lambda item: (str(item.get("kind")), str(item.get("key")))),
        "chunk_assertions": assertions,
        "document_views": document_views,
        "updated_paragraphs": updated_paragraphs,
        "updated_documents": updated_documents,
        "updated_chunk_projections": updated_chunk_projections,
        "projected_relation_edges": sorted(projected_edges.values(), key=lambda item: str(item.get("edge_id"))),
    }


def retry_agentic_corpus_enrichment(
    *,
    project_id: str,
    import_job_id: str,
    documents: List[Dict[str, Any]],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    chunk_search_documents: List[Dict[str, Any]],
    relation_edges: List[Dict[str, Any]],
    existing_registry_entries: Optional[List[Dict[str, Any]]] = None,
    target_type: str,
    target_ids: List[str],
) -> Dict[str, Any]:
    if target_type not in {"chunk", "document"}:
        raise ValueError("target_type must be chunk or document")
    return run_agentic_corpus_enrichment(
        project_id=project_id,
        import_job_id=import_job_id,
        documents=documents,
        pages=pages,
        paragraphs=paragraphs,
        chunk_search_documents=chunk_search_documents,
        relation_edges=relation_edges,
        existing_registry_entries=existing_registry_entries,
        target_document_ids=target_ids if target_type == "document" else None,
        target_paragraph_ids=target_ids if target_type == "chunk" else None,
    )
