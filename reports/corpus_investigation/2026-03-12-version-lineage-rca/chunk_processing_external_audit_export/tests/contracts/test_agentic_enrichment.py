from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest import agentic_enrichment as enrichment_module  # noqa: E402


def _fixture_payload() -> dict:
    return {
        "documents": [
            {
                "document_id": "doc-1",
                "project_id": "proj-1",
                "doc_type": "law",
                "page_count": 1,
                "processing": {},
            }
        ],
        "pages": [
            {
                "page_id": "page-1",
                "document_id": "doc-1",
                "source_page_id": "law_0",
                "page_num": 0,
            }
        ],
        "paragraphs": [
            {
                "paragraph_id": "para-1",
                "page_id": "page-1",
                "document_id": "doc-1",
                "text": "The employer shall provide a written contract unless otherwise agreed.",
                "paragraph_class": "article_clause",
                "section_kind": "operative_provision",
                "entities": ["Employer"],
                "article_refs": ["Article 1"],
                "law_refs": ["Law No. 10"],
                "case_refs": [],
                "dates": ["2024-01-01"],
            }
        ],
        "chunk_search_documents": [
            {
                "chunk_id": "para-1",
                "document_id": "doc-1",
                "pdf_id": "law",
                "page_id": "page-1",
                "page_number": 0,
                "doc_type": "law",
                "text_clean": "The employer shall provide a written contract unless otherwise agreed.",
                "retrieval_text": "employer written contract law",
                "search_keywords": [],
                "edge_types": [],
            }
        ],
        "relation_edges": [],
    }


def test_agentic_enrichment_emits_role_runs_and_artifacts(monkeypatch) -> None:
    payload = _fixture_payload()
    monkeypatch.setattr(
        enrichment_module,
        "extract_chunk_semantics",
        lambda **kwargs: SimpleNamespace(payload={}, prompt_version="disabled", mode="rules_only"),
    )

    result = enrichment_module.run_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
    )

    job = result["job"]
    assert job["role_sequence"] == [
        "chunk_interpreter",
        "chunk_validator",
        "document_synthesizer",
        "projection_agent",
    ]
    assert isinstance(job["llm_enabled"], bool)
    assert str(job["llm_model_version"]).strip()
    assert job["llm_prompt_version"] == enrichment_module.CHUNK_INTERPRETER_PROMPT_VERSION
    assert "para-1" in job["chunk_stage_runs"]
    assert job["chunk_stage_runs"]["para-1"]["chunk_interpreter"]["status"] == "completed"
    assert job["chunk_stage_runs"]["para-1"]["chunk_interpreter"]["payload"]["llm_prompt_version"] == "disabled"
    assert job["chunk_stage_runs"]["para-1"]["chunk_validator"]["status"] == "completed"
    assert job["chunk_stage_runs"]["para-1"]["projection_agent"]["status"] == "completed"
    assert "doc-1" in job["document_stage_runs"]
    assert job["document_stage_runs"]["doc-1"]["document_synthesizer"]["status"] == "completed"
    assert result["chunk_assertions"][0]["paragraph_id"] == "para-1"
    assert result["chunk_assertions"][0]["modality"] in {
        "obligation",
        "prohibition",
        "permission",
        "definition",
        "power",
        "procedure",
        "penalty",
        "exception",
    }
    assert result["chunk_assertions"][0]["properties"]["evidence"]["source_page_ids"] == ["law_0"]
    assert result["document_views"][0]["document_id"] == "doc-1"
    assert result["updated_documents"]["doc-1"]["processing"]["agentic_enrichment"]["status"] == "completed"
    assert result["updated_documents"]["doc-1"]["processing"]["agentic_enrichment"]["llm_prompt_version"] == enrichment_module.CHUNK_INTERPRETER_PROMPT_VERSION


def test_candidate_ontology_labels_do_not_leak_into_retrieval_projection(monkeypatch) -> None:
    payload = _fixture_payload()
    monkeypatch.setattr(
        enrichment_module,
        "extract_chunk_semantics",
        lambda **kwargs: SimpleNamespace(
            payload={
                "semantic_dense_summary": "Employer must provide a written contract unless otherwise agreed.",
                "semantic_query_terms": ["written contract", "employer"],
                "propositions": [
                    {
                        "relation_type": "novel_bridge_duty",
                        "subject_type": "actor",
                        "subject_text": "Employer",
                        "object_type": "legal_object",
                        "object_text": "Written contract",
                        "modality": "obligation",
                        "polarity": "affirmative",
                        "conditions": [],
                        "exceptions": [],
                        "citation_refs": ["Article 1"],
                        "dense_paraphrase": "Employer must provide a written contract.",
                        "direct_answer": {"eligible": False, "answer_type": "none", "boolean_value": None, "number_value": None, "date_value": None, "text_value": None},
                    }
                ],
            },
            prompt_version="law_chunk_semantics_v1",
            mode="llm_merge",
        ),
    )

    result = enrichment_module.run_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
    )

    registry_by_key = {row["key"]: row for row in result["registry_entries"]}
    assert registry_by_key["novel_bridge_duty"]["status"] == "candidate"
    search_keywords = result["updated_chunk_projections"]["para-1"]["search_keywords"]
    assert "novel_bridge_duty" not in search_keywords


def test_chunk_retry_is_idempotent_for_assertion_identity(monkeypatch) -> None:
    payload = _fixture_payload()
    monkeypatch.setattr(
        enrichment_module,
        "extract_chunk_semantics",
        lambda **kwargs: SimpleNamespace(payload={}, prompt_version="disabled", mode="rules_only"),
    )

    first = enrichment_module.retry_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        existing_registry_entries=[],
        target_type="chunk",
        target_ids=["para-1"],
    )
    second = enrichment_module.retry_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
        existing_registry_entries=first["registry_entries"],
        target_type="chunk",
        target_ids=["para-1"],
    )

    assert first["chunk_assertions"][0]["assertion_id"] == second["chunk_assertions"][0]["assertion_id"]
    assert second["job"]["chunk_stage_runs"]["para-1"]["chunk_interpreter"]["status"] == "completed"


def test_agentic_enrichment_env_guard_disables_llm_client(monkeypatch) -> None:
    payload = _fixture_payload()

    class _FakeClient:
        def __init__(self, config=None) -> None:
            self.config = config

    monkeypatch.setenv("AGENTIC_ENRICHMENT_LLM_ENABLED", "0")
    monkeypatch.setattr(enrichment_module, "AzureLLMClient", _FakeClient)
    monkeypatch.setattr(
        enrichment_module,
        "extract_chunk_semantics",
        lambda **kwargs: SimpleNamespace(payload={"propositions": []}, prompt_version="disabled", mode="rules_only"),
    )

    result = enrichment_module.run_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
    )

    job = result["job"]
    assert job["llm_enabled"] is False
    assert job["llm_model_version"] == "disabled"


def test_agentic_enrichment_accepts_multiple_assertions(monkeypatch) -> None:
    payload = _fixture_payload()
    payload["paragraphs"][0]["text"] = (
        "Article 11. A provision to waive statutory minimum requirements is void. "
        "Nothing in this Law precludes an Employee from waiving rights by written agreement if legal advice or mediation conditions are met."
    )
    monkeypatch.setattr(
        enrichment_module,
        "extract_chunk_semantics",
        lambda **kwargs: SimpleNamespace(
            payload={
                "semantic_dense_summary": "Article 11 voids waiver clauses for minimum requirements and permits conditional employee waiver agreements.",
                "semantic_query_terms": ["waive", "void", "employee", "written agreement"],
                "propositions": [
                    {
                        "subject_type": "legal_object",
                        "subject_text": "agreement provision waiving minimum requirements",
                        "relation_type": "is_void",
                        "object_type": "legal_object",
                        "object_text": "void in all circumstances",
                        "modality": "prohibition",
                        "polarity": "affirmative",
                        "conditions": ["not expressly permitted under this Law"],
                        "exceptions": [],
                        "citation_refs": ["Article 11(1)"],
                        "dense_paraphrase": "A waiver clause for minimum requirements is void unless the law expressly permits it.",
                        "direct_answer": {"eligible": True, "answer_type": "boolean", "boolean_value": True, "number_value": None, "date_value": None, "text_value": None},
                    },
                    {
                        "subject_type": "actor",
                        "subject_text": "Employee",
                        "relation_type": "may_waive",
                        "object_type": "legal_object",
                        "object_text": "rights under this Law by written agreement",
                        "modality": "permission",
                        "polarity": "affirmative",
                        "conditions": ["legal advice opportunity or mediation"],
                        "exceptions": [],
                        "citation_refs": ["Article 11(2)(b)"],
                        "dense_paraphrase": "An employee may waive rights under the law in a written agreement if legal-advice or mediation conditions are met.",
                        "direct_answer": {"eligible": True, "answer_type": "boolean", "boolean_value": True, "number_value": None, "date_value": None, "text_value": None},
                    },
                ],
            },
            prompt_version="law_chunk_semantics_v1",
            mode="llm_merge",
        ),
    )

    result = enrichment_module.run_agentic_corpus_enrichment(
        project_id="proj-1",
        import_job_id="job-1",
        documents=payload["documents"],
        pages=payload["pages"],
        paragraphs=payload["paragraphs"],
        chunk_search_documents=payload["chunk_search_documents"],
        relation_edges=payload["relation_edges"],
    )

    assert len(result["chunk_assertions"]) == 2
    updated_projection = result["updated_chunk_projections"]["para-1"]
    assert updated_projection["semantic_assertion_count"] == 2
    assert len(updated_projection["semantic_assertions"]) == 2
    assert updated_projection["semantic_dense_summary"]
