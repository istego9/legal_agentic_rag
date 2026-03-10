"""Chunk-level extractor for case judgment pipeline."""

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


PROMPT_VERSION = "case_judgment_chunk_extractor_v1"
SCHEMA_VERSION = "case_judgment_bundle.v1"


@dataclass
class ChunkExtractionResult:
    chunks: List[Dict[str, Any]]
    validation_errors: List[str]
    validation_status: str
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


def _extract_dates(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for token in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text or ""):
        if token not in seen:
            out.append(token)
            seen.add(token)
    return out


def _classify_chunk_type(text: str, paragraph_class: str) -> Tuple[str, str]:
    lowered = text.lower()
    paragraph_class = (paragraph_class or "").lower()
    if re.match(r"^[A-Z\s\-]{10,}$", text.strip()):
        return "heading", "header"
    if "between" in lowered and " v " in lowered:
        return "caption_line", "caption_parties_block"
    if paragraph_class in {"recital", "case_excerpt"} or lowered.startswith("upon "):
        return "recital_paragraph", "recital_block"
    if re.search(r"\b(is granted|is dismissed|is stayed|shall|must)\b", lowered):
        return "order_item", "operative_order_item"
    if re.search(r"\bissued by\b|\bassistant registrar\b|\bchief justice\b", lowered):
        return "issuance_metadata", "issuance_block"
    if re.search(r"\bground\s+\d+\b", lowered):
        return "numbered_reasoning_paragraph", "ground_reasoning"
    if re.search(r"\breasons\b|\bfor these reasons\b|\bi conclude\b", lowered):
        return "summary_paragraph", "analysis"
    if re.search(r"\btherefore\b|\bin conclusion\b", lowered):
        return "conclusion_paragraph", "global_conclusion"
    return "other", "unknown"


def _extract_ground_fields(text: str) -> Tuple[str | None, str | None]:
    lowered = text.lower()
    owner = None
    if "first applicant" in lowered:
        owner = "first_applicant"
    elif "second" in lowered and "third" in lowered and "applicant" in lowered:
        owner = "second_and_third_applicants"
    elif "judgment creditor" in lowered:
        owner = "judgment_creditor"

    ground = None
    match = re.search(r"\bground\s+([0-9]+(?:\s*(?:and|&)\s*[0-9]+)?)\b", text, re.IGNORECASE)
    if match:
        ground = re.sub(r"\s+", "_", match.group(1).strip())
    return owner, ground


def _extract_authority_refs(text: str) -> List[str]:
    refs: List[str] = []
    seen = set()
    for pattern in (
        r"\bRDC\s+[0-9]+(?:\.[0-9]+)*(?:\([0-9]+\))?\b",
        r"\bPart\s+[0-9]+\b",
        r"\b[A-Z]{2,5}\s*\d{1,5}/\d{4}\b",
    ):
        for match in re.findall(pattern, text or "", flags=re.IGNORECASE):
            token = _compact_text(match, 120)
            key = token.lower()
            if not token or key in seen:
                continue
            seen.add(key)
            refs.append(token)
    return refs[:16]


def _extract_order_effect(text: str, chunk_type: str) -> str | None:
    if chunk_type != "order_item":
        return None
    lowered = text.lower()
    if "permission" in lowered and "granted" in lowered:
        return "permission_granted_partial"
    if "dismissed" in lowered:
        return "application_dismissed"
    if "stayed" in lowered or "stay" in lowered:
        return "stay_granted_partial"
    if "cost" in lowered and "shall pay" in lowered:
        return "costs_payable"
    if "file" in lowered and "serve" in lowered:
        return "filing_direction"
    if "hearing" in lowered:
        return "hearing_direction"
    return "direction"


def _chunk_summary(text: str) -> str:
    compact = _compact_text(text, 600)
    if not compact:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", compact)
    if parts and parts[0]:
        return parts[0][:320]
    return compact[:320]


def _party_roles(parties: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for row in parties:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role_in_document", "")).strip()
        name = str(row.get("name_normalized", row.get("name_raw", ""))).strip()
        if not role or not name:
            continue
        out.append({"role": role, "name": name})
    return out


def _judge_names(document_payload: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    issued_by = document_payload.get("issued_by")
    if isinstance(issued_by, dict):
        name = str(issued_by.get("name", "")).strip()
        if name:
            names.append(name)
    seen = set()
    out: List[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out[:4]


def _chunk_base_payload(
    *,
    paragraph: Dict[str, Any],
    page: Dict[str, Any],
    document_payload: Dict[str, Any],
    chunk_order_in_doc: int,
) -> Dict[str, Any]:
    text = _compact_text(str(paragraph.get("text", "") or ""), 1400)
    chunk_type, section_kind_case = _classify_chunk_type(text, str(paragraph.get("paragraph_class", "") or ""))
    ground_owner, ground_no = _extract_ground_fields(text)

    page_number_0 = int(page.get("page_num", 0) or 0)
    page_number_1 = page_number_0 + 1
    chunk_id = str(paragraph.get("paragraph_id") or "")
    if not chunk_id:
        chunk_id = f"{document_payload.get('document_id', 'doc')}_chunk_{chunk_order_in_doc:04d}"

    payload: Dict[str, Any] = {
        "chunk_id": chunk_id,
        "page_number_1": page_number_1,
        "page_number_0": page_number_0,
        "page_id_internal": str(page.get("source_page_id") or page.get("page_id") or ""),
        "page_id_zero_based": str(page.get("source_page_id") or page.get("page_id") or ""),
        "page_id_one_based": str(page.get("source_page_id") or page.get("page_id") or ""),
        "chunk_order_in_doc": chunk_order_in_doc,
        "chunk_order_in_page": int(paragraph.get("paragraph_index", chunk_order_in_doc) or chunk_order_in_doc),
        "chunk_type": chunk_type,
        "section_kind_case": section_kind_case,
        "case_number": str(document_payload.get("proceeding_no") or ""),
        "case_cluster_id": str(document_payload.get("case_cluster_id") or ""),
        "document_subtype": str(document_payload.get("document_subtype") or "unknown"),
        "paragraph_no": int(paragraph.get("paragraph_index", 0) or 0) + 1,
        "text_clean": text,
        "chunk_summary": _chunk_summary(text),
        "party_roles": _party_roles(document_payload.get("parties", [])),
        "judge_names": _judge_names(document_payload),
        "issue_tags": [str(item) for item in document_payload.get("issues_present", []) if str(item).strip()],
        "authority_refs": _extract_authority_refs(text),
        "answer_candidate_types": ["free_text"],
        "date_mentions": _extract_dates(text),
        "confidence": 0.66,
        "quality_flags": [],
    }

    if ground_owner:
        payload["ground_owner"] = ground_owner
    if ground_no:
        payload["ground_no"] = ground_no

    effect = _extract_order_effect(text, chunk_type)
    if effect:
        payload["order_effect_label"] = effect
        payload["answer_candidate_types"] = ["boolean", "free_text", "date"]

    if chunk_type == "heading":
        payload["answer_candidate_types"] = ["names", "free_text"]
    elif chunk_type == "caption_line":
        payload["answer_candidate_types"] = ["names"]

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


def _llm_chunk_prompt(document_context: Dict[str, Any], chunk_context: Dict[str, Any], chunk_text: str) -> Tuple[str, str]:
    guidance = _load_prompt_markdown(PROMPT_VERSION)
    system_prompt = (
        "You extract chunk-level legal metadata as strict JSON. "
        "Do not fabricate fields that are not supported by chunk evidence."
    )
    user_prompt = (
        "Return JSON using same keys as provided deterministic chunk context. "
        "Only override fields when evidence is explicit in chunk text.\n\n"
        f"Prompt guidance:\n{guidance[:1300]}\n\n"
        f"Document context:\n{json.dumps(document_context, ensure_ascii=False)}\n\n"
        f"Chunk context:\n{json.dumps(chunk_context, ensure_ascii=False)}\n\n"
        f"Chunk text:\n{chunk_text}\n"
    )
    return system_prompt, user_prompt


async def _run_llm_chunk(
    client: AzureLLMClient,
    *,
    document_context: Dict[str, Any],
    chunk_context: Dict[str, Any],
    chunk_text: str,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    system_prompt, prompt = _llm_chunk_prompt(document_context, chunk_context, chunk_text)
    completion, usage = await client.complete_chat(
        prompt,
        user_context={"task": "case_judgment_chunk_extractor", "prompt_version": PROMPT_VERSION},
        system_prompt=system_prompt,
        max_tokens=420,
        temperature=0.0,
    )
    return _parse_json_object(completion), usage


def _llm_chunk(
    client: AzureLLMClient,
    *,
    document_context: Dict[str, Any],
    chunk_context: Dict[str, Any],
    chunk_text: str,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    return asyncio.run(
        _run_llm_chunk(
            client,
            document_context=document_context,
            chunk_context=chunk_context,
            chunk_text=chunk_text,
        )
    )


def _merge_llm_chunk_payload(base: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(llm_payload, dict):
        return base
    merged = dict(base)
    for key in (
        "chunk_type",
        "section_kind_case",
        "ground_owner",
        "ground_no",
        "order_effect_label",
        "chunk_summary",
    ):
        value = llm_payload.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    for key in ("issue_tags", "authority_refs", "answer_candidate_types", "date_mentions", "party_roles", "judge_names", "quality_flags"):
        value = llm_payload.get(key)
        if isinstance(value, list):
            merged[key] = value
    for key in ("paragraph_no", "page_number_1", "page_number_0"):
        if key in llm_payload:
            try:
                merged[key] = int(llm_payload.get(key))
            except Exception:
                pass
    text_clean = llm_payload.get("text_clean")
    if isinstance(text_clean, str) and text_clean.strip():
        merged["text_clean"] = _compact_text(text_clean, 1400)
    if "confidence" in llm_payload:
        try:
            merged["confidence"] = max(0.0, min(1.0, float(llm_payload.get("confidence"))))
        except Exception:
            pass
    return merged


def extract_case_judgment_chunks(
    *,
    document_payload: Dict[str, Any],
    pages: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    use_llm: bool = True,
    llm_client: AzureLLMClient | None = None,
    max_chunks: int | None = None,
) -> ChunkExtractionResult:
    page_by_id = {str(page.get("page_id", "")): page for page in pages}
    ordered = sorted(
        paragraphs,
        key=lambda row: (
            int((page_by_id.get(str(row.get("page_id", "")), {}) or {}).get("page_num", 0) or 0),
            int(row.get("paragraph_index", 0) or 0),
            str(row.get("paragraph_id", "")),
        ),
    )
    if max_chunks is not None:
        ordered = ordered[: max(0, max_chunks)]

    chunks: List[Dict[str, Any]] = []
    errors: List[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    llm_calls = 0

    llm_limit = int(os.getenv("CASE_JUDGMENT_CHUNK_LLM_MAX", "24") or 24)
    client = llm_client or AzureLLMClient()

    for idx, paragraph in enumerate(ordered, start=1):
        page = page_by_id.get(str(paragraph.get("page_id", "")), {})
        payload = _chunk_base_payload(
            paragraph=paragraph,
            page=page,
            document_payload=document_payload,
            chunk_order_in_doc=idx,
        )

        needs_llm = payload.get("chunk_type") in {"other", "summary_paragraph"} or not payload.get("authority_refs")
        if use_llm and needs_llm and client.config.enabled and llm_calls < llm_limit:
            llm_calls += 1
            llm_payload, usage = _llm_chunk(
                client,
                document_context={
                    "case_number": document_payload.get("proceeding_no"),
                    "case_cluster_id": document_payload.get("case_cluster_id"),
                    "document_subtype": document_payload.get("document_subtype"),
                    "issues_present": document_payload.get("issues_present", []),
                },
                chunk_context={
                    "chunk_id": payload.get("chunk_id"),
                    "page_number_1": payload.get("page_number_1"),
                    "chunk_type": payload.get("chunk_type"),
                    "section_kind_case": payload.get("section_kind_case"),
                },
                chunk_text=str(paragraph.get("text", "") or "")[:1400],
            )
            total_prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            total_completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            payload = _merge_llm_chunk_payload(payload, llm_payload)

        payload.pop("confidence", None)
        payload.pop("quality_flags", None)

        chunks.append(payload)

    schemas, _ = load_bundle_mirror()
    for idx, chunk in enumerate(chunks):
        chunk_errors = validate_payload(
            schemas["full_judgment_case_chunk.schema.json"],
            chunk,
            path=f"case_chunk_extraction[{idx}]",
        )
        errors.extend(chunk_errors)

    validation_status = "passed" if not errors else "failed"
    return ChunkExtractionResult(
        chunks=chunks,
        validation_errors=errors,
        validation_status=validation_status,
        token_usage={
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        },
        llm_calls=llm_calls,
    )


def choose_chunk_model() -> Tuple[str, str]:
    return (
        os.getenv("CASE_JUDGMENT_CHUNK_MODEL", "gpt-5-mini"),
        os.getenv("CASE_JUDGMENT_CHUNK_REASONING_EFFORT", "minimal"),
    )
