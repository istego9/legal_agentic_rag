"""Typed LLM-backed semantic extraction for prepared chunks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from legal_rag_api.azure_llm import AzureLLMClient, AzureOpenAIConfig


PROMPT_SET_VERSION = "chunk_semantics_prompt_set_v1"
LAW_PROMPT_VERSION = "law_chunk_semantics_v1"
CASE_PROMPT_VERSION = "case_chunk_semantics_v1"
_DIRECT_ANSWER_TYPES = {"boolean", "number", "date", "name", "names", "none"}

_SEMANTIC_RICH_LAW_PATTERN = re.compile(
    r"\b(?:shall|must|may|unless|except|provided that|void|invalid|precludes|means|liable to|penalty)\b",
    re.IGNORECASE,
)
_SEMANTIC_RICH_CASE_PATTERN = re.compile(
    r"\b(?:ordered|shall pay|must pay|amount payable|dismissed|granted|stayed|interest|costs award|within \d+ days|per annum|for these reasons|i conclude)\b",
    re.IGNORECASE,
)
_CONDITION_CUE_PATTERN = re.compile(
    r"\b(?:subject to|unless|except|provided that|if|only if|nothing in this law precludes)\b",
    re.IGNORECASE,
)
_OPERATIVE_PAYMENT_PATTERN = re.compile(
    r"\b(?:shall|must|is hereby ordered to|ordered to)\s+pay\b|\bcosts award\b|\bamount payable\b",
    re.IGNORECASE,
)
_MONEY_PATTERN = re.compile(
    r"(?:\b(?:USD|US\\$|AED|EUR|GBP)\s*([0-9][0-9,]*(?:\.\d+)?)\b|\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:USD|US\\$|AED|EUR|GBP|dirhams?)\b)",
    re.IGNORECASE,
)
_DAYS_PATTERN = re.compile(r"\bwithin\s+(\d{1,3})\s+days?\b", re.IGNORECASE)
_INTEREST_RATE_PATTERN = re.compile(
    r"(?:interest[^.]{0,120}?(\d{1,3}(?:\.\d+)?)\s*%|(\d{1,3}(?:\.\d+)?)\s*%[^.]{0,120}?interest)",
    re.IGNORECASE,
)
_PROPOSITION_RELATIONS = {
    "requires",
    "prohibits",
    "permits",
    "defines",
    "empowers",
    "governs",
    "penalizes",
    "excepts",
    "is_void",
    "ordered_to_pay",
    "dismissed_application",
    "granted_application",
    "awarded_costs",
    "accrues_interest",
}
_RELATION_ALIASES = {
    "invalidates": "is_void",
    "voids": "is_void",
    "void": "is_void",
    "unenforceable": "is_void",
    "awards_costs": "awarded_costs",
    "orders_to_pay": "ordered_to_pay",
    "obligation": "requires",
    "duty_to_file": "requires",
    "must_file": "requires",
    "must_file_within": "requires",
    "penalty_liability": "penalizes",
    "is_punishable_by": "penalizes",
    "liable_to": "penalizes",
    "comes_into_force": "governs",
    "comes_into_force_on": "governs",
    "comes_into_force_via": "governs",
    "commences_on": "governs",
    "commencement_requires": "governs",
    "forum_of_proceeding": "governs",
}
_MODALITY_ALIASES = {
    "required": "obligation",
    "must": "obligation",
    "forbidden": "prohibition",
    "allowed": "permission",
    "permitted": "permission",
    "authorised": "permission",
    "authorized": "permission",
    "administrative_power": "power",
    "invalidity": "procedure",
}


@dataclass
class ChunkSemanticsResult:
    payload: Dict[str, Any]
    prompt_version: str
    mode: str


def _load_prompt(name: str) -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "packages" / "prompts" / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def build_chunk_semantics_client() -> AzureLLMClient:
    config = AzureOpenAIConfig.from_env()
    provider_override = (os.getenv("CHUNK_SEMANTICS_PROVIDER") or "").strip().lower()
    if provider_override in {"azure", "openai"}:
        config.provider = provider_override
    deployment_override = (os.getenv("CHUNK_SEMANTICS_DEPLOYMENT") or "").strip()
    model_override = (os.getenv("CHUNK_SEMANTICS_MODEL") or "").strip()
    api_mode_override = (os.getenv("CHUNK_SEMANTICS_API_MODE") or "").strip().lower()
    token_parameter_override = (os.getenv("CHUNK_SEMANTICS_TOKEN_PARAMETER") or "").strip()
    reasoning_effort_override = (os.getenv("CHUNK_SEMANTICS_REASONING_EFFORT") or "").strip()
    timeout_override = (os.getenv("CHUNK_SEMANTICS_TIMEOUT_SECONDS") or "").strip()
    max_tokens_override = (os.getenv("CHUNK_SEMANTICS_MAX_TOKENS") or "").strip()
    verbosity_override = (os.getenv("CHUNK_SEMANTICS_VERBOSITY") or "").strip()

    if config.provider == "azure":
        config.deployment = deployment_override or (os.getenv("CORPUS_METADATA_NORMALIZER_DEPLOYMENT") or "").strip() or config.deployment
    else:
        config.model = model_override or (os.getenv("CORPUS_METADATA_NORMALIZER_MODEL") or "").strip() or config.model

    selected_model_name = deployment_override or model_override or config.deployment or config.model or ""
    normalized_model_name = selected_model_name.lower()
    looks_like_gpt5 = normalized_model_name.startswith("gpt-5") or "gpt5" in normalized_model_name
    if api_mode_override in {"chat_completions", "responses"}:
        config.api_mode = api_mode_override
    elif looks_like_gpt5:
        config.api_mode = "responses"
    if reasoning_effort_override:
        config.reasoning_effort = reasoning_effort_override
    elif looks_like_gpt5:
        config.reasoning_effort = "minimal"
    if token_parameter_override in {"max_tokens", "max_completion_tokens", "max_output_tokens"}:
        config.token_parameter = token_parameter_override
    elif looks_like_gpt5:
        config.token_parameter = "max_output_tokens" if config.api_mode == "responses" else "max_completion_tokens"
    if timeout_override:
        try:
            config.timeout_seconds = float(timeout_override)
        except ValueError:
            pass
    elif (os.getenv("CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS") or "").strip():
        try:
            config.timeout_seconds = float(os.getenv("CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS", "30"))
        except ValueError:
            pass
    if max_tokens_override:
        try:
            config.max_tokens = int(max_tokens_override)
        except ValueError:
            pass
    else:
        config.max_tokens = 1200
    if verbosity_override:
        config.verbosity = verbosity_override
    elif looks_like_gpt5 and config.api_mode == "responses":
        config.verbosity = "low"
    return AzureLLMClient(config=config)


def chunk_semantics_enabled() -> bool:
    raw = os.getenv("AGENTIC_ENRICHMENT_LLM_ENABLED", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_semantically_rich_chunk(doc_type: str, paragraph: Dict[str, Any], projection: Dict[str, Any]) -> bool:
    text = _compact(paragraph.get("text", ""), 4000)
    if not text:
        return False
    normalized_doc_type = str(doc_type or "").strip().lower()
    section_kind = str(paragraph.get("section_kind") or projection.get("section_kind") or "").strip().lower()
    if normalized_doc_type in {"law", "regulation", "enactment_notice"}:
        return bool(
            section_kind in {"definition", "operative_provision", "exception", "penalty", "procedure"}
            or paragraph.get("article_refs")
            or projection.get("article_number")
            or _SEMANTIC_RICH_LAW_PATTERN.search(text)
        )
    if normalized_doc_type == "case":
        section_kind_case = str(projection.get("section_kind_case") or "").strip().lower()
        return bool(
            section_kind in {"reasoning", "order", "disposition", "procedural_history"}
            or section_kind_case in {"reasoning", "order", "disposition", "procedural_history"}
            or paragraph.get("money_mentions")
            or _SEMANTIC_RICH_CASE_PATTERN.search(text)
        )
    return False


def _law_prompt(paragraph: Dict[str, Any], page: Dict[str, Any], document: Dict[str, Any], projection: Dict[str, Any]) -> Tuple[str, str]:
    guidance = _load_prompt(LAW_PROMPT_VERSION)
    system_prompt = (
        "You extract grounded legal propositions from one law chunk. "
        "Return strict JSON only. Do not explain your reasoning."
    )
    prompt = (
        f"Use typed chunk extraction contract `{LAW_PROMPT_VERSION}`.\n"
        "Return one JSON object with keys: "
        "{section_kind, provision_kind, semantic_dense_summary, semantic_query_terms, propositions}.\n"
        "Each proposition must use keys: "
        "{subject_type, subject_text, relation_type, object_type, object_text, modality, polarity, conditions, exceptions, citation_refs, dense_paraphrase, direct_answer}.\n"
        "The `direct_answer` object must use keys: "
        "{eligible, answer_type, boolean_value, number_value, date_value, text_value}.\n"
        "Rules:\n"
        "- Use only supplied chunk text and deterministic structural context.\n"
        "- Preserve negation carefully.\n"
        "- Distinguish invalidity, permission, prohibition, obligations, conditions, and exceptions.\n"
        "- If one chunk contains multiple norms, return multiple propositions.\n"
        "- Keep semantic_dense_summary to one short sentence.\n"
        "- Keep semantic_query_terms retrieval-oriented and short.\n"
        "- `direct_answer.answer_type` must be one of: boolean, number, date, name, names, none.\n"
        "- `direct_answer.answer_type` must never be `free_text`.\n"
        "- If no grounded proposition exists, return empty propositions array.\n\n"
        f"Document title: {_compact(document.get('title') or document.get('citation_title') or document.get('pdf_id'), 200)}\n"
        f"Source page id: {_compact(page.get('source_page_id'), 80)}\n"
        f"Heading path: {json.dumps(projection.get('heading_path', []), ensure_ascii=False)}\n"
        f"Part ref: {_compact(projection.get('part_ref'), 80)}\n"
        f"Chapter ref: {_compact(projection.get('chapter_ref'), 80)}\n"
        f"Article number: {_compact(projection.get('article_number'), 40)}\n"
        f"Article title: {_compact(projection.get('article_title'), 120)}\n"
        f"Chunk text: {_compact(paragraph.get('text'), 4000)}\n"
    )
    if guidance:
        prompt += f"\nPrompt guidance:\n{guidance}\n"
    return system_prompt, prompt


def _case_prompt(paragraph: Dict[str, Any], page: Dict[str, Any], document: Dict[str, Any], projection: Dict[str, Any]) -> Tuple[str, str]:
    guidance = _load_prompt(CASE_PROMPT_VERSION)
    system_prompt = (
        "You extract grounded legal propositions from one case chunk. "
        "Return strict JSON only. Do not explain your reasoning."
    )
    prompt = (
        f"Use typed chunk extraction contract `{CASE_PROMPT_VERSION}`.\n"
        "Return one JSON object with keys: "
        "{section_kind_case, semantic_dense_summary, semantic_query_terms, propositions}.\n"
        "Each proposition must use keys: "
        "{subject_type, subject_text, relation_type, object_type, object_text, modality, polarity, conditions, exceptions, citation_refs, dense_paraphrase, direct_answer}.\n"
        "The `direct_answer` object must use keys: "
        "{eligible, answer_type, boolean_value, number_value, date_value, text_value}.\n"
        "Rules:\n"
        "- Use only supplied chunk text and deterministic structural context.\n"
        "- Distinguish orders, dispositions, procedural history, and reasoning.\n"
        "- Preserve amounts, deadlines, and interest consequences exactly if explicit.\n"
        "- If one chunk contains multiple grounded propositions, return multiple propositions.\n"
        "- Keep semantic_dense_summary to one short sentence.\n"
        "- `direct_answer.answer_type` must be one of: boolean, number, date, name, names, none.\n"
        "- `direct_answer.answer_type` must never be `free_text`.\n"
        "- If no grounded proposition exists, return empty propositions array.\n\n"
        f"Case title: {_compact(document.get('title') or document.get('citation_title') or document.get('pdf_id'), 220)}\n"
        f"Case number: {_compact(projection.get('case_number') or document.get('case_id'), 80)}\n"
        f"Court name: {_compact(projection.get('court_name') or document.get('title'), 160)}\n"
        f"Source page id: {_compact(page.get('source_page_id'), 80)}\n"
        f"Heading path: {json.dumps(projection.get('heading_path', []), ensure_ascii=False)}\n"
        f"Section kind candidate: {_compact(projection.get('section_kind_case') or paragraph.get('section_kind'), 80)}\n"
        f"Chunk text: {_compact(paragraph.get('text'), 4000)}\n"
    )
    if guidance:
        prompt += f"\nPrompt guidance:\n{guidance}\n"
    return system_prompt, prompt


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


def _normalize_string_list(value: Any, limit: int = 16) -> List[str]:
    if not isinstance(value, list):
        return []
    seen = set()
    out: List[str] = []
    for item in value:
        token = _compact(item, 240)
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _normalize_citation_refs(value: Any) -> List[str]:
    cleaned = []
    for token in _normalize_string_list(value, limit=16):
        if any(char.isdigit() for char in token):
            cleaned.append(token)
    return cleaned


def _extract_clause_windows(text: str, pattern: re.Pattern[str], *, limit: int = 3) -> List[str]:
    out: List[str] = []
    for match in pattern.finditer(text):
        start = match.start()
        tail = text[start:]
        clause = re.split(r"(?<=[.;:])\s+", tail, maxsplit=1)[0]
        clause = _compact(clause, 220)
        if clause:
            out.append(clause)
        if len(out) >= limit:
            break
    return _normalize_string_list(out, limit=limit)


def _derived_conditions(text: str) -> List[str]:
    patterns = (
        re.compile(r"\bsubject to\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bonly if\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bif\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bprovided that\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bfailing which\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bwritten agreement\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bopportunity to\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bmediation\b[^.;:]{0,220}", re.IGNORECASE),
    )
    out: List[str] = []
    for pattern in patterns:
        out.extend(_extract_clause_windows(text, pattern, limit=2))
    return _normalize_string_list(out, limit=8)


def _derived_exceptions(text: str) -> List[str]:
    patterns = (
        re.compile(r"\bunless\b[^.;:]{0,220}", re.IGNORECASE),
        re.compile(r"\bexcept\b[^.;:]{0,220}", re.IGNORECASE),
    )
    out: List[str] = []
    for pattern in patterns:
        out.extend(_extract_clause_windows(text, pattern, limit=2))
    return _normalize_string_list(out, limit=6)


def _money_values(text: str) -> List[tuple[str, float]]:
    out: List[tuple[str, float]] = []
    seen = set()
    for match in _MONEY_PATTERN.finditer(text):
        raw_text = _compact(match.group(0), 64)
        raw_value = match.group(1) or match.group(2)
        if raw_value is None:
            continue
        try:
            parsed = float(raw_value.replace(",", ""))
        except ValueError:
            continue
        key = (raw_text.casefold(), parsed)
        if key in seen:
            continue
        seen.add(key)
        out.append((raw_text, parsed))
    return out


def _rate_values(text: str) -> List[tuple[str, float]]:
    out: List[tuple[str, float]] = []
    seen = set()
    for match in _INTEREST_RATE_PATTERN.finditer(text):
        raw_number = match.group(1) or match.group(2)
        if raw_number is None:
            continue
        value_text = f"{raw_number}% per annum" if "per annum" in match.group(0).lower() else f"{raw_number}%"
        try:
            parsed = float(raw_number)
        except ValueError:
            continue
        key = value_text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append((value_text, parsed))
    return out


def _first_deadline_value(text: str) -> tuple[str, float] | None:
    match = _DAYS_PATTERN.search(text)
    if not match:
        return None
    return (f"within {match.group(1)} days", float(match.group(1)))


def _derive_case_subject(text: str, propositions: List[Dict[str, Any]]) -> str:
    for proposition in propositions:
        subject_text = _compact(proposition.get("subject_text"), 120)
        if subject_text:
            return subject_text
    for token in ("Applicant", "Respondent", "Defendant", "Claimant", "Appellant"):
        if re.search(rf"\b{token}\b", text, re.IGNORECASE):
            return token
    return "party"


def _direct_answer_stub(*, answer_type: str, boolean_value: bool | None = None, number_value: float | None = None, text_value: str | None = None) -> Dict[str, Any]:
    return {
        "eligible": answer_type in {"boolean", "number", "date", "name", "names"},
        "answer_type": answer_type,
        "boolean_value": boolean_value,
        "number_value": number_value,
        "date_value": None,
        "text_value": text_value,
    }


def _normalize_proposition(item: Dict[str, Any]) -> Dict[str, Any]:
    relation_type = _compact(item.get("relation_type"), 80) or "governs"
    relation_type = _RELATION_ALIASES.get(relation_type.lower(), relation_type)
    if "liable" in relation_type.lower():
        relation_type = "penalizes"
    if relation_type.lower().startswith("must_"):
        relation_type = "requires"
    if relation_type not in _PROPOSITION_RELATIONS:
        relation_type = relation_type.lower().replace(" ", "_")
    modality = _compact(item.get("modality"), 40).lower() or "procedure"
    modality = _MODALITY_ALIASES.get(modality, modality)
    if modality not in {"obligation", "prohibition", "permission", "definition", "power", "procedure", "penalty", "exception"}:
        modality = "procedure"
    polarity = _compact(item.get("polarity"), 24).lower() or "affirmative"
    direct_answer = item.get("direct_answer")
    if not isinstance(direct_answer, dict):
        direct_answer = {}
    direct_answer_payload = {
        "eligible": bool(direct_answer.get("eligible")),
        "answer_type": _compact(direct_answer.get("answer_type"), 24).lower() or "none",
        "boolean_value": direct_answer.get("boolean_value") if isinstance(direct_answer.get("boolean_value"), bool) else None,
        "number_value": direct_answer.get("number_value"),
        "date_value": _compact(direct_answer.get("date_value"), 32) or None,
        "text_value": _compact(direct_answer.get("text_value"), 240) or None,
    }
    if direct_answer_payload["answer_type"] not in _DIRECT_ANSWER_TYPES:
        direct_answer_payload["answer_type"] = "none"
    if direct_answer_payload["answer_type"] == "none":
        direct_answer_payload["eligible"] = False
    if direct_answer_payload["answer_type"] != "boolean":
        direct_answer_payload["boolean_value"] = None
    if direct_answer_payload["answer_type"] != "number":
        direct_answer_payload["number_value"] = None
    if direct_answer_payload["answer_type"] != "date":
        direct_answer_payload["date_value"] = None
    if direct_answer_payload["answer_type"] not in {"name", "names"}:
        direct_answer_payload["text_value"] = None
    if relation_type == "is_void" and direct_answer_payload["answer_type"] == "boolean" and direct_answer_payload["boolean_value"] is None:
        direct_answer_payload["eligible"] = True
        direct_answer_payload["boolean_value"] = True
    return {
        "subject_type": _compact(item.get("subject_type"), 60).lower() or "actor",
        "subject_text": _compact(item.get("subject_text"), 180) or "unspecified subject",
        "relation_type": relation_type,
        "object_type": _compact(item.get("object_type"), 60).lower() or "legal_object",
        "object_text": _compact(item.get("object_text"), 240) or "unspecified object",
        "modality": modality,
        "polarity": polarity if polarity in {"affirmative", "negative"} else "affirmative",
        "conditions": _normalize_string_list(item.get("conditions"), limit=12),
        "exceptions": _normalize_string_list(item.get("exceptions"), limit=12),
        "citation_refs": _normalize_citation_refs(item.get("citation_refs")),
        "dense_paraphrase": _compact(item.get("dense_paraphrase"), 320),
        "direct_answer": direct_answer_payload,
    }


def _postprocess_legislative_payload(payload: Dict[str, Any], *, text: str) -> Dict[str, Any]:
    propositions = payload.get("propositions")
    if not isinstance(propositions, list):
        return payload
    condition_cues = bool(_CONDITION_CUE_PATTERN.search(text))
    derived_conditions = _derived_conditions(text)
    derived_exceptions = _derived_exceptions(text)
    updated: List[Dict[str, Any]] = []
    for proposition in propositions:
        if not isinstance(proposition, dict):
            continue
        item = dict(proposition)
        if condition_cues and not item.get("conditions"):
            item["conditions"] = derived_conditions
        if not item.get("exceptions"):
            item["exceptions"] = derived_exceptions
        if item.get("conditions") or item.get("exceptions"):
            item["direct_answer"] = _direct_answer_stub(answer_type="none")
        updated.append(_normalize_proposition(item))
    payload["propositions"] = updated
    return payload


def _postprocess_case_payload(payload: Dict[str, Any], *, text: str) -> Dict[str, Any]:
    propositions = payload.get("propositions")
    if not isinstance(propositions, list):
        propositions = []
    updated = [item for item in propositions if isinstance(item, dict)]
    operative_payment = bool(_OPERATIVE_PAYMENT_PATTERN.search(text))
    subject_text = _derive_case_subject(text, updated)

    has_amount = any(
        any(raw in json.dumps(item, ensure_ascii=False) for raw, _ in _money_values(text))
        or str(item.get("relation_type", "")) == "ordered_to_pay"
        for item in updated
    )
    if operative_payment and not has_amount:
        amounts = _money_values(text)
        if amounts:
            raw_text, parsed = amounts[0]
            updated.append(
                _normalize_proposition(
                    {
                        "subject_type": "actor",
                        "subject_text": subject_text,
                        "relation_type": "ordered_to_pay",
                        "object_type": "money_amount",
                        "object_text": raw_text,
                        "modality": "obligation",
                        "polarity": "affirmative",
                        "conditions": [],
                        "exceptions": [],
                        "citation_refs": [],
                        "dense_paraphrase": _compact(f"{subject_text} must pay {raw_text}.", 320),
                        "direct_answer": _direct_answer_stub(answer_type="number", number_value=parsed),
                    }
                )
            )

    has_interest = any(
        str(item.get("relation_type", "")) == "accrues_interest"
        or "interest" in json.dumps(item, ensure_ascii=False).lower()
        for item in updated
    )
    if not has_interest:
        rates = _rate_values(text)
        if rates:
            rate_text, parsed_rate = rates[0]
            conditions = _derived_conditions(text)
            updated.append(
                _normalize_proposition(
                    {
                        "subject_type": "money_amount",
                        "subject_text": "unpaid amount",
                        "relation_type": "accrues_interest",
                        "object_type": "interest_rate",
                        "object_text": rate_text,
                        "modality": "procedure",
                        "polarity": "affirmative",
                        "conditions": conditions,
                        "exceptions": [],
                        "citation_refs": [],
                        "dense_paraphrase": _compact(f"If unpaid, interest accrues at {rate_text}.", 320),
                        "direct_answer": _direct_answer_stub(answer_type="none" if conditions else "number", number_value=None if conditions else parsed_rate),
                    }
                )
            )

    payload["propositions"] = updated
    return payload


def _postprocess_chunk_semantics_payload(
    payload: Dict[str, Any],
    *,
    doc_type: str,
    paragraph: Dict[str, Any],
    projection: Dict[str, Any],
) -> Dict[str, Any]:
    text = _compact(paragraph.get("text", ""), 4000)
    normalized_doc_type = str(doc_type or "").strip().lower()
    if normalized_doc_type in {"law", "regulation", "enactment_notice"}:
        return _postprocess_legislative_payload(payload, text=text)
    if normalized_doc_type == "case":
        section_kind_case = str(payload.get("section_kind_case") or projection.get("section_kind_case") or "").strip().lower()
        if section_kind_case in {"order", "disposition"} or _OPERATIVE_PAYMENT_PATTERN.search(text) or "interest" in text.lower():
            return _postprocess_case_payload(payload, text=text)
    return payload


def normalize_chunk_semantics_payload(raw: Dict[str, Any], *, doc_type: str) -> Dict[str, Any]:
    propositions_raw = raw.get("propositions")
    propositions = [
        _normalize_proposition(item)
        for item in propositions_raw
        if isinstance(item, dict)
    ] if isinstance(propositions_raw, list) else []
    payload: Dict[str, Any] = {
        "semantic_dense_summary": _compact(raw.get("semantic_dense_summary"), 320),
        "semantic_query_terms": _normalize_string_list(raw.get("semantic_query_terms"), limit=16),
        "propositions": propositions,
    }
    if doc_type == "case":
        payload["section_kind_case"] = _compact(raw.get("section_kind_case"), 40).lower() or ""
    else:
        payload["section_kind"] = _compact(raw.get("section_kind"), 40).lower() or ""
        payload["provision_kind"] = _compact(raw.get("provision_kind"), 40).lower() or ""
    return payload


async def _run_prompt(client: AzureLLMClient, *, system_prompt: str, user_prompt: str, prompt_version: str, paragraph_id: str) -> Dict[str, Any]:
    completion, _ = await client.complete_chat(
        user_prompt,
        system_prompt=system_prompt,
        user_context={"task": "chunk_semantics", "prompt_version": prompt_version, "paragraph_id": paragraph_id},
        max_tokens=1200,
    )
    return _parse_json_object(completion)


def extract_chunk_semantics(
    *,
    client: AzureLLMClient,
    paragraph: Dict[str, Any],
    page: Dict[str, Any],
    document: Dict[str, Any],
    projection: Dict[str, Any],
) -> ChunkSemanticsResult:
    doc_type = str(document.get("doc_type") or projection.get("doc_type") or "").strip().lower()
    if not client.config.enabled or not chunk_semantics_enabled():
        return ChunkSemanticsResult(payload={}, prompt_version="disabled", mode="rules_only")
    if not _is_semantically_rich_chunk(doc_type, paragraph, projection):
        return ChunkSemanticsResult(payload={}, prompt_version="skipped_non_semantic", mode="skipped")
    if doc_type == "case":
        prompt_version = CASE_PROMPT_VERSION
        system_prompt, user_prompt = _case_prompt(paragraph, page, document, projection)
    else:
        prompt_version = LAW_PROMPT_VERSION
        system_prompt, user_prompt = _law_prompt(paragraph, page, document, projection)
    raw = asyncio.run(
        _run_prompt(
            client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_version=prompt_version,
            paragraph_id=str(paragraph.get("paragraph_id", "")),
        )
    )
    return ChunkSemanticsResult(
        payload=_postprocess_chunk_semantics_payload(
            normalize_chunk_semantics_payload(raw, doc_type=doc_type),
            doc_type=doc_type,
            paragraph=paragraph,
            projection=projection,
        ),
        prompt_version=prompt_version,
        mode="llm_merge" if raw else "rules_only",
    )
