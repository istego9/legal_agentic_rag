from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_public100_triage as module  # noqa: E402


def test_build_triage_rows_marks_answerable_abstain_and_negative_routes() -> None:
    questions = {
        "q-answerable": {
            "id": "q-answerable",
            "question": "Under Article 8(1), is a person permitted to operate in the DIFC without being incorporated?",
            "answer_type": "boolean",
        },
        "q-negative": {
            "id": "q-negative",
            "question": "What Miranda rights warning was given to the accused?",
            "answer_type": "free_text",
        },
    }
    status_rows = [
        {
            "question_id": "q-answerable",
            "answer_type": "boolean",
            "route_name": "article_lookup",
            "success": True,
            "validation": {"competition_contract_valid": True},
            "abstained": True,
            "answer_is_null": True,
            "error": "",
        },
        {
            "question_id": "q-negative",
            "answer_type": "free_text",
            "route_name": "no_answer",
            "success": True,
            "validation": {"competition_contract_valid": True},
            "abstained": True,
            "answer_is_null": False,
            "error": "",
        },
    ]
    answers = {
        "q-answerable": {"question_id": "q-answerable", "answer": None, "telemetry": {"retrieval": {"retrieved_chunk_pages": []}, "model_name": "deterministic-router"}},
        "q-negative": {"question_id": "q-negative", "answer": "No confident answer", "telemetry": {"retrieval": {"retrieved_chunk_pages": []}, "model_name": "deterministic-router"}},
    }

    rows = module.build_triage_rows(
        questions_by_id=questions,
        status_rows=status_rows,
        answers_by_id=answers,
        run_id="run-1",
    )

    by_id = {row["question_id"]: row for row in rows}
    assert "answerable_vs_abstain_conflict" in by_id["q-answerable"]["failure_buckets"]
    assert "retrieval_error" in by_id["q-answerable"]["failure_buckets"]
    assert by_id["q-answerable"]["review_status_recommended"] == "needs_review"
    assert by_id["q-negative"]["triage_status"] == "expected_negative"
    assert by_id["q-negative"]["failure_buckets"] == []


def test_build_failure_taxonomy_counts_required_buckets() -> None:
    rows = [
        {"question_id": "q1", "failure_buckets": ["retrieval_error", "answerable_vs_abstain_conflict"]},
        {"question_id": "q2", "failure_buckets": ["compare_dimension_conflict"]},
    ]
    taxonomy = module.build_failure_taxonomy(rows)
    assert taxonomy["taxonomy_version"] == module.FAILURE_TAXONOMY_VERSION
    assert taxonomy["counts_by_bucket"]["retrieval_error"] == 1
    assert taxonomy["counts_by_bucket"]["answerable_vs_abstain_conflict"] == 1
    assert taxonomy["counts_by_bucket"]["compare_dimension_conflict"] == 1
    assert taxonomy["counts_by_bucket"]["route_error"] == 0


def test_main_writes_triage_artifacts(tmp_path: Path) -> None:
    artifact_root = tmp_path / "baseline"
    artifact_root.mkdir(parents=True)
    (artifact_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "run-1"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_root / "question_status.jsonl").write_text(
        json.dumps(
            {
                "question_id": "q-answerable",
                "answer_type": "boolean",
                "route_name": "article_lookup",
                "success": True,
                "validation": {"competition_contract_valid": True},
                "abstained": True,
                "answer_is_null": True,
                "error": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_root / "submission.json").write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "question_id": "q-answerable",
                        "answer": None,
                        "telemetry": {"retrieval": {"retrieved_chunk_pages": []}, "model_name": "deterministic-router"},
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(
        json.dumps(
            [
                {
                    "id": "q-answerable",
                    "question": "Under Article 8(1), is a person permitted to operate in the DIFC without being incorporated?",
                    "answer_type": "boolean",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    rc = module.main(["--artifact-root", str(artifact_root), "--questions", str(questions_path), "--no-tracked-truth"])
    assert rc == 0
    assert (artifact_root / "triage_summary.md").exists()
    assert (artifact_root / "triage_queue.jsonl").exists()
    assert (artifact_root / "failure_taxonomy.json").exists()
    queue_rows = [
        json.loads(line)
        for line in (artifact_root / "triage_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(queue_rows) == 1
    assert queue_rows[0]["review_priority_rank"] == 1
