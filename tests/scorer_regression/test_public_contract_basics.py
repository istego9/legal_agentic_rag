from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import EvalRun, PageRef, QueryResponse, Telemetry  # noqa: E402
from services.eval.engine import aggregate_run  # noqa: E402


def _telemetry(*, ttft_ms: int, complete: bool) -> Telemetry:
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    return Telemetry(
        request_started_at=now,
        first_token_at=now,
        completed_at=now,
        ttft_ms=ttft_ms,
        total_response_ms=ttft_ms + 100,
        time_per_output_token_ms=1.0,
        input_tokens=8,
        output_tokens=8,
        model_name="test-model",
        route_name="article_lookup",
        judge_model_name=None,
        search_profile="default",
        telemetry_complete=complete,
        trace_id=f"trace-{uuid4()}",
    )


def _response(
    *,
    question_id: str,
    answer: object,
    answer_type: str,
    source_page_ids: list[str],
    ttft_ms: int,
    telemetry_complete: bool,
    abstained: bool = False,
    confidence: float = 1.0,
) -> QueryResponse:
    sources = [
        PageRef(
            project_id="proj",
            document_id="doc",
            pdf_id="doc",
            page_num=int(source_page_id.rsplit("_", 1)[-1]),
            page_index_base=0,
            source_page_id=source_page_id,
            used=True,
            evidence_role="primary",
            score=1.0,
        )
        for source_page_id in source_page_ids
    ]
    return QueryResponse(
        question_id=question_id,
        answer=answer,
        answer_normalized=None,
        answer_type=answer_type,
        confidence=confidence,
        route_name="article_lookup",
        abstained=abstained,
        sources=sources,
        telemetry=_telemetry(ttft_ms=ttft_ms, complete=telemetry_complete),
        debug=None,
    )


def _eval_run() -> EvalRun:
    return EvalRun(
        eval_run_id=str(uuid4()),
        run_id=str(uuid4()),
        gold_dataset_id=str(uuid4()),
        scoring_policy_version="contest_v2026_public_rules_v1",
        judge_policy_version="judge_v1",
        status="completed",
        metrics={},
    )


def _catalog() -> dict[str, dict[str, object]]:
    return {
        "contest_v2026_public_rules_v1": {
            "policy_version": "contest_v2026_public_rules_v1",
            "policy_type": "contest_emulation",
            "beta": 2.5,
            "ttft_curve": {
                "mode": "piecewise_linear_avg_ttft",
                "best_seconds": 1.0,
                "best_factor": 1.05,
                "worst_seconds": 5.0,
                "worst_factor": 0.85,
            },
            "telemetry_policy": "run_level_factor",
        }
    }


def test_aggregate_run_exposes_contract_check_rates_and_summary() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            source_page_ids=["doc_0"],
            ttft_ms=900,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-2",
            answer="not-a-boolean",
            answer_type="boolean",
            source_page_ids=["doc_1"],
            ttft_ms=900,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-3",
            answer="C",
            answer_type="free_text",
            source_page_ids=["doc_2"],
            ttft_ms=900,
            telemetry_complete=False,
        ),
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": ["doc_0"]}],
        },
        {
            "question_id": "q-2",
            "canonical_answer": True,
            "answer_type": "boolean",
            "route_hint": "article_lookup",
            "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": ["doc_1"]}],
        },
        {
            "question_id": "q-3",
            "canonical_answer": "C",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": ["doc_2"]}],
        },
    ]

    metrics = aggregate_run(
        _eval_run(),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics["answer_schema_valid_rate"] == 2 / 3
    assert metrics["telemetry_completeness_rate"] == 2 / 3
    assert metrics["contract_pass_rate"] == 1 / 3
    assert metrics["source_page_id_valid_rate"] == 1.0
    assert metrics["no_answer_form_valid_rate"] == 1.0

    by_qid = {row["question_id"]: row for row in metrics["question_metrics"]}
    assert "answer_schema_invalid" in by_qid["q-2"]["error_tags"]
    assert "telemetry_incomplete" in by_qid["q-3"]["error_tags"]
    assert by_qid["q-2"]["contract_checks"]["answer_schema_valid"] is False
    assert by_qid["q-3"]["contract_checks"]["telemetry_contract_valid"] is False

    summary = metrics["scorer_summary"]["markdown"]
    assert "no_answer_precision" in summary
    assert "telemetry_completeness_rate" in summary
    assert "contract_pass_rate" in summary
