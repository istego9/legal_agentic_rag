"""Deterministic routing rules for route family selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


RouteName = Literal[
    "article_lookup",
    "single_case_extraction",
    "cross_case_compare",
    "cross_law_compare",
    "history_lineage",
    "no_answer",
]

DocumentScopeGuess = Literal["single_doc", "cross_doc"]
TemporalSensitivityGuess = Literal["none", "current_version", "historical_version"]
TargetDocTypeGuess = Literal["case", "law", "regulation", "enactment_notice"]

ROUTE_DECISION_VERSION = "route_decision.v1"

_COMPARE_TOKENS = ("compare", "difference", "compared to", "versus")
_HISTORY_TOKENS = ("history", "amended", "repeal", "amendment", "supersede", "version")
_ARTICLE_TOKENS = ("article", "clause", "section", "paragraph", "schedule")
_CASE_TOKENS = ("case", "court", "judge", "appeal")
_NEGATIVE_TOKENS = ("jury", "parole", "miranda", "plea bargain")
_ENTITY_TOKENS = ("claimant", "respondent", "party", "parties", "judge", "entity", "individual")
_CASE_COMPARE_TOKENS = (
    "same judge",
    "in common",
    "common to both",
    "both cases",
    "both case",
    "appeared in both",
    "any of the same",
    "main party",
    "earlier",
    "later",
    "issued first",
    "higher monetary amount",
    "higher amount",
)
_LAW_COMPARE_TOKENS = (
    "which laws",
    "both laws",
    "common elements",
    "same year",
    "earlier in the year",
    "same day",
    "same date",
    "common commencement date",
    "titles of",
    "administer",
    "same entity",
    "respective citation",
    "define their administration",
)

_CASE_REFERENCE_PATTERN = re.compile(r"\b(?:cfi|ca|arb|tcd|enf|dec|sct)\s*\d{1,3}/\d{4}\b", re.IGNORECASE)
_LAW_NUMBER_REFERENCE_PATTERN = re.compile(r"\blaw\s+no\.?\s*\d+\s+of\s+\d{4}\b", re.IGNORECASE)
_LAW_WORD_PATTERN = re.compile(r"\blaws?\b", re.IGNORECASE)
_REGULATION_WORD_PATTERN = re.compile(r"\bregulations?\b", re.IGNORECASE)


@dataclass(frozen=True)
class RouteDecision:
    raw_route: str
    taxonomy_subroute: Optional[str]
    normalized_taxonomy_route: Optional[str]
    route_signals: Dict[str, bool]
    target_doc_types_guess: List[TargetDocTypeGuess]
    document_scope_guess: Optional[DocumentScopeGuess]
    temporal_sensitivity_guess: Optional[TemporalSensitivityGuess]
    matched_rules: List[str]
    confidence: float
    decision_version: str


def _route_signals(question_text: str) -> Dict[str, bool]:
    text = question_text.lower()
    case_reference_count = len(_CASE_REFERENCE_PATTERN.findall(text))
    law_reference_count = len(_LAW_NUMBER_REFERENCE_PATTERN.findall(text))
    law_word_count = len(_LAW_WORD_PATTERN.findall(text))
    regulation_word_count = len(_REGULATION_WORD_PATTERN.findall(text))
    has_compare_signal = any(token in text for token in _COMPARE_TOKENS)
    has_case_signal = case_reference_count > 0 or any(token in text for token in _CASE_TOKENS)
    has_law_signal = law_word_count > 0
    has_regulation_signal = regulation_word_count > 0
    has_case_compare_phrase = any(token in text for token in _CASE_COMPARE_TOKENS)
    has_law_compare_phrase = any(token in text for token in _LAW_COMPARE_TOKENS)
    has_multiple_case_refs = case_reference_count >= 2
    has_multiple_law_refs = law_reference_count >= 2 or law_word_count >= 2 or regulation_word_count >= 2
    has_case_cross_compare_signal = has_case_signal and has_multiple_case_refs and (
        has_compare_signal
        or has_case_compare_phrase
        or " and " in text
        or " or " in text
        or "between " in text
    )
    has_law_cross_compare_signal = has_law_signal and (
        has_law_compare_phrase
        or (
            has_multiple_law_refs
            and (
                has_compare_signal
                or " and " in text
                or " or " in text
                or "between " in text
            )
        )
    )
    has_strong_negative_signal = any(token in text for token in _NEGATIVE_TOKENS)

    return {
        "has_compare_signal": has_compare_signal,
        "has_history_signal": any(token in text for token in _HISTORY_TOKENS),
        "has_article_signal": any(token in text for token in _ARTICLE_TOKENS),
        "has_case_signal": has_case_signal,
        "has_negative_signal": has_strong_negative_signal,
        "has_entity_signal": any(token in text for token in _ENTITY_TOKENS),
        "has_law_signal": has_law_signal,
        "has_regulation_signal": has_regulation_signal,
        "has_enactment_notice_signal": "enactment notice" in text,
        "has_multiple_case_refs": has_multiple_case_refs,
        "has_multiple_law_refs": has_multiple_law_refs,
        "has_case_cross_compare_signal": has_case_cross_compare_signal,
        "has_law_cross_compare_signal": has_law_cross_compare_signal,
        "has_strong_negative_signal": has_strong_negative_signal,
    }


def _select_raw_route(question: Dict[str, object], signals: Dict[str, bool]) -> tuple[str, List[str], float]:
    route_hint = question.get("route_hint")
    if isinstance(route_hint, str) and route_hint:
        return route_hint, ["rule:route_hint"], 0.99

    if signals["has_case_cross_compare_signal"]:
        return "cross_case_compare", ["rule:cross_case_compare_signal"], 0.93
    if signals["has_law_cross_compare_signal"]:
        return "cross_law_compare", ["rule:cross_law_compare_signal"], 0.92
    if signals["has_strong_negative_signal"]:
        return "no_answer", ["rule:strong_negative_signal"], 0.94
    if signals["has_history_signal"]:
        return "history_lineage", ["rule:history"], 0.85
    if signals["has_article_signal"]:
        return "article_lookup", ["rule:article"], 0.85
    if signals["has_case_signal"]:
        return "single_case_extraction", ["rule:single_case"], 0.8
    return "article_lookup", ["rule:default_article_lookup"], 0.6


def _taxonomy_alignment(
    raw_route: str,
    *,
    signals: Dict[str, bool],
    answer_type: str,
) -> tuple[Optional[str], Optional[str], Optional[DocumentScopeGuess], Optional[TemporalSensitivityGuess], List[TargetDocTypeGuess], List[str]]:
    taxonomy_subroute: Optional[str] = None
    normalized_taxonomy_route: Optional[str] = None
    matched_rules: List[str] = []

    if raw_route == "cross_case_compare":
        taxonomy_subroute = "case_cross_compare"
    elif raw_route == "cross_law_compare":
        taxonomy_subroute = "cross_law_compare"
    elif raw_route == "history_lineage":
        taxonomy_subroute = "law_relation_or_history"
    elif raw_route == "no_answer":
        taxonomy_subroute = "negative_or_unanswerable"
    elif raw_route == "single_case_extraction":
        if signals["has_case_cross_compare_signal"]:
            taxonomy_subroute = "case_cross_compare"
            matched_rules.append("subroute:single_case_compare_signal")
        elif signals["has_strong_negative_signal"]:
            taxonomy_subroute = "negative_or_unanswerable"
            matched_rules.append("subroute:single_case_negative_signal")
        elif answer_type in {"name", "names"} and signals["has_entity_signal"]:
            taxonomy_subroute = "case_entity_lookup"
            matched_rules.append("subroute:single_case_entity")
        else:
            taxonomy_subroute = "case_outcome_or_value"
            matched_rules.append("subroute:single_case_outcome")
    elif raw_route == "article_lookup":
        if signals["has_law_cross_compare_signal"]:
            taxonomy_subroute = "cross_law_compare"
            matched_rules.append("subroute:law_compare_signal")
        elif signals["has_negative_signal"]:
            taxonomy_subroute = "negative_or_unanswerable"
            matched_rules.append("subroute:negative_signal")
        elif signals["has_history_signal"]:
            taxonomy_subroute = "law_relation_or_history"
            matched_rules.append("subroute:history_signal")
        elif signals["has_article_signal"]:
            taxonomy_subroute = "law_article_lookup"
            matched_rules.append("subroute:article_signal")
        else:
            taxonomy_subroute = "law_scope_or_definition"
            matched_rules.append("subroute:scope_default")

    normalized_taxonomy_route = taxonomy_subroute

    target_doc_types_guess: List[TargetDocTypeGuess] = []
    if signals["has_case_signal"]:
        target_doc_types_guess.append("case")
    if signals["has_law_signal"]:
        target_doc_types_guess.append("law")
    if signals["has_regulation_signal"]:
        target_doc_types_guess.append("regulation")
    if signals["has_enactment_notice_signal"]:
        target_doc_types_guess.append("enactment_notice")
    if not target_doc_types_guess:
        if raw_route in {"single_case_extraction", "cross_case_compare"}:
            target_doc_types_guess = ["case"]
        else:
            target_doc_types_guess = ["law"]

    document_scope_guess: Optional[DocumentScopeGuess] = None
    if raw_route in {"cross_case_compare", "cross_law_compare"}:
        document_scope_guess = "cross_doc"
    elif raw_route in {"single_case_extraction", "article_lookup", "history_lineage"}:
        document_scope_guess = "single_doc"

    temporal_sensitivity_guess: Optional[TemporalSensitivityGuess] = None
    if signals["has_history_signal"] or raw_route == "history_lineage":
        temporal_sensitivity_guess = "historical_version"
    elif raw_route in {"article_lookup", "cross_law_compare"}:
        temporal_sensitivity_guess = "current_version"
    elif raw_route in {"single_case_extraction", "cross_case_compare"}:
        temporal_sensitivity_guess = "none"

    return (
        taxonomy_subroute,
        normalized_taxonomy_route,
        document_scope_guess,
        temporal_sensitivity_guess,
        target_doc_types_guess,
        matched_rules,
    )


def choose_route_decision(question: Dict[str, object]) -> RouteDecision:
    question_text = str(question.get("question", "")).strip()
    answer_type = str(question.get("answer_type", "")).strip().lower()
    signals = _route_signals(question_text)
    raw_route, matched_rules, confidence = _select_raw_route(question, signals)
    (
        taxonomy_subroute,
        normalized_taxonomy_route,
        document_scope_guess,
        temporal_sensitivity_guess,
        target_doc_types_guess,
        taxonomy_rules,
    ) = _taxonomy_alignment(raw_route, signals=signals, answer_type=answer_type)

    return RouteDecision(
        raw_route=raw_route,
        taxonomy_subroute=taxonomy_subroute,
        normalized_taxonomy_route=normalized_taxonomy_route,
        route_signals=signals,
        target_doc_types_guess=target_doc_types_guess,
        document_scope_guess=document_scope_guess,
        temporal_sensitivity_guess=temporal_sensitivity_guess,
        matched_rules=[*matched_rules, *taxonomy_rules],
        confidence=confidence,
        decision_version=ROUTE_DECISION_VERSION,
    )


def choose_route(question: Dict[str, object]) -> str:
    return choose_route_decision(question).raw_route
