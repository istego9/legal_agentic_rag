from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest import chunk_semantics as chunk_semantics_module  # noqa: E402


def test_prompt_files_exist() -> None:
    prompt_root = ROOT / "packages" / "prompts"
    assert (prompt_root / "law_chunk_semantics_v1.md").exists()
    assert (prompt_root / "case_chunk_semantics_v1.md").exists()


def test_normalize_chunk_semantics_payload_law() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "prohibition",
            "semantic_dense_summary": "A waiver clause is void unless the law expressly permits it.",
            "semantic_query_terms": ["waive", "void", "minimum requirements"],
            "propositions": [
                {
                    "subject_type": "legal_object",
                    "subject_text": "waiver clause",
                    "relation_type": "is_void",
                    "object_type": "legal_object",
                    "object_text": "void in all circumstances",
                    "modality": "prohibition",
                    "polarity": "affirmative",
                    "conditions": ["not expressly permitted under this Law"],
                    "exceptions": [],
                    "citation_refs": ["Article 11(1)"],
                    "dense_paraphrase": "A waiver clause is void unless expressly permitted.",
                    "direct_answer": {"eligible": True, "answer_type": "boolean", "boolean_value": True},
                }
            ],
        },
        doc_type="law",
    )

    assert payload["section_kind"] == "operative_provision"
    assert payload["provision_kind"] == "prohibition"
    assert payload["semantic_query_terms"] == ["waive", "void", "minimum requirements"]
    assert payload["propositions"][0]["relation_type"] == "is_void"


def test_normalize_chunk_semantics_payload_case() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind_case": "order",
            "semantic_dense_summary": "Applicant must pay costs within 14 days.",
            "semantic_query_terms": ["costs", "14 days"],
            "propositions": [
                {
                    "subject_type": "actor",
                    "subject_text": "Applicant",
                    "relation_type": "ordered_to_pay",
                    "object_type": "legal_object",
                    "object_text": "USD 155,879.50",
                    "modality": "obligation",
                    "polarity": "affirmative",
                    "conditions": ["within 14 days"],
                    "exceptions": [],
                    "citation_refs": ["Operative paragraph 1"],
                    "dense_paraphrase": "Applicant must pay USD 155,879.50 within 14 days.",
                    "direct_answer": {"eligible": True, "answer_type": "number", "number_value": 155879.5},
                }
            ],
        },
        doc_type="case",
    )

    assert payload["section_kind_case"] == "order"
    assert payload["semantic_query_terms"] == ["costs", "14 days"]
    assert payload["propositions"][0]["direct_answer"]["answer_type"] == "number"


def test_normalize_chunk_semantics_aliases_invalidity_and_cleans_citations() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "procedure",
            "semantic_dense_summary": "A waiver provision is invalid.",
            "semantic_query_terms": ["waiver", "void"],
            "propositions": [
                {
                    "subject_type": "legal_object",
                    "subject_text": "waiver provision",
                    "relation_type": "invalidates",
                    "object_type": "legal_object",
                    "object_text": "minimum-rights waiver clause",
                    "modality": "invalidity",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Article 11(1)", "Law are", "action"],
                    "dense_paraphrase": "The minimum-rights waiver clause is void.",
                    "direct_answer": {"eligible": True, "answer_type": "boolean"},
                }
            ],
        },
        doc_type="law",
    )

    proposition = payload["propositions"][0]
    assert proposition["relation_type"] == "is_void"
    assert proposition["citation_refs"] == ["Article 11(1)"]
    assert proposition["direct_answer"]["boolean_value"] is True
