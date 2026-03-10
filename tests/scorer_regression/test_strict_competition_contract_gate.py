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


def _telemetry(
    *,
    ttft_ms: int = 900,
    total_response_ms: int | None = None,
    complete: bool = True,
) -> Telemetry:
    now = datetime(2026, 3, 10, tzinfo=timezone.utc)
    total_ms = total_response_ms if total_response_ms is not None else ttft_ms + 100
    return Telemetry(
        request_started_at=now,
        first_token_at=now,
        completed_at=now,
        ttft_ms=ttft_ms,
        total_response_ms=total_ms,
        time_per_output_token_ms=1.0,
        input_tokens=8,
        output_tokens=8,
        model_name="strict-gate-model",
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
    abstained: bool = False,
    confidence: float = 1.0,
    sources: list[PageRef] | None = None,
    telemetry: Telemetry | None = None,
) -> QueryResponse:
    return QueryResponse(
        question_id=question_id,
        answer=answer,
        answer_normalized=None,
        answer_type=answer_type,
        confidence=confidence,
        route_name="article_lookup",
        abstained=abstained,
        sources=sources or [],
        telemetry=telemetry or _telemetry(),
        debug=None,
    )


def _source(*, pdf_id: str = "doc", page_num: int = 0, source_page_id: str = "doc_0", used: bool = True) -> PageRef:
    return PageRef(
        project_id="proj",
        document_id="doc",
        pdf_id=pdf_id,
        page_num=page_num,
        page_index_base=0,
        source_page_id=source_page_id,
        used=used,
        evidence_role="primary",
        score=1.0,
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


def _gold(question_id: str, *, canonical_answer: object, answer_type: str, page_ids: list[str]) -> dict:
    source_sets = []
    if page_ids:
        source_sets.append(
            {
                "source_set_id": str(uuid4()),
                "is_primary": True,
                "page_ids": page_ids,
            }
        )
    return {
        "question_id": question_id,
        "canonical_answer": canonical_answer,
        "answer_type": answer_type,
        "route_hint": "article_lookup",
        "source_sets": source_sets,
    }


def test_strict_gate_invalid_source_page_id_forces_question_overall_zero() -> None:
    metrics = aggregate_run(
        _eval_run(),
        [
            _response(
                question_id="q1",
                answer="A",
                answer_type="free_text",
                sources=[_source(page_num=5, source_page_id="doc_2")],
            )
        ],
        [_gold("q1", canonical_answer="A", answer_type="free_text", page_ids=["doc_5"])],
        scoring_policy_catalog=_catalog(),
        strict_contract_mode=True,
    )

    question_metric = metrics["question_metrics"][0]
    assert question_metric["competition_contract_valid"] is False
    assert question_metric["prediction_valid_for_competition"] is False
    assert question_metric["overall_score"] == 0.0
    assert "source_page_id:sources[0].source_page_id_not_canonical" in question_metric["blocking_contract_failures"]
    assert "invalid_source_page_id" in question_metric["invalid_reason_tags"]


def test_strict_gate_invalid_answer_schema_marks_prediction_invalid() -> None:
    metrics = aggregate_run(
        _eval_run(),
        [
            _response(
                question_id="q1",
                answer="yes",
                answer_type="boolean",
                sources=[_source(page_num=0, source_page_id="doc_0")],
            )
        ],
        [_gold("q1", canonical_answer=True, answer_type="boolean", page_ids=["doc_0"])],
        scoring_policy_catalog=_catalog(),
        strict_contract_mode=True,
    )
    question_metric = metrics["question_metrics"][0]
    assert question_metric["competition_contract_valid"] is False
    assert question_metric["overall_score"] == 0.0
    assert "invalid_answer_schema" in question_metric["invalid_reason_tags"]


def test_strict_gate_invalid_telemetry_contract_marks_prediction_invalid() -> None:
    metrics = aggregate_run(
        _eval_run(),
        [
            _response(
                question_id="q1",
                answer="A",
                answer_type="free_text",
                sources=[_source(page_num=0, source_page_id="doc_0")],
                telemetry=_telemetry(ttft_ms=900, total_response_ms=100, complete=True),
            )
        ],
        [_gold("q1", canonical_answer="A", answer_type="free_text", page_ids=["doc_0"])],
        scoring_policy_catalog=_catalog(),
        strict_contract_mode=True,
    )
    question_metric = metrics["question_metrics"][0]
    assert question_metric["competition_contract_valid"] is False
    assert question_metric["overall_score"] == 0.0
    assert "invalid_telemetry_contract" in question_metric["invalid_reason_tags"]


def test_strict_gate_invalid_no_answer_form_marks_prediction_invalid() -> None:
    metrics = aggregate_run(
        _eval_run(),
        [
            _response(
                question_id="q1",
                answer=12,
                answer_type="number",
                abstained=True,
                confidence=0.3,
                sources=[_source(page_num=0, source_page_id="doc_0")],
            )
        ],
        [_gold("q1", canonical_answer=None, answer_type="number", page_ids=[])],
        scoring_policy_catalog=_catalog(),
        strict_contract_mode=True,
    )
    question_metric = metrics["question_metrics"][0]
    assert question_metric["competition_contract_valid"] is False
    assert question_metric["overall_score"] == 0.0
    assert "invalid_no_answer_form" in question_metric["invalid_reason_tags"]


def test_strict_gate_valid_prediction_passes_and_run_metrics_include_blocking_summary() -> None:
    predictions = [
        _response(
            question_id="q-valid",
            answer="A",
            answer_type="free_text",
            sources=[_source(page_num=0, source_page_id="doc_0")],
        ),
        _response(
            question_id="q-invalid-source",
            answer="B",
            answer_type="free_text",
            sources=[_source(page_num=4, source_page_id="doc_2")],
        ),
        _response(
            question_id="q-invalid-telemetry",
            answer="C",
            answer_type="free_text",
            sources=[_source(page_num=1, source_page_id="doc_1")],
            telemetry=_telemetry(ttft_ms=1000, total_response_ms=200, complete=True),
        ),
    ]
    gold = [
        _gold("q-valid", canonical_answer="A", answer_type="free_text", page_ids=["doc_0"]),
        _gold("q-invalid-source", canonical_answer="B", answer_type="free_text", page_ids=["doc_4"]),
        _gold("q-invalid-telemetry", canonical_answer="C", answer_type="free_text", page_ids=["doc_1"]),
    ]
    metrics = aggregate_run(
        _eval_run(),
        predictions,
        gold,
        scoring_policy_catalog=_catalog(),
        strict_contract_mode=True,
    )

    assert metrics["strict_contract_mode"] is True
    assert metrics["competition_contract_pass_rate"] == 1 / 3
    assert metrics["invalid_prediction_count"] == 2
    assert metrics["competition_gate_passed"] is False
    assert metrics["overall_score"] < metrics["overall_score_raw"]
    assert "source_page_id:sources[0].source_page_id_not_canonical" in metrics["blocking_contract_failure_histogram"]
    assert "telemetry:total_response_ms_below_ttft_ms" in metrics["blocking_contract_failure_histogram"]

    summary = metrics["scorer_summary"]["markdown"]
    assert "strict_contract_mode" in summary
    assert "invalid_prediction_count" in summary
    assert "Top Blocking Contract Failures" in summary
