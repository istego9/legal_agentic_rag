from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_chunk_processing_full_corpus_eval as full_eval_module  # noqa: E402


def _snapshot() -> dict:
    return {
        "documents": [
            {"document_id": "doc-law", "doc_type": "law"},
            {"document_id": "doc-case", "doc_type": "case"},
        ],
        "pages": [],
        "paragraphs": [
            {
                "paragraph_id": "para-law-1",
                "document_id": "doc-law",
                "section_kind": "operative_provision",
                "chunk_type": "paragraph",
                "text": "Nothing in this Law precludes an employee from waiving rights by written agreement, subject to Article 66(13).",
            },
            {
                "paragraph_id": "para-law-2",
                "document_id": "doc-law",
                "section_kind": "definition",
                "chunk_type": "paragraph",
                "text": "Employee means a natural person employed under a contract of employment.",
            },
            {
                "paragraph_id": "para-case-1",
                "document_id": "doc-case",
                "section_kind": "order",
                "chunk_type": "list_item",
                "text": "The Applicant shall pay 10,000 AED within 14 days, failing which interest shall accrue at 9% per annum.",
            },
            {
                "paragraph_id": "para-case-2",
                "document_id": "doc-case",
                "section_kind": "parties",
                "chunk_type": "heading",
                "text": "BETWEEN Alpha Claimant and Beta Defendant",
            },
        ],
        "chunk_search_documents": [
            {"chunk_id": "para-law-1", "document_id": "doc-law", "article_number": "11"},
            {"chunk_id": "para-law-2", "document_id": "doc-law"},
            {"chunk_id": "para-case-1", "document_id": "doc-case", "section_kind_case": "order"},
            {"chunk_id": "para-case-2", "document_id": "doc-case", "section_kind_case": "parties"},
        ],
        "chunk_assertions": [],
    }


def test_semantic_target_report_includes_reason_histogram_and_distributions() -> None:
    report, target_ids = full_eval_module._semantic_target_report(_snapshot())

    assert set(target_ids) == {"para-law-1", "para-case-1"}
    assert report["target_chunk_count"] == 2
    assert report["total_chunk_count"] == 4
    assert report["selected_chunk_count_by_doc_type"] == {"case": 1, "law": 1}
    assert report["selected_chunk_count_by_prompt_family"] == {"law": 1, "case": 1, "none": 0}
    assert report["semantic_target_reason_distribution"]["contains_negation_or_exception"] >= 1
    assert report["semantic_target_reason_distribution"]["contains_money_order"] >= 1


def test_baseline_delta_report_compares_against_broad_selector_baseline() -> None:
    report = {
        "target_chunk_count": 500,
        "target_chunk_rate": 0.2,
        "selected_chunk_count_by_doc_type": {"law": 300, "case": 200},
        "selected_chunk_count_by_section_kind": {"operative_provision": 250, "order": 100},
        "selected_chunk_count_by_prompt_family": {"law": 300, "case": 200, "none": 0},
    }
    delta = full_eval_module._baseline_delta_report(report)

    assert delta["old_target_chunk_count"] == 2151
    assert delta["new_target_chunk_count"] == 500
    assert delta["target_chunk_count_delta"] == -1651
    assert delta["selected_chunk_count_by_doc_type_delta"]["law"]["old"] == 1047
    assert delta["selected_chunk_count_by_prompt_family_delta"]["case"]["new"] == 200


def test_configure_full_eval_runtime_disables_llm_safely(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "wf-fast10")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    tracked_keys = [
        "CORPUS_METADATA_NORMALIZER_PROVIDER",
        "CORPUS_METADATA_NORMALIZER_MODEL",
        "CHUNK_SEMANTICS_PROVIDER",
        "CHUNK_SEMANTICS_MODEL",
        "AGENTIC_ENRICHMENT_LLM_ENABLED",
        "OPENAI_API_KEY",
    ]
    before = {key: os.environ.get(key) for key in tracked_keys}
    try:
        config = full_eval_module._configure_full_eval_runtime(
            llm_enabled=False,
            provider="azure",
            model="wf-gpt5mini-metadata",
            import_metadata_llm_enabled=False,
        )

        assert config["llm_enabled_requested"] is False
        assert config["llm_enabled_effective"] is False
        assert os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] == "0"
        assert os.environ["CORPUS_METADATA_NORMALIZER_PROVIDER"] == "openai"
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
