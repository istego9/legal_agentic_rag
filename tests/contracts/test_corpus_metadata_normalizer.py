from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest import corpus_metadata_normalizer as normalizer_module  # noqa: E402


class _DisabledClient:
    class config:
        enabled = False
        deployment = None
        model = None


class _FakeEnabledClient:
    class config:
        enabled = True
        deployment = "fake-title-model"
        model = None

    async def complete_chat(self, prompt: str, **kwargs):
        task = (kwargs.get("user_context") or {}).get("task")
        if task == "corpus_title_page_metadata_normalizer":
            if "employment-law" in prompt:
                return (
                    '{"canonical_document":{"title_raw":"Employment Law","title_normalized":"employment law","short_title":"Employment Law","citation_title":"Employment Law","jurisdiction":"DIFC","issued_date":"2019-01-01","effective_start_date":"2019-01-01","effective_end_date":"","ocr_used":false,"extraction_confidence":0.91},"type_specific_document":{"law_number":"2","law_year":2019,"instrument_kind":"law","administering_authority":"DIFC Authority","promulgation_date":"2019-01-01","commencement_date":"2019-01-01","last_consolidated_date":"2025-07-01"},"processing_candidates":{"consolidated_version_number":"5","consolidated_version_date":"2025-07-01","family_anchor_candidate":"employment"},"review":{"manual_review_required":false,"manual_review_reasons":[]}}',
                    {"prompt_tokens": 20, "completion_tokens": 10},
                )
            return (
                '{"canonical_document":{"doc_type":"case","title_raw":"Techteryx v Banks","title_normalized":"techteryx v banks","short_title":"Techteryx v Banks","citation_title":"Techteryx v Banks","jurisdiction":"DIFC","issued_date":"2025-10-17","ocr_used":false,"extraction_confidence":0.88},"type_specific_document":{"case_number":"DEC 001/2025","neutral_citation":"DEC 001/2025","court_name":"Digital Economy Court","court_level":"Court of First Instance","decision_date":"2025-10-17","judgment_date":"2025-10-17","claimant_names":["Techteryx Ltd"],"respondent_names":["Aria Commodities DM CC"],"appellant_names":[],"defendant_names":[],"judge_names":["Justice Example"],"presiding_judge":"Justice Example","procedural_stage":"judgment"},"processing_candidates":{"claim_number":"DEC 001/2025","appeal_number":"","document_role":"judgment","same_case_anchor_candidate":"dec_001_2025"},"review":{"manual_review_required":false,"manual_review_reasons":[]}}',
                {"prompt_tokens": 18, "completion_tokens": 11},
            )
        if task == "corpus_case_relation_resolver":
            return (
                '{"case_family_id":"dec_001_2025","primary_merits_document_id":"case-judgment","document_role_confirmations":{"case-judgment":"judgment","case-order":"order"},"relations":[{"source_document_id":"case-order","target_document_id":"case-judgment","case_relation_type":"order_for","confidence":0.93}],"family_review_required":false,"family_review_reasons":[]}',
                {"prompt_tokens": 14, "completion_tokens": 8},
            )
        return ("{}", {"prompt_tokens": 0, "completion_tokens": 0})


def _payload() -> dict:
    return {
        "documents": [
            {
                "document_id": "law-1",
                "project_id": "proj-1",
                "pdf_id": "employment-law",
                "canonical_doc_id": "employment-law-v1",
                "content_hash": "a" * 64,
                "doc_type": "law",
                "title": "Document employment-law",
                "title_raw": "Document employment-law",
                "title_normalized": "document employment-law",
                "citation_title": "Document employment-law",
                "law_number": "2",
                "year": 2019,
                "page_count": 1,
                "status": "parsed",
                "jurisdiction": "unknown",
                "issued_date": "2019-01-01",
                "effective_start_date": "2019-01-01",
                "effective_end_date": None,
                "is_current_version": True,
                "version_group_id": "law:employment:2",
                "ocr_used": False,
                "extraction_confidence": 0.6,
                "processing": {},
            },
            {
                "document_id": "case-judgment",
                "project_id": "proj-1",
                "pdf_id": "dec-case-judgment",
                "canonical_doc_id": "dec-case-judgment-v1",
                "content_hash": "b" * 64,
                "doc_type": "case",
                "title": "Document dec-case-judgment",
                "title_raw": "Document dec-case-judgment",
                "title_normalized": "document dec-case-judgment",
                "citation_title": "Document dec-case-judgment",
                "case_id": "DEC 001/2025",
                "year": 2025,
                "page_count": 1,
                "status": "parsed",
                "jurisdiction": "unknown",
                "issued_date": "2025-10-17",
                "is_current_version": True,
                "version_group_id": "case:dec_001_2025",
                "ocr_used": False,
                "extraction_confidence": 0.7,
                "processing": {},
            },
            {
                "document_id": "case-order",
                "project_id": "proj-1",
                "pdf_id": "dec-case-order",
                "canonical_doc_id": "dec-case-order-v1",
                "content_hash": "c" * 64,
                "doc_type": "case",
                "title": "Document dec-case-order",
                "title_raw": "Document dec-case-order",
                "title_normalized": "document dec-case-order",
                "citation_title": "Document dec-case-order",
                "case_id": "DEC 001/2025",
                "year": 2025,
                "page_count": 1,
                "status": "parsed",
                "jurisdiction": "unknown",
                "issued_date": "2025-10-17",
                "is_current_version": True,
                "version_group_id": "case:dec_001_2025",
                "ocr_used": False,
                "extraction_confidence": 0.7,
                "processing": {},
            },
        ],
        "document_bases": [
            {"document_id": "law-1", "doc_type": "law"},
            {"document_id": "case-judgment", "doc_type": "case"},
            {"document_id": "case-order", "doc_type": "case"},
        ],
        "law_documents": [
            {"document_id": "law-1", "law_number": "2", "law_year": 2019, "instrument_kind": "law"},
        ],
        "case_documents": [
            {"document_id": "case-judgment", "case_number": "DEC 001/2025", "procedural_stage": "unknown"},
            {"document_id": "case-order", "case_number": "DEC 001/2025", "procedural_stage": "unknown"},
        ],
        "pages": [
            {
                "page_id": "law-page-1",
                "document_id": "law-1",
                "source_page_id": "employment-law_0",
                "page_num": 0,
                "text": "EMPLOYMENT LAW DIFC LAW NO. 2 of 2019 Consolidated Version No. 5 (July 2025)",
            },
            {
                "page_id": "case-page-1",
                "document_id": "case-judgment",
                "source_page_id": "dec-case-judgment_0",
                "page_num": 0,
                "text": "Techteryx Ltd v Aria Commodities [2025] DIFC DEC 001 OCTOBER 17, 2025 DIGITAL ECONOMY COURT - JUDGMENTS Claim No. DEC 001/2025",
            },
            {
                "page_id": "case-page-2",
                "document_id": "case-order",
                "source_page_id": "dec-case-order_0",
                "page_num": 0,
                "text": "DEC 001/2025 OCTOBER 17, 2025 DIGITAL ECONOMY COURT - ORDERS Claim No. DEC 001/2025",
            },
        ],
        "chunk_search_documents": [
            {
                "chunk_id": "law-chunk-1",
                "document_id": "law-1",
                "page_id": "law-page-1",
                "doc_type": "law",
                "title_normalized": "document employment-law",
                "short_title": "Document employment-law",
                "jurisdiction": "unknown",
                "is_current_version": True,
                "effective_start_date": "2019-01-01",
                "effective_end_date": None,
                "law_number": "2",
                "law_year": 2019,
            },
            {
                "chunk_id": "case-chunk-1",
                "document_id": "case-judgment",
                "page_id": "case-page-1",
                "doc_type": "case",
                "title_normalized": "document dec-case-judgment",
                "short_title": "Document dec-case-judgment",
                "jurisdiction": "unknown",
                "case_number": "DEC 001/2025",
                "court_name": None,
                "decision_date": "2025-10-17",
            },
        ],
        "relation_edges": [],
    }


def test_rules_only_normalizer_populates_processing_and_case_relations() -> None:
    payload = _payload()

    result = normalizer_module.run_corpus_metadata_normalization(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        document_bases=payload["document_bases"],
        law_documents=payload["law_documents"],
        case_documents=payload["case_documents"],
        llm_client=_DisabledClient(),
    )

    assert result["job"]["llm_enabled"] is False
    assert "law-1" in result["updated_documents"]
    law_processing = result["updated_documents"]["law-1"]["processing"]["metadata_normalization"]
    assert law_processing["mode"] == "rules_only"
    assert law_processing["canonical_document"]["doc_type"] == "law"
    assert "case-judgment" in result["updated_documents"]
    case_processing = result["updated_documents"]["case-order"]["processing"]["case_relation_resolution"]
    assert case_processing["status"] == "completed"
    assert case_processing["primary_merits_document_id"] == "case-judgment"
    assert case_processing["relation_targets"][0]["case_relation_type"] == "order_for"
    relation_edges = result["projected_relation_edges"]
    assert any(edge.get("case_relation_type") == "order_for" for edge in relation_edges)


def test_llm_normalizer_merges_title_metadata_and_case_resolution(tmp_path: Path, monkeypatch) -> None:
    payload = _payload()
    monkeypatch.setattr(normalizer_module, "_normalizer_cache_dir", lambda: tmp_path / "cache")

    result = normalizer_module.run_corpus_metadata_normalization(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        document_bases=payload["document_bases"],
        law_documents=payload["law_documents"],
        case_documents=payload["case_documents"],
        llm_client=_FakeEnabledClient(),
    )

    assert result["job"]["llm_enabled"] is True
    assert result["job"]["llm_calls"] >= 3
    law_doc = result["updated_documents"]["law-1"]
    assert law_doc["title"] == "Employment Law"
    assert law_doc["jurisdiction"] == "DIFC"
    assert law_doc["processing"]["metadata_normalization"]["mode"] == "llm_merge"
    case_doc = result["updated_documents"]["case-judgment"]
    assert case_doc["case_id"] == "DEC 001/2025"
    case_stage = result["updated_case_documents"]["case-order"]["procedural_stage"]
    assert case_stage == "order"
    relation_edges = result["projected_relation_edges"]
    assert any(edge.get("case_relation_type") == "order_for" for edge in relation_edges)
    assert result["updated_chunk_projections"]["law-chunk-1"]["title_normalized"] == "employment law"


def test_llm_normalizer_retries_429_and_reuses_cache(tmp_path: Path, monkeypatch) -> None:
    payload = _payload()
    title_calls = {"count": 0}
    relation_calls = {"count": 0}

    class _CacheClient:
        class config:
            enabled = True
            deployment = "fake-cache-model"
            model = None

    def _fake_title_page_llm(client, *, envelope, pdf_id):
        title_calls["count"] += 1
        if title_calls["count"] == 1:
            raise RuntimeError("Azure OpenAI request failed: 429 Too Many Requests")
        return (
            {
                "canonical_document": {"title_raw": f"{pdf_id}-normalized", "title_normalized": f"{pdf_id}-normalized"},
                "type_specific_document": {},
                "processing_candidates": {},
                "review": {"manual_review_required": False, "manual_review_reasons": []},
            },
            {"prompt_tokens": 5, "completion_tokens": 2},
        )

    def _fake_case_relation_llm(client, *, group_key, docs):
        relation_calls["count"] += 1
        return (
            {
                "case_family_id": group_key,
                "primary_merits_document_id": "case-judgment",
                "document_role_confirmations": {"case-judgment": "judgment", "case-order": "order"},
                "relations": [
                    {
                        "source_document_id": "case-order",
                        "target_document_id": "case-judgment",
                        "case_relation_type": "order_for",
                        "confidence": 0.9,
                    }
                ],
                "family_review_required": False,
                "family_review_reasons": [],
            },
            {"prompt_tokens": 4, "completion_tokens": 2},
        )

    monkeypatch.setattr(normalizer_module, "_title_page_llm", _fake_title_page_llm)
    monkeypatch.setattr(normalizer_module, "_case_relation_llm", _fake_case_relation_llm)
    monkeypatch.setattr(normalizer_module, "_normalizer_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(normalizer_module, "_request_spacing_seconds", lambda: 0.0)
    monkeypatch.setattr(normalizer_module, "_retry_limit", lambda: 2)
    monkeypatch.setattr(normalizer_module, "_retry_delay_seconds", lambda attempt: 0.0)
    monkeypatch.setattr(normalizer_module, "_sleep", lambda seconds: None)

    first = normalizer_module.run_corpus_metadata_normalization(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        document_bases=payload["document_bases"],
        law_documents=payload["law_documents"],
        case_documents=payload["case_documents"],
        llm_client=_CacheClient(),
    )
    second = normalizer_module.run_corpus_metadata_normalization(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        document_bases=payload["document_bases"],
        law_documents=payload["law_documents"],
        case_documents=payload["case_documents"],
        llm_client=_CacheClient(),
    )

    assert first["job"]["rate_limit_retry_count"] >= 1
    assert first["job"]["cache_hit_count"] == 0
    assert second["job"]["cache_hit_count"] >= 3
    assert title_calls["count"] == 4
    assert relation_calls["count"] == 1


def test_merge_title_envelope_derives_case_anchor_and_clears_false_missing_anchor_review() -> None:
    base = {
        "canonical_document": {
            "doc_type": "case",
            "title_raw": None,
            "title_normalized": None,
            "short_title": None,
            "citation_title": None,
            "language": "unknown",
            "jurisdiction": "unknown",
            "issued_date": "2025-12-03",
            "effective_start_date": None,
            "effective_end_date": None,
            "ocr_used": False,
            "extraction_confidence": 0.7,
        },
        "type_specific_document": {
            "case_number": None,
            "neutral_citation": None,
            "court_name": None,
            "court_level": None,
            "decision_date": "2025-12-03",
            "judgment_date": None,
            "claimant_names": [],
            "respondent_names": [],
            "appellant_names": [],
            "defendant_names": [],
            "judge_names": [],
            "presiding_judge": None,
            "procedural_stage": "reasons",
        },
        "processing_candidates": {
            "claim_number": None,
            "appeal_number": None,
            "document_role": "reasons",
            "same_case_anchor_candidate": None,
        },
        "review": {
            "manual_review_required": True,
            "manual_review_reasons": ["missing_case_anchor"],
        },
        "context": {
            "page_1_text": "TCD 001/2024 ARCHITERIORS v EMIRATES Claim No: TCD 001/2024 ORDER WITH REASONS",
            "page_2_text": "",
            "source_page_ids": ["sample_0"],
        },
    }
    llm_payload = {
        "canonical_document": {"doc_type": "case", "title_raw": "Architeriors v Emirates"},
        "type_specific_document": {
            "case_number": "TCD 001/2024",
            "neutral_citation": "TCD 001/2024",
            "procedural_stage": "reasons",
        },
        "processing_candidates": {
            "claim_number": "TCD 001/2024",
            "same_case_anchor_candidate": "",
            "document_role": "reasons",
        },
        "review": {
            "manual_review_required": True,
            "manual_review_reasons": ["missing_case_anchor"],
        },
    }

    merged = normalizer_module._merge_title_envelope(base, llm_payload)

    assert merged["type_specific_document"]["case_number"] == "TCD 001/2024"
    assert merged["processing_candidates"]["same_case_anchor_candidate"] == "tcd_001_2024"
    assert merged["review"]["manual_review_required"] is False
    assert merged["review"]["manual_review_reasons"] == []


def test_merge_title_envelope_forces_case_doc_type_and_prunes_legislative_fields() -> None:
    base = {
        "canonical_document": {
            "doc_type": "other",
            "title_raw": None,
            "title_normalized": None,
            "short_title": None,
            "citation_title": None,
            "language": "unknown",
            "jurisdiction": "unknown",
            "issued_date": "2026-02-06",
            "effective_start_date": None,
            "effective_end_date": None,
            "ocr_used": False,
            "extraction_confidence": 0.7,
        },
        "type_specific_document": {},
        "processing_candidates": {},
        "review": {
            "manual_review_required": False,
            "manual_review_reasons": [],
        },
        "context": {
            "page_1_text": "CFI 067/2025 Coinmena v Foloosi Claim No: CFI 067/2025 COURT OF FIRST INSTANCE - ORDERS",
            "page_2_text": "",
            "source_page_ids": ["sample_0"],
        },
    }
    llm_payload = {
        "canonical_document": {
            "doc_type": "regulation",
            "title_raw": "Order with Reasons of H.E. Justice Shamlan Al Sawalehi",
            "effective_start_date": "2026-02-06",
        },
        "type_specific_document": {
            "regulation_type": "court order",
            "regulation_year": 2026,
            "regulation_number": None,
            "case_number": "CFI 067/2025",
            "neutral_citation": "CFI 067/2025",
        },
        "processing_candidates": {
            "claim_number": "CFI 067/2025",
            "document_role": "order",
        },
        "review": {
            "manual_review_required": True,
            "manual_review_reasons": ["missing_legislative_number"],
        },
    }

    merged = normalizer_module._merge_title_envelope(base, llm_payload)

    assert merged["canonical_document"]["doc_type"] == "case"
    assert "regulation_type" not in merged["type_specific_document"]
    assert merged["type_specific_document"]["case_number"] == "CFI 067/2025"
    assert merged["processing_candidates"]["same_case_anchor_candidate"] == "cfi_067_2025"
    assert merged["review"]["manual_review_required"] is False
    assert merged["review"]["manual_review_reasons"] == []


def test_base_envelope_does_not_seed_placeholder_titles() -> None:
    document = {
        "doc_type": "case",
        "title": "Document c98c1475692b",
        "title_raw": "Document c98c1475692b",
        "title_normalized": "document c98c1475692b",
        "citation_title": "Document c98c1475692b",
        "issued_date": "2025-12-30",
        "case_id": "TCD 001/2024",
        "ocr_used": False,
        "processing": {},
    }
    pages = [
        {
            "source_page_id": "sample_0",
            "text": "TCD 001/2024 Claim No: TCD 001/2024 TECHNOLOGY AND CONSTRUCTION DIVISION - ORDERS",
        }
    ]

    envelope = normalizer_module._base_envelope(document, pages)

    assert envelope["canonical_document"]["title_raw"] is None
    assert envelope["canonical_document"]["short_title"] is None
    assert envelope["canonical_document"]["citation_title"] is None


def test_merge_title_envelope_clears_reasonless_manual_review_for_complete_law() -> None:
    base = {
        "canonical_document": {
            "doc_type": "law",
            "title_raw": "TRUST LAW DIFC LAW NO. 4 OF 2018",
            "title_normalized": "trust law difc law no. 4 of 2018",
            "short_title": "Trust Law",
            "citation_title": "Trust Law",
            "language": "unknown",
            "jurisdiction": "DIFC",
            "issued_date": "2018-01-01",
            "effective_start_date": "2018-01-01",
            "effective_end_date": None,
            "ocr_used": False,
            "extraction_confidence": 0.8,
        },
        "type_specific_document": {
            "law_number": "4",
            "law_year": 2018,
            "instrument_kind": "law",
            "administering_authority": None,
            "promulgation_date": "2018-01-01",
            "commencement_date": "2018-01-01",
            "last_consolidated_date": "2024-03-01",
        },
        "processing_candidates": {
            "consolidated_version_number": "3",
            "consolidated_version_date": "2024-03-01",
            "enabled_by_law_number": None,
            "enabled_by_law_year": None,
            "family_anchor_candidate": "trust",
        },
        "review": {
            "manual_review_required": False,
            "manual_review_reasons": [],
        },
        "context": {
            "page_1_text": "TRUST LAW DIFC LAW NO. 4 OF 2018 Consolidated Version No. 3 (March 2024)",
            "page_2_text": "",
            "source_page_ids": ["sample_0"],
        },
    }
    llm_payload = {
        "canonical_document": {"doc_type": "law"},
        "type_specific_document": {"law_number": "4", "law_year": 2018},
        "processing_candidates": {"family_anchor_candidate": "trust"},
        "review": {"manual_review_required": True, "manual_review_reasons": []},
    }

    merged = normalizer_module._merge_title_envelope(base, llm_payload)

    assert merged["review"]["manual_review_required"] is False
    assert merged["review"]["manual_review_reasons"] == []


def test_merge_title_envelope_drops_non_issue_case_review_reasons() -> None:
    base = {
        "canonical_document": {
            "doc_type": "case",
            "title_raw": "LXT v SIR",
            "title_normalized": "lxt v sir",
            "short_title": "LXT v SIR",
            "citation_title": "CA 005/2025",
            "language": "unknown",
            "jurisdiction": "DIFC",
            "issued_date": "2026-01-21",
            "effective_start_date": None,
            "effective_end_date": None,
            "ocr_used": False,
            "extraction_confidence": 0.8,
        },
        "type_specific_document": normalizer_module._case_type_specific_template("CA 005/2025", "2026-01-21", "reasons"),
        "processing_candidates": normalizer_module._case_processing_candidates_template("CA 005/2025", "reasons"),
        "review": {
            "manual_review_required": False,
            "manual_review_reasons": [],
        },
        "context": {
            "page_1_text": "CA 005/2025 Claim No: CA 005/2025 COURT OF APPEAL - ORDERS",
            "page_2_text": "",
            "source_page_ids": ["sample_0"],
        },
    }
    llm_payload = {
        "canonical_document": {"doc_type": "case"},
        "type_specific_document": {"case_number": "CA 005/2025"},
        "processing_candidates": {"claim_number": "CA 005/2025", "same_case_anchor_candidate": "ca_005_2025"},
        "review": {
            "manual_review_required": True,
            "manual_review_reasons": [
                "No issues identified requiring manual review.",
                "The document is a court/case document with case number CA 005/2025.",
            ],
        },
    }

    merged = normalizer_module._merge_title_envelope(base, llm_payload)

    assert merged["review"]["manual_review_required"] is False
    assert merged["review"]["manual_review_reasons"] == []


def test_title_prompt_is_typed_by_document_family() -> None:
    envelope = {
        "canonical_document": {"doc_type": "law"},
        "type_specific_document": {},
        "processing_candidates": {},
        "review": {},
        "context": {"page_1_text": "LAW", "page_2_text": ""},
    }

    prompt_name, system_prompt, user_prompt = normalizer_module._title_page_prompt(envelope, "law-pdf")

    assert prompt_name == "corpus_law_title_identity_v1"
    assert "typed extraction contract `corpus_law_title_identity_v1`" in user_prompt
    assert "title_page_amending_law_refs" in user_prompt
    assert "structured metadata from legal document title pages" in system_prompt


def test_build_metadata_normalizer_client_supports_gpt5_override(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "wf-fast10")
    monkeypatch.setenv("CORPUS_METADATA_NORMALIZER_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.delenv("CORPUS_METADATA_NORMALIZER_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("CORPUS_METADATA_NORMALIZER_TOKEN_PARAMETER", raising=False)

    client = normalizer_module.build_metadata_normalizer_client()

    assert client.config.deployment == "gpt-5-mini"
    assert client.config.reasoning_effort == "minimal"
    assert client.config.token_parameter == "max_completion_tokens"


def test_extract_title_page_amending_law_refs() -> None:
    refs = normalizer_module._extract_title_page_amending_law_refs(
        "TRUST LAW DIFC LAW NO. 4 OF 2018 As Amended by DIFC Laws Amendment Law DIFC Law No. 3 of 2024 "
        "DIFC Laws Amendment Law DIFC Law No. 1 of 2024"
    )

    assert len(refs) >= 1
    assert refs[0]["law_number"] == "3"
    assert refs[0]["law_year"] == 2024
