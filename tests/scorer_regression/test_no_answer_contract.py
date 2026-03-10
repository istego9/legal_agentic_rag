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

NO_ANSWER_MARKER = "No confident answer could be derived from the indexed corpus with current evidence."


def _telemetry() -> Telemetry:
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    return Telemetry(
        request_started_at=now,
        first_token_at=now,
        completed_at=now,
        ttft_ms=900,
        total_response_ms=1100,
        time_per_output_token_ms=1.0,
        input_tokens=8,
        output_tokens=8,
        model_name="test-model",
        route_name="history_lineage",
        judge_model_name=None,
        search_profile="history_lineage_graph_v1",
        telemetry_complete=True,
        trace_id=f"trace-{uuid4()}",
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


def test_aggregate_run_enforces_allowed_no_answer_form() -> None:
    valid_no_answer = QueryResponse(
        question_id="q-no-answer-ok",
        answer=NO_ANSWER_MARKER,
        answer_normalized=None,
        answer_type="free_text",
        confidence=0.0,
        route_name="history_lineage",
        abstained=True,
        sources=[],
        telemetry=_telemetry(),
        debug=None,
    )
    invalid_no_answer = QueryResponse(
        question_id="q-no-answer-bad",
        answer=12,
        answer_normalized=None,
        answer_type="number",
        confidence=0.3,
        route_name="history_lineage",
        abstained=True,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc",
                pdf_id="doc",
                page_num=0,
                page_index_base=0,
                source_page_id="doc_0",
                used=True,
                evidence_role="primary",
                score=1.0,
            )
        ],
        telemetry=_telemetry(),
        debug=None,
    )
    gold_questions = [
        {
            "question_id": "q-no-answer-ok",
            "canonical_answer": None,
            "answer_type": "free_text",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
        {
            "question_id": "q-no-answer-bad",
            "canonical_answer": None,
            "answer_type": "number",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    metrics = aggregate_run(
        _eval_run(),
        [valid_no_answer, invalid_no_answer],
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics["no_answer_precision"] == 1.0
    assert metrics["no_answer_recall"] == 1.0
    assert metrics["no_answer_form_valid_rate"] == 0.5
    assert metrics["contract_pass_rate"] == 0.5

    by_qid = {row["question_id"]: row for row in metrics["question_metrics"]}
    assert by_qid["q-no-answer-ok"]["no_answer_form_valid"] is True
    assert by_qid["q-no-answer-bad"]["no_answer_form_valid"] is False
    assert "no_answer_form_invalid" in by_qid["q-no-answer-bad"]["error_tags"]
    assert "no_answer_precision" in metrics["scorer_summary"]["markdown"]
    assert "telemetry_factor" in metrics["scorer_summary"]["markdown"]
