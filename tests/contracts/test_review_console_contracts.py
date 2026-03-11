from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import (  # noqa: E402
    CandidateAnswer,
    PageRef,
    QueryResponse,
    QuestionReviewRecord,
    RunQuestionReviewArtifact,
    Telemetry,
)


def test_run_question_review_artifact_accepts_legacy_payload_without_new_review_fields() -> None:
    now = datetime(2026, 3, 11, tzinfo=timezone.utc)
    artifact = RunQuestionReviewArtifact(
        run_id="run-1",
        question_id="q-1",
        question={"id": "q-1", "question": "Which case was decided earlier?", "answer_type": "name"},
        response=QueryResponse(
            question_id="q-1",
            answer="ENF 269/2023",
            answer_normalized="ENF 269/2023",
            answer_type="name",
            confidence=1.0,
            route_name="single_case_extraction",
            abstained=False,
            sources=[
                PageRef(
                    project_id="proj-1",
                    document_id="doc-1",
                    pdf_id="doc-1",
                    page_num=0,
                    page_index_base=0,
                    source_page_id="doc-1_0",
                    used=True,
                    evidence_role="primary",
                    score=1.0,
                )
            ],
            telemetry=Telemetry(
                request_started_at=now,
                first_token_at=now,
                completed_at=now,
                ttft_ms=10,
                total_response_ms=12,
                time_per_output_token_ms=1.0,
                input_tokens=1,
                output_tokens=1,
                model_name="deterministic-router",
                route_name="single_case_extraction",
                search_profile="default",
                telemetry_complete=True,
                trace_id="trace-1",
            ),
        ),
        evidence={"retrieved_chunk_ids": ["chunk-a"]},
        document_viewer={"documents": []},
        promotion_preview={"source_sets": []},
        created_at=now,
    )

    assert artifact.status == "needs_review"
    assert artifact.candidate_bundle == []
    assert artifact.accepted_decision is None


def test_question_review_record_schema_artifact_is_present_and_matches_title() -> None:
    payload = json.loads((ROOT / "schemas" / "review_record.schema.json").read_text(encoding="utf-8"))
    assert payload["title"] == "QuestionReviewRecord"
    assert "candidate_bundle" in payload["properties"]


def test_candidate_answer_supports_explicit_unavailable_state() -> None:
    candidate = CandidateAnswer(
        candidate_id="strong:q-1",
        candidate_kind="strong_model",
        answer=None,
        answerability="abstain",
        sources=[],
        support_status="unavailable",
        unavailable_reason="profile not configured",
    )
    record = QuestionReviewRecord(
        question_id="q-1",
        question="Which case was decided earlier?",
        answer_type="name",
        status="needs_review",
        candidate_bundle=[candidate],
    )

    assert record.candidate_bundle[0].support_status == "unavailable"
    assert record.candidate_bundle[0].unavailable_reason == "profile not configured"
