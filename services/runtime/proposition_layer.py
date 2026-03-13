"""Internal proposition-aware retrieval helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.()/:-]{1,}")
_CAN_MAY_PATTERN = re.compile(r"\b(can|may|permitted|allowed|entitled)\b", re.IGNORECASE)
_VOID_PATTERN = re.compile(r"\b(void|invalid|unenforceable)\b", re.IGNORECASE)
_OBLIGATION_PATTERN = re.compile(r"\b(must|required|shall)\b", re.IGNORECASE)
_DAYS_PATTERN = re.compile(r"\bwithin\s+(\d{1,3})\s+days?\b", re.IGNORECASE)
_PERCENT_PATTERN = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")
_MONEY_PATTERN = re.compile(
    r"(?:\b(?:USD|US\\$|AED|EUR|GBP)\s*([0-9][0-9,]*(?:\.\d+)?)\b|\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:USD|US\\$|AED|EUR|GBP|dirhams?)\b)",
    re.IGNORECASE,
)
_INTEREST_PERCENT_PATTERN = re.compile(
    r"(?:interest[^.]{0,120}?(\d{1,3}(?:\.\d+)?)\s*%|(\d{1,3}(?:\.\d+)?)\s*%[^.]{0,120}?interest)",
    re.IGNORECASE,
)
_QUESTION_CONDITIONAL_PATTERN = re.compile(r"\b(if|unless|when|provided that|subject to|failing which)\b", re.IGNORECASE)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(value: Any) -> List[str]:
    return [token.casefold() for token in _TOKEN_PATTERN.findall(_compact(value))]


def _query_signal_tokens(question_text: str) -> List[str]:
    stop = {"the", "a", "an", "of", "to", "under", "this", "that", "is", "are", "by", "with", "their", "any"}
    return [token for token in _tokenize(question_text) if token not in stop]


def _semantic_assertions(projection: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = projection.get("semantic_assertions")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _money_match_value(match: re.Match[str]) -> float | None:
    raw_value = match.group(1) or match.group(2)
    if raw_value is None:
        return None
    try:
        return float(raw_value.replace(",", ""))
    except ValueError:
        return None


def _assertion_evidence(assertion: Dict[str, Any]) -> Dict[str, Any]:
    evidence = assertion.get("evidence")
    if isinstance(evidence, dict):
        return evidence
    return {}


def _candidate_evidence(candidate: Dict[str, Any]) -> Dict[str, Any]:
    paragraph = candidate.get("paragraph") if isinstance(candidate.get("paragraph"), dict) else {}
    page = candidate.get("page") if isinstance(candidate.get("page"), dict) else {}
    source_page_id = str(page.get("source_page_id", "")).strip()
    page_num = page.get("page_num")
    return {
        "source_page_ids": [source_page_id] if source_page_id else [],
        "page_numbers_0": [int(page_num)] if page_num is not None else [],
        "page_numbers_1": [int(page_num) + 1] if page_num is not None else [],
        "paragraph_id": paragraph.get("paragraph_id"),
        "chunk_id": paragraph.get("paragraph_id"),
        "document_id": paragraph.get("document_id"),
    }


def _has_assertion_provenance(assertion: Dict[str, Any]) -> bool:
    evidence = _assertion_evidence(assertion)
    source_page_ids = evidence.get("source_page_ids")
    return isinstance(source_page_ids, list) and any(str(item).strip() for item in source_page_ids)


def _candidate_text(candidate: Dict[str, Any]) -> str:
    paragraph = candidate.get("paragraph") if isinstance(candidate.get("paragraph"), dict) else {}
    projection = candidate.get("chunk_projection") if isinstance(candidate.get("chunk_projection"), dict) else {}
    return _compact(
        " ".join(
            [
                str(paragraph.get("text", "") or ""),
                str(projection.get("text_clean", "") or ""),
                str(projection.get("retrieval_text", "") or ""),
            ]
        )
    )


def _extract_number_from_candidates(question_text: str, candidate_pool: List[Dict[str, Any]]) -> tuple[float | None, str]:
    lowered = question_text.lower()
    values: List[float] = []
    if "interest" in lowered or "rate" in lowered:
        for candidate in candidate_pool:
            text = _candidate_text(candidate)
            matched = False
            for match in _INTEREST_PERCENT_PATTERN.finditer(text):
                value = match.group(1) or match.group(2)
                if value is None:
                    continue
                values.append(float(value))
                matched = True
            if matched:
                continue
            if "interest" in text.lower():
                for match in _PERCENT_PATTERN.finditer(text):
                    values.append(float(match.group(1)))
        unique = sorted({value for value in values})
        return (unique[0], "deterministic_percent_pattern") if len(unique) == 1 else (None, "number_abstain_conflict")
    if "days" in lowered:
        for candidate in candidate_pool:
            for match in _DAYS_PATTERN.finditer(_candidate_text(candidate)):
                values.append(float(match.group(1)))
        unique = sorted({value for value in values})
        return (unique[0], "deterministic_days_pattern") if len(unique) == 1 else (None, "number_abstain_conflict")
    if any(token in lowered for token in ("sum", "amount", "costs award", "total")):
        for candidate in candidate_pool:
            text = _candidate_text(candidate)
            scoped_values: List[float] = []
            projection = candidate.get("chunk_projection") if isinstance(candidate.get("chunk_projection"), dict) else {}
            section_kind_case = str(projection.get("section_kind_case", "")).strip().lower()
            operative_chunk = section_kind_case in {"order", "disposition"}
            if operative_chunk:
                for raw in projection.get("money_values", []) if isinstance(projection.get("money_values"), list) else []:
                    raw_text = _compact(raw)
                    match = _MONEY_PATTERN.search(raw_text)
                    if match:
                        parsed = _money_match_value(match)
                        if parsed is not None:
                            scoped_values.append(parsed)
            for sentence in re.split(r"(?<=[.;])\s+", text):
                sentence_lower = sentence.lower()
                if "costs award" not in sentence_lower and "shall pay" not in sentence_lower and "pay" not in sentence_lower:
                    continue
                for match in _MONEY_PATTERN.finditer(sentence):
                    parsed = _money_match_value(match)
                    if parsed is not None:
                        scoped_values.append(parsed)
            if scoped_values:
                values.extend(scoped_values)
            else:
                continue
        unique = sorted({value for value in values})
        return (unique[0], "deterministic_money_pattern") if len(unique) == 1 else (None, "number_abstain_conflict")
    return None, "number_abstain_missing"


def _extract_name_from_candidates(question_text: str, candidate_pool: List[Dict[str, Any]]) -> tuple[str | None, str]:
    lowered = question_text.lower()
    if "court" not in lowered:
        return None, "name_abstain_missing"
    names = []
    for candidate in candidate_pool:
        projection = candidate.get("chunk_projection") if isinstance(candidate.get("chunk_projection"), dict) else {}
        name = _compact(projection.get("court_name"))
        if name:
            if " - " in name:
                name = _compact(name.split(" - ")[-1])
            names.append(name)
    unique = sorted({value for value in names})
    return (unique[0], "deterministic_court_name") if len(unique) == 1 else (None, "name_abstain_conflict")


def proposition_match_features(
    *,
    question_text: str,
    question_structure: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    projection = candidate.get("chunk_projection") if isinstance(candidate.get("chunk_projection"), dict) else {}
    assertions = _semantic_assertions(projection)
    if not assertions:
        return {
            "semantic_boost": 0.0,
            "semantic_terms_hit_count": 0,
            "top_proposition": None,
            "top_proposition_score": 0.0,
            "second_proposition_score": 0.0,
        }

    query_tokens = _query_signal_tokens(question_text)
    article_refs = set(question_structure.get("article_refs", []))
    case_numbers = set(question_structure.get("case_numbers", []))
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for assertion in assertions:
        semantic_bag = _tokenize(assertion.get("subject_text")) + _tokenize(assertion.get("relation_type")) + _tokenize(assertion.get("object_text"))
        semantic_bag += _tokenize(assertion.get("dense_paraphrase"))
        semantic_bag += _tokenize(" ".join(assertion.get("citation_refs", [])))
        semantic_bag += _tokenize(" ".join(projection.get("semantic_query_terms", []))) if isinstance(projection.get("semantic_query_terms"), list) else []
        overlap = len({token for token in query_tokens if token in semantic_bag})
        score = float(overlap) / float(max(1, len(set(query_tokens))))
        citations = {str(item).lower() for item in assertion.get("citation_refs", []) if str(item).strip()}
        if article_refs and any(ref.lower() in citations for ref in article_refs):
            score += 0.2
        if case_numbers and any(ref.upper() in {item.upper() for item in assertion.get("citation_refs", [])} for ref in case_numbers):
            score += 0.2
        if assertion.get("direct_answer", {}).get("eligible"):
            score += 0.05
        scored.append((score, assertion))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_assertion = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    return {
        "semantic_boost": min(0.45, top_score * 0.45),
        "semantic_terms_hit_count": int(round(top_score * len(set(query_tokens)))) if query_tokens else 0,
        "top_proposition": top_assertion,
        "top_proposition_score": round(top_score, 4),
        "second_proposition_score": round(second_score, 4),
    }


def _boolean_inference(question_text: str, assertion: Dict[str, Any]) -> bool | None:
    relation = str(assertion.get("relation_type", "")).lower()
    modality = str(assertion.get("modality", "")).lower()
    lowered = question_text.lower()
    object_blob = f"{assertion.get('object_text', '')} {assertion.get('dense_paraphrase', '')}".lower()
    if _VOID_PATTERN.search(lowered):
        if relation == "is_void":
            return True
        if " void " in f" {object_blob} " or "invalid" in object_blob:
            return True
        return None
    if _CAN_MAY_PATTERN.search(lowered):
        if modality == "permission":
            return True
        if modality == "prohibition" or relation == "is_void":
            return False
    if _OBLIGATION_PATTERN.search(lowered) and modality == "obligation":
        return True
    return None


def try_direct_answer(
    *,
    question_text: str,
    answer_type: str,
    route_name: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    if answer_type not in {"boolean", "number", "date", "name", "names"}:
        return None
    if route_name not in {"article_lookup", "single_case_extraction"}:
        return None
    question_has_conditional_cue = bool(_QUESTION_CONDITIONAL_PATTERN.search(question_text))
    if question_has_conditional_cue and answer_type in {"boolean", "number", "date", "name", "names"}:
        return None

    query_tokens = _query_signal_tokens(question_text)
    candidate_pool = list(candidates[:6])
    exact_pool = [candidate for candidate in candidate_pool if candidate.get("exact_identifier_hit")]
    if exact_pool:
        candidate_pool = exact_pool
    if candidate_pool:
        top_doc_id = str((((candidate_pool[0].get("paragraph") or {}) if isinstance(candidate_pool[0].get("paragraph"), dict) else {})).get("document_id", ""))
        if top_doc_id:
            candidate_pool = [
                candidate
                for candidate in candidate_pool
                if str((((candidate.get("paragraph") or {}) if isinstance(candidate.get("paragraph"), dict) else {})).get("document_id", "")) == top_doc_id
            ]

    scored_props: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for candidate in candidate_pool:
        projection = candidate.get("chunk_projection") if isinstance(candidate.get("chunk_projection"), dict) else {}
        for assertion in _semantic_assertions(projection):
            bag = _tokenize(assertion.get("subject_text")) + _tokenize(assertion.get("relation_type")) + _tokenize(assertion.get("object_text"))
            bag += _tokenize(assertion.get("dense_paraphrase"))
            overlap = len({token for token in query_tokens if token in bag})
            if overlap <= 0:
                continue
            scored_props.append((float(overlap) / float(max(1, len(set(query_tokens)))), assertion, candidate))
    if not scored_props:
        if answer_type == "number":
            number_value, number_path = _extract_number_from_candidates(question_text, candidate_pool)
            if number_value is not None:
                evidence = _candidate_evidence(candidate_pool[0]) if candidate_pool else {}
                return {
                    "answer": int(number_value) if number_value.is_integer() else number_value,
                    "confidence": 0.76,
                    "trace": {
                        "solver_version": "proposition_direct_answer_v1",
                        "route_name": route_name,
                        "answer_type": answer_type,
                        "path": number_path,
                        "top_proposition_score": 0.0,
                        "second_proposition_score": 0.0,
                        "top_proposition": {"evidence": evidence},
                        "matched_candidate_indices": [0] if candidate_pool else [],
                        "candidate_count": len(candidates),
                        "direct_answer_used": True,
                        "source_paragraph_id": str((((candidate_pool[0].get("paragraph") or {}) if candidate_pool and isinstance(candidate_pool[0].get("paragraph"), dict) else {})).get("paragraph_id", "")),
                    },
                }
        if answer_type == "name":
            name_value, name_path = _extract_name_from_candidates(question_text, candidate_pool)
            if name_value:
                evidence = _candidate_evidence(candidate_pool[0]) if candidate_pool else {}
                return {
                    "answer": name_value,
                    "confidence": 0.76,
                    "trace": {
                        "solver_version": "proposition_direct_answer_v1",
                        "route_name": route_name,
                        "answer_type": answer_type,
                        "path": name_path,
                        "top_proposition_score": 0.0,
                        "second_proposition_score": 0.0,
                        "top_proposition": {"evidence": evidence},
                        "matched_candidate_indices": [0] if candidate_pool else [],
                        "candidate_count": len(candidates),
                        "direct_answer_used": True,
                        "source_paragraph_id": str((((candidate_pool[0].get("paragraph") or {}) if candidate_pool and isinstance(candidate_pool[0].get("paragraph"), dict) else {})).get("paragraph_id", "")),
                    },
                }
        return None
    scored_props.sort(key=lambda item: item[0], reverse=True)
    top_score, top_assertion, top_candidate = scored_props[0]
    second_score = scored_props[1][0] if len(scored_props) > 1 else 0.0
    if top_score < 0.45 or (second_score and top_score - second_score < 0.12):
        if answer_type == "number":
            number_value, number_path = _extract_number_from_candidates(question_text, candidate_pool)
            if number_value is not None:
                evidence = _candidate_evidence(candidate_pool[0]) if candidate_pool else {}
                return {
                    "answer": int(number_value) if number_value.is_integer() else number_value,
                    "confidence": 0.76,
                    "trace": {
                        "solver_version": "proposition_direct_answer_v1",
                        "route_name": route_name,
                        "answer_type": answer_type,
                        "path": number_path,
                        "top_proposition_score": round(top_score, 4),
                        "second_proposition_score": round(second_score, 4),
                        "top_proposition": {"evidence": evidence},
                        "matched_candidate_indices": [0] if candidate_pool else [],
                        "candidate_count": len(candidates),
                        "direct_answer_used": True,
                        "source_paragraph_id": str((((candidate_pool[0].get("paragraph") or {}) if candidate_pool and isinstance(candidate_pool[0].get("paragraph"), dict) else {})).get("paragraph_id", "")),
                    },
                }
        if answer_type == "name":
            name_value, name_path = _extract_name_from_candidates(question_text, candidate_pool)
            if name_value:
                evidence = _candidate_evidence(candidate_pool[0]) if candidate_pool else {}
                return {
                    "answer": name_value,
                    "confidence": 0.76,
                    "trace": {
                        "solver_version": "proposition_direct_answer_v1",
                        "route_name": route_name,
                        "answer_type": answer_type,
                        "path": name_path,
                        "top_proposition_score": round(top_score, 4),
                        "second_proposition_score": round(second_score, 4),
                        "top_proposition": {"evidence": evidence},
                        "matched_candidate_indices": [0] if candidate_pool else [],
                        "candidate_count": len(candidates),
                        "direct_answer_used": True,
                        "source_paragraph_id": str((((candidate_pool[0].get("paragraph") or {}) if candidate_pool and isinstance(candidate_pool[0].get("paragraph"), dict) else {})).get("paragraph_id", "")),
                    },
                }
        return None
    if not _has_assertion_provenance(top_assertion):
        return None
    evidence = _assertion_evidence(top_assertion)
    source_page_ids = evidence.get("source_page_ids") if isinstance(evidence, dict) else []
    normalized_source_page_ids = {
        str(item).strip()
        for item in source_page_ids
        if str(item).strip()
    }
    if len(normalized_source_page_ids) != 1:
        return None
    has_condition_or_exception = bool(top_assertion.get("conditions") or top_assertion.get("exceptions"))
    if has_condition_or_exception and answer_type == "boolean":
        return None

    direct = top_assertion.get("direct_answer") if isinstance(top_assertion.get("direct_answer"), dict) else {}
    answer = None
    path = "no_match"
    if not has_condition_or_exception and direct.get("eligible") and str(direct.get("answer_type", "")).strip().lower() == answer_type:
        if answer_type == "boolean" and isinstance(direct.get("boolean_value"), bool):
            inferred = _boolean_inference(question_text, top_assertion)
            answer = inferred if inferred is not None else direct.get("boolean_value")
        elif answer_type == "number" and direct.get("number_value") is not None:
            answer = direct.get("number_value")
        elif answer_type == "date" and str(direct.get("date_value", "")).strip():
            answer = str(direct.get("date_value")).strip()
        path = "direct_answer_hint"

    if answer is None and answer_type == "boolean":
        inferred = _boolean_inference(question_text, top_assertion)
        if inferred is not None:
            answer = inferred
            if inferred is True and str(top_assertion.get("relation_type", "")).lower() == "is_void":
                path = "relation_void_boolean"
            elif inferred is True and str(top_assertion.get("modality", "")).lower() == "obligation":
                path = "obligation_boolean"
            elif inferred is True:
                path = "permission_boolean"
            else:
                path = "prohibition_boolean"

    if answer is None and answer_type == "number":
        number_value, number_path = _extract_number_from_candidates(question_text, candidate_pool)
        if number_value is not None:
            answer = int(number_value) if number_value.is_integer() else number_value
            path = number_path

    if answer is None and answer_type == "name":
        name_value, name_path = _extract_name_from_candidates(question_text, candidate_pool)
        if name_value:
            answer = name_value
            path = name_path

    if answer is None:
        return None

    if answer_type == "boolean":
        for score, assertion, _candidate in scored_props[1:]:
            if score < 0.35:
                continue
            competing = _boolean_inference(question_text, assertion)
            if competing is not None and competing != answer:
                return None

    return {
        "answer": answer,
        "confidence": round(min(0.96, 0.72 + top_score * 0.2), 4),
        "trace": {
            "solver_version": "proposition_direct_answer_v1",
            "route_name": route_name,
            "answer_type": answer_type,
            "path": path,
            "top_proposition_score": round(top_score, 4),
            "second_proposition_score": round(second_score, 4),
            "top_proposition": {
                "subject_text": top_assertion.get("subject_text"),
                "relation_type": top_assertion.get("relation_type"),
                "object_text": top_assertion.get("object_text"),
                "modality": top_assertion.get("modality"),
                "citation_refs": top_assertion.get("citation_refs", []),
                "evidence": _assertion_evidence(top_assertion),
            },
            "matched_candidate_indices": [0],
            "candidate_count": len(candidates),
            "direct_answer_used": True,
            "source_paragraph_id": str(((top_candidate.get("paragraph") or {}) if isinstance(top_candidate.get("paragraph"), dict) else {}).get("paragraph_id", "")),
        },
    }
