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


def test_normalize_chunk_semantics_disables_free_text_direct_answer_hint() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind_case": "order",
            "semantic_dense_summary": "Order summary.",
            "semantic_query_terms": ["order"],
            "propositions": [
                {
                    "subject_type": "actor",
                    "subject_text": "respondent",
                    "relation_type": "ordered_to_pay",
                    "object_type": "money_amount",
                    "object_text": "AED 10,000",
                    "modality": "obligation",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Operative paragraph 1"],
                    "dense_paraphrase": "The respondent must pay AED 10,000.",
                    "direct_answer": {"eligible": True, "answer_type": "free_text", "text_value": "The respondent must pay AED 10,000."},
                }
            ],
        },
        doc_type="case",
    )

    proposition = payload["propositions"][0]
    assert proposition["direct_answer"]["eligible"] is False
    assert proposition["direct_answer"]["answer_type"] == "none"
    assert proposition["direct_answer"]["text_value"] is None


def test_postprocess_legislative_payload_backfills_conditions_and_disables_direct_answer() -> None:
    payload = {
        "section_kind": "operative_provision",
        "provision_kind": "permission",
        "semantic_dense_summary": "An employee may waive rights under conditions.",
        "semantic_query_terms": ["employee", "waive"],
        "propositions": [
            {
                "subject_type": "actor",
                "subject_text": "employee",
                "relation_type": "permits",
                "object_type": "legal_object",
                "object_text": "waive rights under the law",
                "modality": "permission",
                "polarity": "affirmative",
                "conditions": [],
                "exceptions": [],
                "citation_refs": ["Article 11(2)(b)"],
                "dense_paraphrase": "An employee may waive rights under the law.",
                "direct_answer": {"eligible": True, "answer_type": "boolean", "boolean_value": True},
            }
        ],
    }
    processed = chunk_semantics_module._postprocess_chunk_semantics_payload(
        payload,
        doc_type="law",
        paragraph={
            "text": "Nothing in this Law precludes an employee from waiving rights by written agreement with the employer to terminate employment, subject to Article 66(13) and the employee being given an opportunity to receive independent legal advice or taking part in mediation."
        },
        projection={"article_number": "11"},
    )
    proposition = processed["propositions"][0]
    assert proposition["conditions"]
    assert any("subject to" in item.lower() or "legal advice" in item.lower() or "mediation" in item.lower() for item in proposition["conditions"])
    assert proposition["direct_answer"]["eligible"] is False


def test_postprocess_case_payload_backfills_amount_and_interest_propositions() -> None:
    payload = {
        "section_kind_case": "order",
        "semantic_dense_summary": "The applicant must pay the costs award.",
        "semantic_query_terms": ["costs award"],
        "propositions": [
            {
                "subject_type": "actor",
                "subject_text": "Applicant",
                "relation_type": "requires",
                "object_type": "deadline",
                "object_text": "within 14 days",
                "modality": "obligation",
                "polarity": "affirmative",
                "conditions": [],
                "exceptions": [],
                "citation_refs": ["Operative paragraph 2"],
                "dense_paraphrase": "The applicant must pay within 14 days.",
                "direct_answer": {"eligible": True, "answer_type": "number", "number_value": 14},
            }
        ],
    }
    processed = chunk_semantics_module._postprocess_chunk_semantics_payload(
        payload,
        doc_type="case",
        paragraph={
            "text": "The Applicant shall pay 10,000 AED within 14 days, failing which interest shall accrue at 9% per annum."
        },
        projection={"section_kind_case": "order"},
    )
    relations = [item["relation_type"] for item in processed["propositions"]]
    assert "ordered_to_pay" in relations
    assert "accrues_interest" in relations
    amount_prop = next(item for item in processed["propositions"] if item["relation_type"] == "ordered_to_pay")
    assert amount_prop["direct_answer"]["answer_type"] == "number"
    assert amount_prop["direct_answer"]["number_value"] == 10000
    interest_prop = next(item for item in processed["propositions"] if item["relation_type"] == "accrues_interest")
    assert interest_prop["conditions"]
    assert interest_prop["direct_answer"]["eligible"] is False


def test_case_parties_chunk_is_not_semantically_rich() -> None:
    assert chunk_semantics_module._is_semantically_rich_chunk(
        "case",
        {"text": "BETWEEN ALPHA Claimant and BETA Defendant", "section_kind": "parties"},
        {"section_kind_case": "parties"},
    ) is False


def test_normalize_chunk_semantics_maps_regulation_and_notice_relation_aliases() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "procedure",
            "semantic_dense_summary": "Compliance filing and commencement effects.",
            "semantic_query_terms": ["compliance", "commencement"],
            "propositions": [
                {
                    "subject_type": "actor",
                    "subject_text": "regulated person",
                    "relation_type": "obligation",
                    "object_type": "action_and_timing",
                    "object_text": "file annual return within 30 days",
                    "modality": "obligation",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Article 19"],
                    "dense_paraphrase": "A regulated person must file an annual return within 30 days.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                },
                {
                    "subject_type": "law_reference",
                    "subject_text": "Articles 1 to 5",
                    "relation_type": "comes_into_force_on",
                    "object_type": "date",
                    "object_text": "1 January 2027",
                    "modality": "procedure",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": ["except Article 4"],
                    "citation_refs": ["Notice paragraph 1"],
                    "dense_paraphrase": "Articles 1 to 5 come into force on 1 January 2027 except Article 4.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                },
            ],
        },
        doc_type="regulation",
    )
    relations = [item["relation_type"] for item in payload["propositions"]]
    assert relations == ["requires", "governs"]
