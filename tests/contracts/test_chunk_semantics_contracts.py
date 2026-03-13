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


def test_semantic_target_selection_marks_conditional_legislative_chunk() -> None:
    selection = chunk_semantics_module.semantic_target_selection(
        "law",
        {
            "text": (
                "Nothing in this Law precludes an employee from waiving rights by written agreement with the employer, "
                "subject to Article 66(13) and the employee being given an opportunity to receive independent legal advice."
            ),
            "section_kind": "operative_provision",
            "chunk_type": "paragraph",
        },
        {"article_number": "11"},
    )
    assert selection.selected is True
    assert "contains_negation_or_exception" in selection.reasons
    assert any(item in selection.target_classes for item in ("carve_out", "exception"))
    assert selection.prompt_family == "law"


def test_semantic_target_selection_excludes_definition_block_by_default() -> None:
    selection = chunk_semantics_module.semantic_target_selection(
        "law",
        {
            "text": "In this Law, Employee means a natural person engaged under a contract of employment.",
            "section_kind": "definition",
            "chunk_type": "paragraph",
        },
        {},
    )
    assert selection.selected is False
    assert selection.reasons == ()


def test_semantic_target_selection_marks_case_order_money_deadline_interest() -> None:
    selection = chunk_semantics_module.semantic_target_selection(
        "case",
        {
            "text": "The Applicant shall pay 10,000 AED within 14 days, failing which interest shall accrue at 9% per annum.",
            "section_kind": "order",
            "chunk_type": "list_item",
        },
        {"section_kind_case": "order"},
    )
    assert selection.selected is True
    assert "contains_money_order" in selection.reasons
    assert "contains_deadline" in selection.reasons
    assert "contains_interest_clause" in selection.reasons
    assert any(item in selection.target_classes for item in ("costs_order", "order_item"))
    assert any(item in selection.target_classes for item in ("deadline_clause", "interest_clause"))
    assert selection.prompt_family == "case"


def test_semantic_target_selection_marks_notice_commencement_rule() -> None:
    selection = chunk_semantics_module.semantic_target_selection(
        "enactment_notice",
        {
            "text": (
                "This Notice brings Articles 1 to 5 of the Target Law into force on 1 January 2027, "
                "except Article 4, which shall come into force on a date appointed by a further notice."
            ),
            "section_kind": "procedure",
            "chunk_type": "paragraph",
        },
        {},
    )
    assert selection.selected is True
    assert "contains_notice_commencement" in selection.reasons
    assert any(item in selection.target_classes for item in ("notice_rule", "commencement_rule"))


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
                {
                    "subject_type": "actor",
                    "subject_text": "contravening person",
                    "relation_type": "is_liable_to",
                    "object_type": "penalty",
                    "object_text": "a fine not exceeding AED 50,000",
                    "modality": "penalty",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Article 20"],
                    "dense_paraphrase": "A contravening person is liable to a fine up to AED 50,000.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                },
            ],
        },
        doc_type="regulation",
    )
    relations = [item["relation_type"] for item in payload["propositions"]]
    assert relations == ["requires", "governs", "penalizes"]


def test_normalize_chunk_semantics_maps_duty_to_file_to_requires() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "obligation",
            "semantic_dense_summary": "A regulated person must file an annual return.",
            "semantic_query_terms": ["annual return"],
            "propositions": [
                {
                    "subject_type": "actor",
                    "subject_text": "regulated person",
                    "relation_type": "duty_to_file",
                    "object_type": "legal_object",
                    "object_text": "annual compliance return within 30 days",
                    "modality": "obligation",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Article 19"],
                    "dense_paraphrase": "A regulated person must file the annual compliance return within 30 days.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                }
            ],
        },
        doc_type="regulation",
    )

    assert payload["propositions"][0]["relation_type"] == "requires"


def test_normalize_chunk_semantics_maps_comes_into_force_to_governs() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "procedure",
            "semantic_dense_summary": "The notice brings provisions into force on a stated date.",
            "semantic_query_terms": ["comes into force"],
            "propositions": [
                {
                    "subject_type": "law_articles",
                    "subject_text": "Articles 1 to 5",
                    "relation_type": "comes_into_force",
                    "object_type": "date",
                    "object_text": "1 January 2027",
                    "modality": "procedure",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": ["except Article 4"],
                    "citation_refs": ["Notice paragraph 1"],
                    "dense_paraphrase": "Articles 1 to 5 come into force on 1 January 2027 except Article 4.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                }
            ],
        },
        doc_type="enactment_notice",
    )

    assert payload["propositions"][0]["relation_type"] == "governs"


def test_normalize_chunk_semantics_maps_notice_commencement_aliases_to_governs() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "procedure",
            "semantic_dense_summary": "Specified provisions commence on the stated date, with one article requiring further notice.",
            "semantic_query_terms": ["commencement", "further notice"],
            "propositions": [
                {
                    "subject_type": "law_articles",
                    "subject_text": "Articles 1 to 5",
                    "relation_type": "commences_on",
                    "object_type": "date",
                    "object_text": "1 January 2027",
                    "modality": "procedure",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": ["except Article 4"],
                    "citation_refs": ["Notice paragraph 1"],
                    "dense_paraphrase": "Articles 1 to 5 commence on 1 January 2027 except Article 4.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                },
                {
                    "subject_type": "law_article",
                    "subject_text": "Article 4",
                    "relation_type": "commencement_requires",
                    "object_type": "notice_requirement",
                    "object_text": "a further notice appointing the commencement date",
                    "modality": "procedure",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Notice paragraph 1"],
                    "dense_paraphrase": "Article 4 commences only when a further notice appoints its date.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                },
            ],
        },
        doc_type="enactment_notice",
    )

    relations = [item["relation_type"] for item in payload["propositions"]]
    assert relations == ["governs", "governs"]


def test_normalize_chunk_semantics_maps_is_punishable_by_to_penalizes() -> None:
    payload = chunk_semantics_module.normalize_chunk_semantics_payload(
        {
            "section_kind": "operative_provision",
            "provision_kind": "penalty",
            "semantic_dense_summary": "A contravention is punishable by a fine.",
            "semantic_query_terms": ["fine"],
            "propositions": [
                {
                    "subject_type": "act_infringement",
                    "subject_text": "contravention",
                    "relation_type": "is_punishable_by",
                    "object_type": "penalty",
                    "object_text": "a fine not exceeding AED 50,000",
                    "modality": "procedure",
                    "polarity": "affirmative",
                    "conditions": [],
                    "exceptions": [],
                    "citation_refs": ["Article 19"],
                    "dense_paraphrase": "The contravention is punishable by a fine up to AED 50,000.",
                    "direct_answer": {"eligible": False, "answer_type": "none"},
                }
            ],
        },
        doc_type="regulation",
    )

    assert payload["propositions"][0]["relation_type"] == "penalizes"
