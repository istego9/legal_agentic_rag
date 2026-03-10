"""Rules-first, token-efficient router for case-judgment extraction."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from legal_rag_api.azure_llm import AzureLLMClient


PIPELINE_NAME = "pipeline_1_case_judgment_router"
PIPELINE_VERSION = "v1"
PROMPT_VERSION = "case_judgment_router_v1"
SCHEMA_VERSION = "case_judgment_bundle.v1"

_ALLOWED_SUBTYPES = {"short_order", "order_with_reasons", "judgment", "unknown"}
_ALLOWED_PROFILES = {
    "short_order_parser",
    "full_reasons_parser",
    "full_judgment_parser",
    "unknown",
}


@dataclass
class RouterDecision:
    doc_type: str
    document_subtype: str
    routing_profile: str
    confidence: float
    route_status: str
    one_line_rationale: str
    rule_hits: List[str]
    conflicts: List[str]
    missing_markers: List[str]
    marker_state: Dict[str, Any]
    feature_state: Dict[str, Any]
    llm_calls: int
    token_usage: Dict[str, int]


def _load_prompt_markdown(name: str = PROMPT_VERSION) -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "packages" / "prompts" / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _normalize_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    return compact[:limit]


def marker_scan(first_two_pages_text: str, filename: str = "", metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    source = f"{filename}\n{first_two_pages_text}"
    lowered = source.lower()
    metadata = metadata or {}

    has_order_with_reasons_phrase = bool(
        re.search(r"\border\s+with\s+reasons\b", lowered)
        or re.search(r"\border\b.*\breasons\b", lowered)
    )
    has_judgment_marker = bool(re.search(r"\bjudg(?:e)?ment\b", lowered))
    has_order_marker = bool(re.search(r"\border\b", lowered))
    has_reasons_heading = bool(
        re.search(r"\breasons\b", lowered)
        or re.search(r"\bgrounds\s+of\s+appeal\b", lowered)
        or re.search(r"\bexecutive\s+summary\b", lowered)
    )
    has_case_number = bool(re.search(r"\b[A-Z]{2,4}\s*\d{1,5}/\d{4}\b", source))
    has_court_marker = bool(re.search(r"\bcourt\b", lowered))

    return {
        "has_order_with_reasons_phrase": has_order_with_reasons_phrase,
        "has_judgment_marker": has_judgment_marker,
        "has_order_marker": has_order_marker,
        "has_reasons_heading": has_reasons_heading,
        "has_case_number": has_case_number,
        "has_court_marker": has_court_marker,
        "metadata_hint_doc_type": str(metadata.get("doc_type", "") or "").strip().lower(),
    }


def page_feature_scan(first_two_pages_text: str) -> Dict[str, Any]:
    text = first_two_pages_text or ""
    lowered = text.lower()
    numbered_orders = len(re.findall(r"(?:^|\n)\s*\d{1,3}[\.)]\s+[A-Z]", text))
    numbered_paragraphs = len(re.findall(r"(?:^|\n)\s*\[?\d{1,3}\]?\s+", text))

    order_action_hits = 0
    for marker in (
        "is granted",
        "is dismissed",
        "is stayed",
        "shall file",
        "shall pay",
        "costs",
    ):
        if marker in lowered:
            order_action_hits += 1

    reasoning_hits = 0
    for marker in (
        "for these reasons",
        "i am satisfied",
        "i conclude",
        "in my judgment",
        "ground",
        "permission to appeal",
    ):
        if marker in lowered:
            reasoning_hits += 1

    return {
        "numbered_orders": numbered_orders,
        "numbered_paragraphs": numbered_paragraphs,
        "order_action_hits": order_action_hits,
        "reasoning_hits": reasoning_hits,
    }


def rule_router(marker_state: Dict[str, Any], feature_state: Dict[str, Any]) -> Tuple[str, str, List[str], List[str], List[str], str]:
    hits: List[str] = []
    conflicts: List[str] = []
    missing: List[str] = []

    has_order_with_reasons = bool(marker_state.get("has_order_with_reasons_phrase"))
    has_order_marker = bool(marker_state.get("has_order_marker"))
    has_reasons_heading = bool(marker_state.get("has_reasons_heading"))
    has_judgment_marker = bool(marker_state.get("has_judgment_marker"))
    numbered_orders = int(feature_state.get("numbered_orders", 0) or 0)
    order_action_hits = int(feature_state.get("order_action_hits", 0) or 0)
    reasoning_hits = int(feature_state.get("reasoning_hits", 0) or 0)

    if has_order_with_reasons:
        hits.append("order_with_reasons_phrase")
    if has_reasons_heading:
        hits.append("reasons_heading")
    if has_judgment_marker:
        hits.append("judgment_marker")
    if numbered_orders >= 3:
        hits.append("numbered_orders>=3")
    if order_action_hits >= 2:
        hits.append("order_actions>=2")
    if reasoning_hits >= 2:
        hits.append("reasoning_hits>=2")

    if has_judgment_marker and has_order_marker and numbered_orders >= 3 and reasoning_hits >= 2:
        conflicts.append("mixed_order_and_judgment_markers")

    if not marker_state.get("has_case_number"):
        missing.append("case_number")
    if not marker_state.get("has_court_marker"):
        missing.append("court_marker")

    if has_order_with_reasons or (has_order_marker and has_reasons_heading and numbered_orders >= 2 and order_action_hits >= 1):
        return (
            "order_with_reasons",
            "full_reasons_parser",
            hits,
            conflicts,
            missing,
            "operative orders with reasons markers",
        )

    if has_judgment_marker and reasoning_hits >= 2:
        return (
            "judgment",
            "full_judgment_parser",
            hits,
            conflicts,
            missing,
            "judgment marker with reasoning density",
        )

    if has_order_marker and not has_reasons_heading and order_action_hits >= 1:
        return (
            "short_order",
            "short_order_parser",
            hits,
            conflicts,
            missing,
            "order marker without reasons heading",
        )

    return (
        "unknown",
        "unknown",
        hits,
        conflicts,
        missing,
        "insufficient deterministic signals",
    )


def routing_confidence(*, rule_hits: List[str], conflicts: List[str], missing_markers: List[str], subtype: str) -> float:
    score = 0.2
    score += min(0.5, len(rule_hits) * 0.09)
    score -= min(0.25, len(conflicts) * 0.2)
    score -= min(0.2, len(missing_markers) * 0.06)
    if subtype == "unknown":
        score = min(score, 0.55)
    return max(0.0, min(1.0, round(score, 4)))


def should_fallback(*, subtype: str, confidence: float, conflicts: List[str], marker_state: Dict[str, Any]) -> bool:
    if subtype == "unknown":
        return True
    if confidence < 0.62:
        return True
    if conflicts:
        return True
    if not marker_state.get("has_case_number"):
        return True
    return False


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


def _llm_router_prompt(
    *,
    filename_metadata: Dict[str, Any],
    marker_summary: Dict[str, Any],
    first_page_excerpt: str,
    second_page_excerpt: str,
) -> Tuple[str, str]:
    instructions = _load_prompt_markdown(PROMPT_VERSION)
    system_prompt = (
        "You classify legal case documents for parser routing. Return strict JSON only. "
        "Do not guess and prefer unknown over fabricated certainty."
    )
    user_prompt = (
        "Use the schema exactly:\n"
        '{"doc_type":"case|other","document_subtype":"short_order|order_with_reasons|judgment|unknown",'
        '"routing_profile":"short_order_parser|full_reasons_parser|full_judgment_parser|unknown",'
        '"confidence":0.0,"one_line_rationale":"string"}.\n\n'
        f"Prompt reference:\n{instructions[:1200]}\n\n"
        f"Filename metadata:\n{json.dumps(filename_metadata, ensure_ascii=False)}\n\n"
        f"Marker summary:\n{json.dumps(marker_summary, ensure_ascii=False)}\n\n"
        f"First page excerpt:\n{first_page_excerpt}\n\n"
        f"Second page excerpt:\n{second_page_excerpt}\n"
    )
    return system_prompt, user_prompt


async def _run_llm_router(
    client: AzureLLMClient,
    *,
    filename_metadata: Dict[str, Any],
    marker_summary: Dict[str, Any],
    first_page_excerpt: str,
    second_page_excerpt: str,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    system_prompt, prompt = _llm_router_prompt(
        filename_metadata=filename_metadata,
        marker_summary=marker_summary,
        first_page_excerpt=first_page_excerpt,
        second_page_excerpt=second_page_excerpt,
    )
    completion, usage = await client.complete_chat(
        prompt,
        user_context={"task": "case_judgment_router", "prompt_version": PROMPT_VERSION},
        system_prompt=system_prompt,
        max_tokens=180,
        temperature=0.0,
    )
    payload = _parse_json_object(completion)
    return payload, usage


def _llm_router(
    client: AzureLLMClient,
    *,
    filename_metadata: Dict[str, Any],
    marker_summary: Dict[str, Any],
    first_page_excerpt: str,
    second_page_excerpt: str,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    return asyncio.run(
        _run_llm_router(
            client,
            filename_metadata=filename_metadata,
            marker_summary=marker_summary,
            first_page_excerpt=first_page_excerpt,
            second_page_excerpt=second_page_excerpt,
        )
    )


def route_case_judgment_document(
    *,
    filename: str,
    first_page_text: str,
    second_page_text: str,
    metadata: Dict[str, Any] | None = None,
    llm_client: AzureLLMClient | None = None,
) -> RouterDecision:
    metadata = metadata or {}
    first_excerpt = _normalize_text(first_page_text, limit=900)
    second_excerpt = _normalize_text(second_page_text, limit=900)
    first_two_pages_text = f"{first_excerpt}\n{second_excerpt}".strip()

    markers = marker_scan(first_two_pages_text, filename=filename, metadata=metadata)
    features = page_feature_scan(first_two_pages_text)
    subtype, profile, hits, conflicts, missing, rationale = rule_router(markers, features)
    confidence = routing_confidence(
        rule_hits=hits,
        conflicts=conflicts,
        missing_markers=missing,
        subtype=subtype,
    )
    route_status = "routed"
    llm_calls = 0
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    if should_fallback(subtype=subtype, confidence=confidence, conflicts=conflicts, marker_state=markers):
        client = llm_client or AzureLLMClient()
        if client.config.enabled:
            llm_calls = 1
            raw_payload, usage = _llm_router(
                client,
                filename_metadata={"filename": filename, **metadata},
                marker_summary={**markers, **features},
                first_page_excerpt=first_excerpt,
                second_page_excerpt=second_excerpt,
            )
            token_usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            }
            llm_subtype = str(raw_payload.get("document_subtype", "unknown")).strip().lower()
            llm_profile = str(raw_payload.get("routing_profile", "unknown")).strip()
            if llm_subtype in _ALLOWED_SUBTYPES and llm_profile in _ALLOWED_PROFILES:
                subtype = llm_subtype
                profile = llm_profile
                route_status = "fallback_used"
                try:
                    confidence = float(raw_payload.get("confidence", confidence))
                except Exception:
                    pass
                confidence = max(0.0, min(1.0, round(confidence, 4)))
                rationale = str(raw_payload.get("one_line_rationale", rationale)).strip() or rationale
            else:
                route_status = "fallback_failed"
        else:
            route_status = "not_required"

    doc_type = "case"
    if subtype == "unknown" and not markers.get("has_court_marker"):
        doc_type = str(markers.get("metadata_hint_doc_type") or "other") or "other"

    return RouterDecision(
        doc_type=doc_type,
        document_subtype=subtype,
        routing_profile=profile,
        confidence=confidence,
        route_status=route_status,
        one_line_rationale=rationale,
        rule_hits=hits,
        conflicts=conflicts,
        missing_markers=missing,
        marker_state=markers,
        feature_state=features,
        llm_calls=llm_calls,
        token_usage=token_usage,
    )


def choose_router_model() -> Tuple[str, str]:
    model_name = os.getenv("CASE_JUDGMENT_ROUTER_MODEL", "gpt-5-mini")
    reasoning_effort = os.getenv("CASE_JUDGMENT_ROUTER_REASONING_EFFORT", "minimal")
    return model_name, reasoning_effort
