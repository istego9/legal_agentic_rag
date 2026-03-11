from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.router.benchmark_mapping import (  # noqa: E402
    UNMAPPED_TAXONOMY_ROUTE,
    map_raw_route_to_taxonomy,
    normalize_runtime_route_for_taxonomy,
    validate_benchmark_mapping,
)


def test_benchmark_route_mapping_is_valid() -> None:
    assert validate_benchmark_mapping() == []


def test_raw_mapping_only_applies_minimal_aliases() -> None:
    assert map_raw_route_to_taxonomy("cross_case_compare") == "case_cross_compare"
    assert map_raw_route_to_taxonomy("cross_law_compare") == "cross_law_compare"
    assert map_raw_route_to_taxonomy("history_lineage") == "law_relation_or_history"
    assert map_raw_route_to_taxonomy("no_answer") == "negative_or_unanswerable"
    assert map_raw_route_to_taxonomy("article_lookup") == UNMAPPED_TAXONOMY_ROUTE
    assert map_raw_route_to_taxonomy("single_case_extraction") == UNMAPPED_TAXONOMY_ROUTE


def test_normalization_does_not_reroute_without_runtime_metadata() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "article_lookup",
    )
    assert decision.raw_taxonomy_route == UNMAPPED_TAXONOMY_ROUTE
    assert decision.normalized_taxonomy_route == UNMAPPED_TAXONOMY_ROUTE
    assert decision.normalization_source == "raw_unmapped"


def test_normalization_uses_explicit_runtime_taxonomy_route_when_available() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "article_lookup",
        runtime_metadata={"normalized_taxonomy_route": "law_article_lookup"},
    )
    assert decision.normalized_taxonomy_route == "law_article_lookup"
    assert decision.normalization_source == "runtime_metadata.taxonomy_route"


def test_normalization_uses_explicit_runtime_subroute_when_available() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "single_case_extraction",
        runtime_metadata={"taxonomy_subroute": "case_cross_compare"},
    )
    assert decision.normalized_taxonomy_route == "case_cross_compare"
    assert decision.runtime_taxonomy_subroute == "case_cross_compare"
    assert decision.normalization_source == "runtime_metadata.taxonomy_subroute"


def test_normalization_does_not_infer_from_runtime_signals_or_text_fields() -> None:
    decision = normalize_runtime_route_for_taxonomy(
        "article_lookup",
        runtime_metadata={
            "question": "Which case was decided earlier: A or B?",
            "route_signals": {"has_compare_signal": True, "has_case_signal": True},
        },
    )
    assert decision.raw_taxonomy_route == UNMAPPED_TAXONOMY_ROUTE
    assert decision.normalized_taxonomy_route == UNMAPPED_TAXONOMY_ROUTE
    assert decision.normalization_source == "raw_unmapped"
