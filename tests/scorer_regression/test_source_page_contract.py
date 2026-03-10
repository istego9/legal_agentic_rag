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
        route_name="article_lookup",
        judge_model_name=None,
        search_profile="default",
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


def test_aggregate_run_flags_non_canonical_used_source_page_ids() -> None:
    response = QueryResponse(
        question_id="q-source",
        answer="A",
        answer_normalized=None,
        answer_type="free_text",
        confidence=1.0,
        route_name="article_lookup",
        abstained=False,
        sources=[
            PageRef(
                project_id="proj",
                document_id="doc",
                pdf_id="doc",
                page_num=5,
                page_index_base=0,
                source_page_id="doc_2",
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
            "question_id": "q-source",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": ["doc_5"]}],
        }
    ]
    metrics = aggregate_run(
        _eval_run(),
        [response],
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics["source_page_id_valid_rate"] == 0.0
    assert metrics["contract_pass_rate"] == 0.0
    question_metric = metrics["question_metrics"][0]
    assert question_metric["source_page_id_valid"] is False
    assert "invalid_source_page_id" in question_metric["error_tags"]
    assert any(
        issue == "source_page_id:sources[0].source_page_id_not_canonical"
        for issue in question_metric["contract_checks"]["issues"]
    )
