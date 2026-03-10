from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.router.benchmark_mapping import (  # noqa: E402
    normalize_runtime_route_for_taxonomy,
    validate_benchmark_mapping,
)


def test_benchmark_route_mapping_is_valid() -> None:
    assert validate_benchmark_mapping() == []


def test_single_case_runtime_route_normalizes_cross_case_subroute() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "single_case_extraction",
        question="Was the same judge involved in both case CFI 010/2024 and case DEC 001/2025?",
        answer_type="boolean",
    )
    assert decision.normalization_subroute == "case_cross_compare"
    assert decision.normalized_taxonomy_route == "case_cross_compare"


def test_article_lookup_runtime_route_normalizes_cross_law_subroute() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "article_lookup",
        question="Was the Employment Law enacted in the same year as the Intellectual Property Law?",
        answer_type="boolean",
    )
    assert decision.normalization_subroute == "cross_law_compare"
    assert decision.normalized_taxonomy_route == "cross_law_compare"


def test_no_answer_runtime_route_normalizes_negative_route() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "no_answer",
        question="What was the plea bargain in case ARB 032/2025?",
        answer_type="free_text",
    )
    assert decision.normalized_taxonomy_route == "negative_or_unanswerable"

