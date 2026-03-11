#!/usr/bin/env python3
"""Run scorer regression tests and write a readable summary artifact."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.contracts import EvalRun, PageRef, QueryResponse, Telemetry  # noqa: E402
from services.eval.engine import aggregate_run  # noqa: E402

REPORT_PATH = ROOT / "reports" / "scorer_regression_summary.md"


def _display_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _run_regression_tests() -> int:
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "tests/scorer_regression",
        "-q",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = "apps/api/src:."
    process = subprocess.run(cmd, cwd=str(ROOT), env=env)
    return int(process.returncode)


def _telemetry(*, ttft_ms: int, complete: bool) -> Telemetry:
    now = datetime.now(timezone.utc)
    return Telemetry(
        request_started_at=now,
        first_token_at=now,
        completed_at=now,
        ttft_ms=ttft_ms,
        total_response_ms=ttft_ms + 100,
        time_per_output_token_ms=1.0,
        input_tokens=16,
        output_tokens=8,
        model_name="scorer-regression-fixture",
        route_name="article_lookup",
        judge_model_name=None,
        search_profile="default",
        telemetry_complete=complete,
        trace_id=f"trace-{uuid4()}",
    )


def _fixture_summary_markdown() -> str:
    eval_run = EvalRun(
        eval_run_id=str(uuid4()),
        run_id=str(uuid4()),
        gold_dataset_id=str(uuid4()),
        scoring_policy_version="contest_v2026_public_rules_v1",
        judge_policy_version="judge_v1",
        status="completed",
        metrics={},
    )
    predictions = [
        QueryResponse(
            question_id="q-1",
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
                    page_num=0,
                    page_index_base=0,
                    source_page_id="doc_0",
                    used=True,
                    evidence_role="primary",
                    score=1.0,
                )
            ],
            telemetry=_telemetry(ttft_ms=900, complete=True),
            debug=None,
        ),
        QueryResponse(
            question_id="q-2",
            answer="No confident answer could be derived from the indexed corpus with current evidence.",
            answer_normalized=None,
            answer_type="free_text",
            confidence=0.0,
            route_name="history_lineage",
            abstained=True,
            sources=[],
            telemetry=_telemetry(ttft_ms=900, complete=True),
            debug=None,
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
            "canonical_answer": None,
            "answer_type": "free_text",
            "route_hint": "history_lineage",
            "source_sets": [],
        },
    ]
    catalog = {
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
    metrics = aggregate_run(
        eval_run,
        predictions,
        gold_questions,
        scoring_policy_catalog=catalog,
    )
    return str((metrics.get("scorer_summary") or {}).get("markdown", "")).strip()


def _write_summary() -> None:
    summary = _fixture_summary_markdown()
    timestamp = datetime.now(timezone.utc).isoformat()
    command = f"{_display_repo_path(ROOT / '.venv' / 'bin' / 'python')} scripts/scorer_regression.py"
    body = "\n".join(
        [
            "# Scorer Regression Artifact",
            "",
            f"- generated_at_utc: `{timestamp}`",
            f"- command: `{command}`",
            "",
            summary,
            "",
        ]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(body, encoding="utf-8")


def main() -> int:
    rc = _run_regression_tests()
    if rc != 0:
        return rc
    _write_summary()
    print(f"[ok] scorer regression passed; summary written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
