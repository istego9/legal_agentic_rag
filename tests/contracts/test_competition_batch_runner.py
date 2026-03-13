from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
SCRIPT_PATH = ROOT / "scripts" / "competition_batch.py"

if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.state import store  # noqa: E402


def _load_module():
    spec = importlib.util.spec_from_file_location("competition_batch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _snapshot_store_state() -> dict:
    return copy.deepcopy(store.__dict__)


def _restore_store_state(state: dict) -> None:
    for key, value in state.items():
        setattr(store, key, value)


@pytest.fixture(autouse=True)
def _isolate_store_state() -> None:
    state = _snapshot_store_state()
    try:
        yield
    finally:
        _restore_store_state(state)


def _write_questions(path: Path) -> Path:
    payload = [
        {
            "id": "q-no-answer",
            "question": "No answer expected for this synthetic question?",
            "answer_type": "free_text",
            "route_hint": "no_answer",
        }
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_validate_command_fails_closed_on_malformed_submission(tmp_path: Path) -> None:
    module = _load_module()
    submission = tmp_path / "bad_submission.json"
    report = tmp_path / "bad_submission.validation.json"
    submission.write_text(
        json.dumps(
            {
                "architecture_summary": "",
                "answers": [{"question_id": "q1"}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    rc = module.main(
        [
            "validate",
            "--submission",
            str(submission),
            "--report",
            str(report),
        ]
    )
    assert rc == 1
    validation = json.loads(report.read_text(encoding="utf-8"))
    assert validation["valid"] is False
    assert validation["error_count"] > 0


def test_run_manifest_and_safe_rerun_controls(tmp_path: Path) -> None:
    module = _load_module()
    questions = _write_questions(tmp_path / "questions.json")
    output_dir = tmp_path / "run_output"

    rc_first = module.main(
        [
            "run",
            "--questions",
            str(questions),
            "--output",
            str(output_dir),
            "--project-id",
            "contract-test-project",
            "--dataset-id",
            "contract-test-dataset",
            "--limit",
            "1",
        ]
    )
    assert rc_first == 0
    assert (output_dir / "submission.json").exists()
    assert (output_dir / "run_manifest.json").exists()
    assert (output_dir / "question_status.jsonl").exists()
    assert (output_dir / "run_summary.md").exists()
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert "route_distribution" in manifest
    assert "abstain_summary" in manifest
    assert "latency_summary" in manifest
    assert "top_failure_buckets" in manifest
    run_summary = (output_dir / "run_summary.md").read_text(encoding="utf-8")
    assert "## Route Distribution" in run_summary
    assert "## Top Failure Buckets" in run_summary
    assert "## Latency Summary" in run_summary

    with pytest.raises(SystemExit):
        module.main(
            [
                "run",
                "--questions",
                str(questions),
                "--output",
                str(output_dir),
                "--project-id",
                "contract-test-project",
                "--dataset-id",
                "contract-test-dataset",
                "--limit",
                "1",
            ]
        )

    rc_resume = module.main(
        [
            "run",
            "--questions",
            str(questions),
            "--output",
            str(output_dir),
            "--project-id",
            "contract-test-project",
            "--dataset-id",
            "contract-test-dataset",
            "--limit",
            "1",
            "--resume",
        ]
    )
    assert rc_resume == 0
    resume_manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert resume_manifest["counts"]["resumed_from_cache_count"] == 1

    rc_overwrite = module.main(
        [
            "run",
            "--questions",
            str(questions),
            "--output",
            str(output_dir),
            "--project-id",
            "contract-test-project",
            "--dataset-id",
            "contract-test-dataset",
            "--limit",
            "1",
            "--overwrite",
        ]
    )
    assert rc_overwrite == 0
    overwrite_manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert overwrite_manifest["counts"]["resumed_from_cache_count"] == 0
