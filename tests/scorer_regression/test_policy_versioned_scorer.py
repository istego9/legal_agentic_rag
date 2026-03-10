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
from services.eval.engine import (  # noqa: E402
    aggregate_run,
    resolve_scoring_policy_spec,
)


def _telemetry(*, ttft_ms: int, complete: bool) -> Telemetry:
    now = datetime(2026, 3, 6, tzinfo=timezone.utc)
    return Telemetry(
        request_started_at=now,
        first_token_at=now,
        completed_at=now,
        ttft_ms=ttft_ms,
        total_response_ms=ttft_ms + 100,
        time_per_output_token_ms=1.0,
        input_tokens=16,
        output_tokens=8,
        model_name="test-model",
        route_name="article_lookup",
        judge_model_name=None,
        search_profile="default",
        telemetry_complete=complete,
        trace_id=str(uuid4()),
    )


def _response(
    *,
    question_id: str,
    answer: object,
    answer_type: str,
    route_name: str,
    source_page_ids: list[str],
    ttft_ms: int,
    telemetry_complete: bool = True,
    abstained: bool = False,
) -> QueryResponse:
    sources = [
        PageRef(
            project_id="proj-test",
            document_id="doc-test",
            pdf_id="doc",
            page_num=int(page_id.rsplit("_", 1)[-1]),
            page_index_base=0,
            source_page_id=page_id,
            used=True,
            evidence_role="primary",
            score=1.0,
        )
        for page_id in source_page_ids
    ]
    return QueryResponse(
        question_id=question_id,
        answer=answer,
        answer_normalized=None,
        answer_type=answer_type,
        confidence=1.0,
        route_name=route_name,
        abstained=abstained,
        sources=sources,
        telemetry=_telemetry(ttft_ms=ttft_ms, complete=telemetry_complete),
        debug=None,
    )


def _eval_run(scoring_policy_version: str) -> EvalRun:
    return EvalRun(
        eval_run_id=str(uuid4()),
        run_id=str(uuid4()),
        gold_dataset_id=str(uuid4()),
        scoring_policy_version=scoring_policy_version,
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
        },
        "contest_v2026_public_rules_strict": {
            "policy_version": "contest_v2026_public_rules_strict",
            "policy_type": "contest_emulation",
            "beta": 1.0,
            "ttft_curve": {
                "mode": "piecewise_linear_avg_ttft",
                "best_seconds": 0.5,
                "best_factor": 1.0,
                "worst_seconds": 2.0,
                "worst_factor": 0.5,
            },
            "telemetry_policy": "run_level_factor",
        },
        "contest_v2026_public_rules_all_or_nothing": {
            "policy_version": "contest_v2026_public_rules_all_or_nothing",
            "policy_type": "contest_emulation",
            "beta": 2.5,
            "ttft_curve": {
                "mode": "piecewise_linear_avg_ttft",
                "best_seconds": 1.0,
                "best_factor": 1.05,
                "worst_seconds": 5.0,
                "worst_factor": 0.85,
            },
            "telemetry_policy": "all_or_nothing",
        },
    }


def test_resolve_scoring_policy_spec_fallback_to_default() -> None:
    spec = resolve_scoring_policy_spec("unknown_policy_v9", catalog=_catalog())
    assert spec["requested_policy_version"] == "unknown_policy_v9"
    assert spec["resolved_policy_version"] == "contest_v2026_public_rules_v1"
    assert spec["used_fallback"] is True
    assert spec["resolution_rule"] == "default_policy_for_unknown_requested_version"


def test_aggregate_run_uses_policy_beta_and_ttft_curve() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            route_name="article_lookup",
            source_page_ids=["doc_0"],
            ttft_ms=3000,
            telemetry_complete=True,
        )
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["doc_0", "doc_1"],
                }
            ],
        }
    ]
    metrics_v1 = aggregate_run(
        _eval_run("contest_v2026_public_rules_v1"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )
    metrics_strict = aggregate_run(
        _eval_run("contest_v2026_public_rules_strict"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics_v1["grounding_score_mean"] != metrics_strict["grounding_score_mean"]
    assert metrics_v1["ttft_factor"] != metrics_strict["ttft_factor"]
    assert metrics_v1["scoring_policy"]["resolved_policy_version"] == "contest_v2026_public_rules_v1"
    assert metrics_strict["scoring_policy"]["resolved_policy_version"] == "contest_v2026_public_rules_strict"


def test_aggregate_run_respects_all_or_nothing_telemetry_policy() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            route_name="article_lookup",
            source_page_ids=["doc_0"],
            ttft_ms=1000,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-2",
            answer=None,
            answer_type="boolean",
            route_name="history_lineage",
            source_page_ids=[],
            ttft_ms=1000,
            telemetry_complete=False,
            abstained=True,
        ),
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["doc_0"],
                }
            ],
        },
        {
            "question_id": "q-2",
            "canonical_answer": None,
            "answer_type": "boolean",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    metrics_run_level = aggregate_run(
        _eval_run("contest_v2026_public_rules_v1"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )
    metrics_all_or_nothing = aggregate_run(
        _eval_run("contest_v2026_public_rules_all_or_nothing"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics_run_level["telemetry_factor"] == 0.5
    assert metrics_all_or_nothing["telemetry_factor"] == 0.0


def test_aggregate_run_emits_stable_slices_by_type_and_family() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            route_name="article_lookup",
            source_page_ids=["doc_0"],
            ttft_ms=1200,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-2",
            answer=None,
            answer_type="boolean",
            route_name="history_lineage",
            source_page_ids=[],
            ttft_ms=900,
            telemetry_complete=True,
            abstained=True,
        ),
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["doc_0"],
                }
            ],
        },
        {
            "question_id": "q-2",
            "canonical_answer": None,
            "answer_type": "boolean",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    metrics = aggregate_run(
        _eval_run("contest_v2026_public_rules_v1"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    slices = metrics["slices"]
    assert slices["slice_version"] == "eval_metric_slices.v1"
    assert [row["answer_type"] for row in slices["by_answer_type"]] == ["boolean", "free_text"]
    assert [row["route_family"] for row in slices["by_route_family"]] == [
        "article_lookup",
        "history_lineage",
    ]


def test_aggregate_run_emits_source_and_no_answer_metrics() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            route_name="article_lookup",
            source_page_ids=["doc_0", "doc_2"],
            ttft_ms=1200,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-2",
            answer=None,
            answer_type="boolean",
            route_name="history_lineage",
            source_page_ids=[],
            ttft_ms=900,
            telemetry_complete=True,
            abstained=True,
        ),
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["doc_0", "doc_1"],
                }
            ],
        },
        {
            "question_id": "q-2",
            "canonical_answer": None,
            "answer_type": "boolean",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    metrics = aggregate_run(
        _eval_run("contest_v2026_public_rules_v1"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
    )

    assert metrics["source_precision"] > 0.0
    assert metrics["source_recall"] > 0.0
    assert metrics["source_f_beta"] > 0.0
    assert metrics["no_answer_precision"] == 1.0
    assert metrics["no_answer_recall"] == 1.0
    assert metrics["S"] == metrics["answer_score_mean"]
    assert metrics["G"] == metrics["grounding_score_mean"]
    assert metrics["T"] == metrics["telemetry_factor"]
    assert metrics["F"] == metrics["ttft_factor"]
    assert len(metrics["question_metrics"]) == 2


def test_aggregate_run_emits_value_report_with_context_cohorts() -> None:
    predictions = [
        _response(
            question_id="q-1",
            answer="A",
            answer_type="free_text",
            route_name="article_lookup",
            source_page_ids=["doc_0"],
            ttft_ms=800,
            telemetry_complete=True,
        ),
        _response(
            question_id="q-2",
            answer=None,
            answer_type="boolean",
            route_name="history_lineage",
            source_page_ids=[],
            ttft_ms=900,
            telemetry_complete=True,
            abstained=True,
        ),
    ]
    gold_questions = [
        {
            "question_id": "q-1",
            "canonical_answer": "A",
            "answer_type": "free_text",
            "route_hint": "article_lookup",
            "source_sets": [
                {
                    "source_set_id": str(uuid4()),
                    "is_primary": True,
                    "page_ids": ["doc_0"],
                }
            ],
        },
        {
            "question_id": "q-2",
            "canonical_answer": None,
            "answer_type": "boolean",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    metrics = aggregate_run(
        _eval_run("contest_v2026_public_rules_v1"),
        predictions,
        gold_questions,
        scoring_policy_catalog=_catalog(),
        question_context_by_id={
            "q-1": {
                "document_scope": "single-doc",
                "corpus_domain": "law",
                "temporal_scope": "general",
                "retrieval_profile_id": "article_lookup_recall_v2",
                "candidate_count": 4,
                "used_page_count": 1,
            },
            "q-2": {
                "document_scope": "single-doc",
                "corpus_domain": "law",
                "temporal_scope": "history-lineage",
                "retrieval_profile_id": "history_lineage_graph_v1",
                "candidate_count": 3,
                "used_page_count": 0,
            },
        },
    )

    assert metrics["value_report"]["report_version"] == "value_report.v1"
    assert any(row["route_family"] == "article_lookup" for row in metrics["value_report"]["by_route_family"])
    assert any(row["answerability"] == "unanswerable" for row in metrics["value_report"]["by_answerability"])
