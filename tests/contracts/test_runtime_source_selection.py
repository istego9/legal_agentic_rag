from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime.router import resolve_retrieval_profile  # noqa: E402
from services.runtime.solvers import choose_used_sources, choose_used_sources_with_trace  # noqa: E402


def _candidate_refs(count: int) -> list[dict[str, object]]:
    return [
        {
            "source_page_id": f"sample_{idx}",
            "score": 1.0 - (idx * 0.01),
        }
        for idx in range(count)
    ]


def test_existing_route_profiles_remain_unchanged() -> None:
    refs = _candidate_refs(10)
    profile = resolve_retrieval_profile("history_lineage", max_candidate_pages=8)

    assert profile.profile_id == "history_lineage_graph_v1"
    assert profile.used_page_limit == 5
    assert len(choose_used_sources(refs, "history_lineage", used_page_limit=profile.used_page_limit)) == 5

    case_profile = resolve_retrieval_profile("single_case_extraction", max_candidate_pages=8, answer_type="number")
    assert case_profile.profile_id == "single_case_extraction_compact_v2"
    assert len(choose_used_sources(refs, "single_case_extraction", used_page_limit=case_profile.used_page_limit)) == 2


def test_article_lookup_profile_uses_explicit_used_source_limit() -> None:
    refs = _candidate_refs(10)
    profile = resolve_retrieval_profile("article_lookup", max_candidate_pages=8, answer_type="number")

    assert profile.profile_id == "article_lookup_recall_v2"
    assert profile.used_page_limit == 2
    assert len(choose_used_sources(refs, "article_lookup", used_page_limit=profile.used_page_limit)) == 2


def test_cross_case_compare_profile_is_route_specific() -> None:
    refs = _candidate_refs(10)
    profile = resolve_retrieval_profile("cross_case_compare", max_candidate_pages=8, answer_type="boolean")

    assert profile.profile_id == "cross_case_compare_pairwise_v1"
    assert profile.candidate_page_limit >= 8
    assert profile.used_page_limit == 3
    assert profile.structural_lookup_enabled is True
    assert len(choose_used_sources(refs, "cross_case_compare", used_page_limit=profile.used_page_limit)) == 3


def test_cross_law_compare_profile_is_route_specific() -> None:
    refs = _candidate_refs(12)
    profile = resolve_retrieval_profile("cross_law_compare", max_candidate_pages=8, answer_type="free_text")

    assert profile.profile_id == "cross_law_compare_matrix_v1"
    assert profile.candidate_page_limit >= 8
    assert profile.used_page_limit == 5
    assert profile.structural_lookup_enabled is True
    assert profile.lineage_expansion_enabled is True
    assert len(choose_used_sources(refs, "cross_law_compare", used_page_limit=profile.used_page_limit)) == 5


def test_no_answer_profile_uses_fast_path_budget() -> None:
    profile = resolve_retrieval_profile("no_answer", max_candidate_pages=8, answer_type="free_text")
    assert profile.profile_id == "no_answer_fast_path_v1"
    assert profile.candidate_page_limit == 0
    assert profile.used_page_limit == 0
    assert profile.structural_lookup_enabled is False
    assert profile.lineage_expansion_enabled is False


def test_evidence_selection_trace_explicitly_tracks_retrieved_and_used() -> None:
    refs = _candidate_refs(5)
    used_refs, trace = choose_used_sources_with_trace(
        refs,
        "article_lookup",
        question_text="What is article 1?",
        answer_type="free_text",
        used_page_limit=2,
    )

    assert [row["source_page_id"] for row in used_refs] == ["sample_0", "sample_1"]
    assert trace["trace_version"] == "evidence_selection_trace_v1"
    assert trace["selection_rule"] == "profile_used_page_limit"
    assert trace["answer_type"] == "free_text"
    assert trace["retrieved_candidate_count"] == 5
    assert trace["used_candidate_count"] == 2
    assert trace["retrieved_source_page_ids"] == [
        "sample_0",
        "sample_1",
        "sample_2",
        "sample_3",
        "sample_4",
    ]
    assert trace["used_source_page_ids"] == ["sample_0", "sample_1"]
    assert [row["decision"] for row in trace["decisions"]] == [
        "selected",
        "selected",
        "dropped_over_limit",
        "dropped_over_limit",
        "dropped_over_limit",
    ]
