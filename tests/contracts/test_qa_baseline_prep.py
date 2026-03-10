from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "qa_baseline_prep.py"


def load_module():
    spec = importlib.util.spec_from_file_location("qa_baseline_prep", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _public_question_map(module) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for spec in module.PUBLIC_SLICE_SPEC:
        mapping[spec["id"]] = {
            "id": spec["id"],
            "question": f"Question for {spec['id']}",
            "answer_type": spec["answer_type"],
        }
    return mapping


def test_fixed_slice_artifact_contains_public_and_manual_items() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))

    assert artifact["artifact_version"] == module.SLICE_ARTIFACT_VERSION
    assert artifact["slice_id"] == module.SLICE_ID
    assert artifact["public_item_count"] == len(module.PUBLIC_SLICE_SPEC)
    assert artifact["manual_no_answer_count"] == len(module.MANUAL_NO_ANSWER_SPEC)
    assert artifact["item_count"] == len(module.PUBLIC_SLICE_SPEC) + len(module.MANUAL_NO_ANSWER_SPEC)
    assert any(item["id"] == "manual-no-answer-001" for item in artifact["items"])


def test_dataset_import_payload_covers_manual_no_answer_items() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))

    payload = module.build_dataset_import_payload(artifact)

    imported_ids = [item["id"] for item in payload["questions"]]
    assert imported_ids[0] == module.PUBLIC_SLICE_SPEC[0]["id"]
    assert imported_ids[-1] == module.MANUAL_NO_ANSWER_SPEC[-1]["id"]
    assert len(imported_ids) == artifact["item_count"]


def test_b0_request_pack_forces_none_sources_summary() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))

    pack = module.build_b0_request_pack(artifact)

    assert pack["baseline_id"] == "B0"
    assert pack["item_count"] == artifact["item_count"]
    assert all(item["sources_summary_token"] == "none" for item in pack["items"])
    assert "question-only" in pack["items"][0]["system_prompt"]


def test_b1_template_marks_context_as_pending() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))

    pack = module.build_b1_request_pack_template(artifact, top_k=4)

    assert pack["baseline_id"] == "B1"
    assert pack["items"][0]["naive_context"]["top_k"] == 4
    assert pack["items"][0]["naive_context"]["status"] == "build_with_live_api"
    assert pack["items"][0]["sources_summary_token"] == "naive_context:pending"


def test_normalize_model_results_flags_manual_no_answer_hallucination() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))

    raw_payload = {
        "items": [
            {
                "id": item["id"],
                "answer": False if item["answer_type"] == "boolean" else "filled",
                "abstained": False,
                "sources_summary": "none" if item["id"] != "manual-no-answer-001" else "none",
                "short_failure_note": "",
            }
            for item in artifact["items"]
        ]
    }

    normalized = module.normalize_model_result_artifact(
        artifact,
        baseline_id="B0",
        raw_payload=raw_payload,
    )

    by_id = {item["id"]: item for item in normalized["items"]}
    assert by_id["manual-no-answer-001"]["short_failure_note"] == "manual_no_answer_should_abstain"
    assert by_id[module.PUBLIC_SLICE_SPEC[0]["id"]]["short_failure_note"] == ""


def test_normalize_b2_response_uses_runtime_used_sources() -> None:
    module = load_module()
    artifact = module.build_fixed_slice_artifact(_public_question_map(module))
    responses = {}
    for item in artifact["items"]:
        item_id = item["id"]
        responses[item_id] = {
            "question_id": item_id,
            "answer": True if item["answer_type"] == "boolean" else "answer",
            "answer_normalized": "normalized",
            "abstained": False,
            "sources": [
                {
                    "source_page_id": "law_1",
                    "used": True,
                },
                {
                    "source_page_id": "law_2",
                    "used": False,
                },
            ],
        }

    normalized = module.normalize_b2_response_artifact(artifact, responses_by_id=responses)

    first_row = normalized["items"][0]
    assert first_row["baseline_id"] == "B2"
    assert first_row["sources_summary"] == "runtime_used:law_1"
    assert first_row["answer_normalized"] == "normalized"
