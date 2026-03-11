"""Runtime route resolver and retrieval profile planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from packages.router.heuristics import RouteDecision, choose_route_decision


@dataclass(frozen=True)
class RetrievalProfilePlan:
    profile_id: str
    candidate_page_limit: int
    used_page_limit: int
    ttft_budget_ms: int
    structural_lookup_enabled: bool
    lineage_expansion_enabled: bool
    budget_policy_version: str


@dataclass(frozen=True)
class _RetrievalProfileTemplate:
    profile_id: str
    candidate_multiplier: float
    candidate_limit_cap: int
    used_page_limit: int
    ttft_budget_ms: int
    structural_lookup_enabled: bool = False
    lineage_expansion_enabled: bool = False
    budget_policy_version: str = "evidence_budget_v1"


_DEFAULT_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="default_compare_v1",
    candidate_multiplier=1.0,
    candidate_limit_cap=100,
    used_page_limit=2,
    ttft_budget_ms=3000,
)

_ARTICLE_LOOKUP_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="article_lookup_recall_v2",
    candidate_multiplier=2.0,
    candidate_limit_cap=16,
    used_page_limit=3,
    ttft_budget_ms=1500,
    structural_lookup_enabled=True,
    budget_policy_version="evidence_budget_v2",
)

_SINGLE_CASE_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="single_case_extraction_compact_v2",
    candidate_multiplier=1.5,
    candidate_limit_cap=12,
    used_page_limit=2,
    ttft_budget_ms=1800,
    budget_policy_version="evidence_budget_v2",
)

_HISTORY_LINEAGE_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="history_lineage_graph_v1",
    candidate_multiplier=2.0,
    candidate_limit_cap=20,
    used_page_limit=4,
    ttft_budget_ms=2200,
    lineage_expansion_enabled=True,
    budget_policy_version="evidence_budget_v2",
)

_CROSS_CASE_COMPARE_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="cross_case_compare_pairwise_v1",
    candidate_multiplier=2.0,
    candidate_limit_cap=18,
    used_page_limit=4,
    ttft_budget_ms=2100,
    structural_lookup_enabled=True,
    budget_policy_version="evidence_budget_v2",
)

_CROSS_LAW_COMPARE_RETRIEVAL_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="cross_law_compare_matrix_v1",
    candidate_multiplier=2.5,
    candidate_limit_cap=24,
    used_page_limit=5,
    ttft_budget_ms=2300,
    structural_lookup_enabled=True,
    lineage_expansion_enabled=True,
    budget_policy_version="evidence_budget_v2",
)

_NO_ANSWER_FAST_PATH_TEMPLATE = _RetrievalProfileTemplate(
    profile_id="no_answer_fast_path_v1",
    candidate_multiplier=0.0,
    candidate_limit_cap=0,
    used_page_limit=0,
    ttft_budget_ms=400,
    budget_policy_version="evidence_budget_v2",
)


def _normalized_max_pages(raw_limit: int) -> int:
    if raw_limit < 1:
        return 1
    if raw_limit > 100:
        return 100
    return raw_limit


def resolve_route(question: Dict[str, object]) -> str:
    return resolve_route_decision(question).raw_route


def resolve_route_decision(question: Dict[str, object]) -> RouteDecision:
    return choose_route_decision(question)


def _used_page_budget(template: _RetrievalProfileTemplate, answer_type: str) -> int:
    normalized_answer_type = str(answer_type or "free_text").strip().lower() or "free_text"
    if template.profile_id == "article_lookup_recall_v2":
        return 2 if normalized_answer_type in {"boolean", "number", "date", "name", "names"} else 3
    if template.profile_id == "single_case_extraction_compact_v2":
        return 2 if normalized_answer_type in {"number", "date", "name", "names"} else 3
    if template.profile_id == "cross_case_compare_pairwise_v1":
        return 3 if normalized_answer_type in {"boolean", "number", "date", "name", "names"} else 4
    if template.profile_id == "cross_law_compare_matrix_v1":
        return 4 if normalized_answer_type in {"boolean", "number", "date", "name", "names"} else 5
    if template.profile_id == "history_lineage_graph_v1":
        return 4 if normalized_answer_type in {"boolean", "number", "date", "name", "names"} else 5
    if template.profile_id == "no_answer_fast_path_v1":
        return 0
    return template.used_page_limit


def resolve_retrieval_profile(
    route_name: str,
    max_candidate_pages: int,
    *,
    answer_type: str = "free_text",
) -> RetrievalProfilePlan:
    if route_name == "article_lookup":
        template = _ARTICLE_LOOKUP_RETRIEVAL_TEMPLATE
    elif route_name == "single_case_extraction":
        template = _SINGLE_CASE_RETRIEVAL_TEMPLATE
    elif route_name == "history_lineage":
        template = _HISTORY_LINEAGE_RETRIEVAL_TEMPLATE
    elif route_name == "cross_case_compare":
        template = _CROSS_CASE_COMPARE_RETRIEVAL_TEMPLATE
    elif route_name == "cross_law_compare":
        template = _CROSS_LAW_COMPARE_RETRIEVAL_TEMPLATE
    elif route_name == "no_answer":
        template = _NO_ANSWER_FAST_PATH_TEMPLATE
    else:
        template = _DEFAULT_RETRIEVAL_TEMPLATE
    base_limit = _normalized_max_pages(max_candidate_pages)
    expanded_limit = int(round(float(base_limit) * float(template.candidate_multiplier)))
    if expanded_limit < base_limit:
        expanded_limit = base_limit
    candidate_page_limit = min(template.candidate_limit_cap, expanded_limit)
    used_page_limit = min(_used_page_budget(template, answer_type), candidate_page_limit)
    return RetrievalProfilePlan(
        profile_id=template.profile_id,
        candidate_page_limit=candidate_page_limit,
        used_page_limit=used_page_limit,
        ttft_budget_ms=template.ttft_budget_ms,
        structural_lookup_enabled=template.structural_lookup_enabled,
        lineage_expansion_enabled=template.lineage_expansion_enabled,
        budget_policy_version=template.budget_policy_version,
    )
