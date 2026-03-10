"""Document-level extractor for case judgment pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from legal_rag_api.azure_llm import AzureLLMClient
from packages.contracts.case_judgment_bundle_validation import load_bundle_mirror, validate_payload


PIPELINE_NAME = "pipeline_2_case_judgment_extractor"
PIPELINE_VERSION = "v1"
PROMPT_VERSION = "case_judgment_document_extractor_v1"
SCHEMA_VERSION = "case_judgment_bundle.v1"

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


@dataclass
class DocumentExtractionResult:
    payload: Dict[str, Any]
    validation_errors: List[str]
    validation_status: str
    confidence_score: float
    token_usage: Dict[str, int]
    llm_calls: int


def _load_prompt_markdown(name: str = PROMPT_VERSION) -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "packages" / "prompts" / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _compact_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def _normalize_date(value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

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


def _extract_dates(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for token in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text or ""):
        if token not in seen:
            seen.add(token)
            out.append(token)
    for match in re.findall(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", text or ""):
        value = _normalize_date(match)
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    for match in re.findall(r"\b[A-Za-z]+\s+\d{1,2},\s*\d{4}\b", text or ""):
        value = _normalize_date(match)
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _extract_case_number(text: str) -> str | None:
    match = re.search(r"\b([A-Z]{2,4}\s*\d{1,5}/\d{4})\b", text or "")
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_court_name(text: str) -> str | None:
    for line in (text or "").splitlines():
        compact = _compact_text(line, 240)
        lowered = compact.lower()
        if "court" in lowered and len(compact) >= 8:
            return compact
    return None


def _infer_court_level(court_name: str, full_text: str) -> str:
    source = f"{court_name}\n{full_text}".lower()
    if "court of appeal" in source:
        return "Court of Appeal"
    if "high court" in source:
        return "High Court"
    if "first instance" in source:
        return "Court of First Instance"
    if "supreme" in source:
        return "Supreme Court"
    return "Unknown Court Level"


def _extract_caption_party_names(text: str) -> List[str]:
    names: List[str] = []
    seen = set()
    for match in re.finditer(r"\b([A-Z][A-Z\-]{2,})\b", text or ""):
        token = match.group(1).title()
        if token.lower() in {"between", "and", "court", "appeal", "judgment", "order", "reasons"}:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(token)
        if len(names) >= 12:
            break
    return names


def _order_effect_label(order_text: str) -> str:
    lowered = order_text.lower()
    if "granted" in lowered and "permission" in lowered:
        return "permission_granted"
    if "dismissed" in lowered:
        return "application_dismissed"
    if "stayed" in lowered or "stay" in lowered:
        return "stay_granted"
    if "cost" in lowered:
        return "costs_direction"
    if "shall file" in lowered or "file and serve" in lowered:
        return "filing_direction"
    if "hearing" in lowered:
        return "hearing_direction"
    return "direction"


def _extract_operative_orders(
    paragraphs: List[Dict[str, Any]],
    page_num_by_id: Dict[str, int],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    item_no = 0
    for para in paragraphs:
        text = _compact_text(str(para.get("text", "") or ""), 1200)
        if not text:
            continue
        looks_like_order = bool(re.search(r"\b(is granted|is dismissed|is stayed|shall|must)\b", text, re.IGNORECASE))
        looks_numbered = bool(re.match(r"^\(?\d{1,3}\)?[\.)]\s+", text))
        if not (looks_like_order or looks_numbered):
            continue
        item_no += 1
        page_number_1 = int(page_num_by_id.get(str(para.get("page_id", "")), 0) or 0) + 1
        out.append(
            {
                "item_no": item_no,
                "order_text": text,
                "order_effect_label": _order_effect_label(text),
                "page_number_1": page_number_1,
            }
        )
        if item_no >= 24:
            break
    return out


def _page_map(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in sorted(pages, key=lambda item: int(item.get("page_num", 0) or 0)):
        page_num = int(page.get("page_num", 0) or 0)
        out.append(
            {
                "page_number_1": page_num + 1,
                "page_number_0": page_num,
                "page_id_internal": str(page.get("source_page_id") or page.get("page_id") or ""),
                "page_class": str(page.get("page_class", "body") or "body"),
            }
        )
    return out


def _section_map(orders: List[Dict[str, Any]], page_count: int, subtype: str) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = [
        {
            "section_id": "sec_000",
            "section_kind_case": "header_and_caption",
            "page_start": 1,
            "page_end": min(2, max(1, page_count)),
            "meaning": "front matter and caption",
        }
    ]
    if orders:
        pages = [int(item.get("page_number_1", 1) or 1) for item in orders]
        sections.append(
            {
                "section_id": "sec_001",
                "section_kind_case": "operative_order_item",
                "order_item_range": [1, len(orders)],
                "page_start": min(pages),
                "page_end": max(pages),
                "meaning": "operative orders",
            }
        )
    if subtype in {"order_with_reasons", "judgment"}:
        sections.append(
            {
                "section_id": "sec_002",
                "section_kind_case": "ground_statement_and_reasoning",
                "page_start": min(2, max(1, page_count)),
                "page_end": max(1, page_count),
                "meaning": "reasons and legal analysis",
            }
        )
    return sections


def _base_payload(
    *,
    document: Dict[str, Any],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    routing_state: Dict[str, Any],
) -> Dict[str, Any]:
    first_page = pages[0] if pages else {}
    first_page_text = str(first_page.get("text", "") or "")
    first_two = "\n".join(str(item.get("text", "") or "") for item in pages[:2])
    all_text = "\n".join(str(item.get("text", "") or "") for item in pages)

    proceeding_no = _extract_case_number(first_two) or str(document.get("case_id") or "").strip()
    if not proceeding_no:
        proceeding_no = f"UNKNOWN-{str(document.get('document_id', 'doc')).upper()}"

    court_name = _extract_court_name(first_two) or str(document.get("title") or "").strip()
    if not court_name:
        court_name = "Unknown Court"

    candidate_dates = _extract_dates(first_two)
    if not candidate_dates:
        candidate_dates = _extract_dates(all_text)
    decision_date = candidate_dates[0] if candidate_dates else str(document.get("edition_date") or "")
    decision_date = _normalize_date(decision_date) or "1970-01-01"

    page_count = len(pages) if pages else int(document.get("page_count", 1) or 1)

    party_names = _extract_caption_party_names(first_page_text)
    parties = [
        {
            "name_raw": name.upper(),
            "name_normalized": name,
            "role_in_document": f"party_{idx + 1}",
            "cluster_roles": [],
        }
        for idx, name in enumerate(party_names)
    ]

    page_num_by_id = {str(item.get("page_id", "")): int(item.get("page_num", 0) or 0) for item in pages}
    orders = _extract_operative_orders(paragraphs, page_num_by_id)
    if not orders and paragraphs:
        # Keep contract-required field populated with at least one grounded item.
        top = paragraphs[0]
        top_text = _compact_text(str(top.get("text", "") or ""), 1200)
        if top_text:
            orders = [
                {
                    "item_no": 1,
                    "order_text": top_text,
                    "order_effect_label": _order_effect_label(top_text),
                    "page_number_1": int(page_num_by_id.get(str(top.get("page_id", "")), 0) or 0) + 1,
                }
            ]

    document_subtype = str(routing_state.get("document_subtype", "unknown") or "unknown")
    if document_subtype not in {
        "judgment",
        "order_with_reasons",
        "reasons_for_order",
        "permission_to_appeal_order",
        "enforcement_order_with_reasons",
        "interlocutory_order_with_reasons",
        "short_order",
        "unknown",
    }:
        document_subtype = "unknown"

    quality_flags: List[str] = []
    if decision_date == "1970-01-01":
        quality_flags.append("missing_decision_date")
    if not party_names:
        quality_flags.append("missing_parties")
    if not proceeding_no.startswith("UNKNOWN-") and not re.search(r"\d", proceeding_no):
        quality_flags.append("weak_proceeding_no")

    confidence = 0.55
    if orders:
        confidence += 0.1
    if party_names:
        confidence += 0.1
    if decision_date != "1970-01-01":
        confidence += 0.1
    if document_subtype != "unknown":
        confidence += 0.08
    confidence = max(0.0, min(1.0, round(confidence, 4)))

    case_cluster_id = str(document.get("case_cluster_id") or "").strip()
    if not case_cluster_id:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", proceeding_no).strip("_")
        case_cluster_id = f"{normalized.lower()}_cluster" if normalized else f"{document.get('document_id', 'doc')}_cluster"

    payload: Dict[str, Any] = {
        "document_id": str(document.get("document_id") or ""),
        "competition_pdf_id": str(document.get("pdf_id") or document.get("competition_pdf_id") or ""),
        "canonical_slug": str(document.get("canonical_doc_id") or document.get("pdf_id") or ""),
        "case_cluster_id": case_cluster_id,
        "proceeding_no": proceeding_no,
        "related_root_matter_no": str(document.get("case_id") or proceeding_no),
        "doc_type": "case",
        "document_category": "case_decision",
        "document_subtype": document_subtype,
        "case_stage": "unknown",
        "court_name": court_name,
        "court_level": _infer_court_level(court_name, all_text),
        "case_caption": _compact_text(first_page_text, 320),
        "decision_date": decision_date,
        "date_of_issue": decision_date,
        "time_of_issue_local": "",
        "parties": parties,
        "applications_under_determination": [],
        "operative_orders": orders,
        "procedural_event_refs": [],
        "authority_refs": [],
        "issues_present": [],
        "document_one_liner": _compact_text(str(paragraphs[0].get("text", "") if paragraphs else ""), 180),
        "document_summary": _compact_text(" ".join(str(item.get("text", "") or "") for item in paragraphs[:6]), 1200),
        "page_count": page_count,
        "page_map": _page_map(pages),
        "section_map": _section_map(orders, page_count, document_subtype),
        "confidence": confidence,
        "quality_flags": quality_flags,
    }
    return payload


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


def _llm_doc_prompt(routing_state: Dict[str, Any], context: Dict[str, Any]) -> Tuple[str, str]:
    guidance = _load_prompt_markdown(PROMPT_VERSION)
    system_prompt = (
        "You extract document-level case metadata as strict JSON. "
        "Do not guess unknown facts. Keep all values grounded in provided context."
    )
    user_prompt = (
        "Return JSON using the same keys as the provided base payload. "
        "Only override values with stronger grounded evidence from context.\n\n"
        f"Prompt guidance:\n{guidance[:1500]}\n\n"
        f"Routing state:\n{json.dumps(routing_state, ensure_ascii=False)}\n\n"
        f"Base payload:\n{json.dumps(context.get('base_payload', {}), ensure_ascii=False)}\n\n"
        f"Front matter excerpt:\n{context.get('front_matter_excerpt', '')}\n\n"
        f"Operative orders excerpt:\n{context.get('operative_orders_excerpt', '')}\n\n"
        f"Reasoning map:\n{json.dumps(context.get('reasoning_map', []), ensure_ascii=False)}\n"
    )
    return system_prompt, user_prompt


async def _run_llm_doc(
    client: AzureLLMClient,
    *,
    routing_state: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    system_prompt, prompt = _llm_doc_prompt(routing_state, context)
    completion, usage = await client.complete_chat(
        prompt,
        user_context={"task": "case_judgment_document_extractor", "prompt_version": PROMPT_VERSION},
        system_prompt=system_prompt,
        max_tokens=850,
        temperature=0.0,
    )
    return _parse_json_object(completion), usage


def _llm_doc(
    client: AzureLLMClient,
    *,
    routing_state: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    return asyncio.run(_run_llm_doc(client, routing_state=routing_state, context=context))


def _merge_llm_payload(base: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(llm_payload, dict):
        return base
    merged = dict(base)
    for key in (
        "canonical_slug",
        "case_cluster_id",
        "proceeding_no",
        "related_root_matter_no",
        "document_category",
        "document_subtype",
        "case_stage",
        "court_name",
        "court_level",
        "case_caption",
        "decision_date",
        "date_of_issue",
        "time_of_issue_local",
        "document_one_liner",
        "document_summary",
    ):
        if key not in llm_payload:
            continue
        value = llm_payload.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    for key in (
        "parties",
        "applications_under_determination",
        "operative_orders",
        "procedural_event_refs",
        "authority_refs",
        "issues_present",
        "page_map",
        "section_map",
        "quality_flags",
    ):
        if key in llm_payload and isinstance(llm_payload.get(key), list):
            merged[key] = llm_payload.get(key)
    if "page_count" in llm_payload:
        try:
            merged["page_count"] = max(1, int(llm_payload.get("page_count") or merged.get("page_count") or 1))
        except Exception:
            pass
    if "confidence" in llm_payload:
        try:
            merged["confidence"] = max(0.0, min(1.0, float(llm_payload.get("confidence"))))
        except Exception:
            pass
    merged["doc_type"] = "case"
    merged["decision_date"] = _normalize_date(str(merged.get("decision_date", ""))) or "1970-01-01"
    merged["date_of_issue"] = _normalize_date(str(merged.get("date_of_issue", ""))) or merged["decision_date"]
    return merged


def extract_case_judgment_document(
    *,
    document: Dict[str, Any],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    routing_state: Dict[str, Any],
    use_llm: bool = True,
    llm_client: AzureLLMClient | None = None,
) -> DocumentExtractionResult:
    base_payload = _base_payload(
        document=document,
        pages=pages,
        paragraphs=paragraphs,
        routing_state=routing_state,
    )

    llm_calls = 0
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    payload = dict(base_payload)

    if use_llm:
        client = llm_client or AzureLLMClient()
        if client.config.enabled:
            llm_calls = 1
            context = {
                "base_payload": base_payload,
                "front_matter_excerpt": _compact_text("\n".join(str(item.get("text", "") or "") for item in pages[:2]), 3000),
                "operative_orders_excerpt": _compact_text("\n".join(item.get("order_text", "") for item in base_payload.get("operative_orders", [])[:8]), 2600),
                "reasoning_map": base_payload.get("section_map", [])[:8],
            }
            llm_payload, usage = _llm_doc(client, routing_state=routing_state, context=context)
            token_usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            }
            payload = _merge_llm_payload(payload, llm_payload)

    schemas, _ = load_bundle_mirror()
    errors = validate_payload(
        schemas["full_judgment_case_document.schema.json"],
        payload,
        path="case_document_extraction",
    )

    confidence_score = float(payload.get("confidence", 0.0) or 0.0)
    validation_status = "passed" if not errors else "failed"
    if not errors and confidence_score < float(os.getenv("CASE_JUDGMENT_DOC_CONFIDENCE_WARN", "0.6")):
        validation_status = "warning"

    return DocumentExtractionResult(
        payload=payload,
        validation_errors=errors,
        validation_status=validation_status,
        confidence_score=max(0.0, min(1.0, round(confidence_score, 4))),
        token_usage=token_usage,
        llm_calls=llm_calls,
    )


def choose_document_model() -> Tuple[str, str]:
    return (
        os.getenv("CASE_JUDGMENT_DOCUMENT_MODEL", "gpt-5-mini"),
        os.getenv("CASE_JUDGMENT_DOCUMENT_REASONING_EFFORT", "minimal"),
    )
