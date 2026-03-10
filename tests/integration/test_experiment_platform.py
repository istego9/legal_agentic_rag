from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import runtime_pg  # noqa: E402
from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.state import store  # noqa: E402


def _assert_run_metadata(run_payload: dict) -> None:
    metrics = run_payload.get("metrics", {})
    assert isinstance(metrics, dict)
    run_metadata = metrics.get("run_metadata", {})
    assert isinstance(run_metadata, dict)
    assert run_metadata.get("metadata_version") == "run_metadata.v1"
    assert run_metadata.get("profile_id")
    assert run_metadata.get("stage_type") in {"proxy", "full"}
    assert run_metadata.get("baseline_experiment_run_id")
    assert isinstance(run_metadata.get("sample_size"), int) and run_metadata["sample_size"] > 0
    assert isinstance(run_metadata.get("question_count"), int) and run_metadata["question_count"] > 0
    assert run_metadata["sample_size"] == run_metadata["question_count"]
    assert run_metadata.get("qa_run_id")
    assert run_metadata.get("eval_run_id")
    assert run_metadata.get("run_report_artifact_url")
    policy_versions = run_metadata.get("policy_versions", {})
    assert isinstance(policy_versions, dict)
    assert policy_versions.get("scoring_policy_version")
    summary = run_metadata.get("metrics_summary", {})
    assert isinstance(summary, dict)
    for field in (
        "overall_score",
        "answer_score_mean",
        "grounding_score_mean",
        "telemetry_factor",
        "ttft_factor",
    ):
        assert isinstance(summary.get(field), (float, int))
    request = run_metadata.get("request", {})
    assert isinstance(request, dict)
    assert request.get("stage_mode")
    assert request.get("actor")
    assert isinstance(request.get("agent_mode"), bool)


def _force_high_baseline_score(experiment_run_id: str, experiment_id: str) -> None:
    forced_metrics = {
        "answer_score_mean": 1.0,
        "grounding_score_mean": 1.2,
        "telemetry_factor": 1.0,
        "ttft_factor": 1.0,
        "overall_score": 1.2,
    }
    if runtime_pg.enabled():
        runtime_pg.upsert_exp_score(
            experiment_run_id,
            experiment_id,
            "full",
            forced_metrics,
            payload=forced_metrics,
        )
        return
    store.upsert_exp_score(experiment_run_id, experiment_id, "full", forced_metrics)


def test_experiment_platform_flow() -> None:
    project_id = str(uuid4())
    dataset_id = str(uuid4())
    client = TestClient(app)

    imported = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={
            "project_id": project_id,
            "questions": [
                {
                    "id": "q-exp-1",
                    "question": "What is article 1?",
                    "answer_type": "free_text",
                },
                {
                    "id": "q-exp-2",
                    "question": "What is article 2?",
                    "answer_type": "free_text",
                },
                {
                    "id": "q-exp-3",
                    "question": "What is article 3?",
                    "answer_type": "free_text",
                },
                {
                    "id": "q-exp-4",
                    "question": "What is article 4?",
                    "answer_type": "free_text",
                },
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["upserted"] == 4

    created_gold_ds = client.post(
        "/v1/gold/datasets",
        json={
            "project_id": project_id,
            "name": "exp-gold",
            "version": "1.0.0",
        },
    )
    assert created_gold_ds.status_code == 200
    gold_dataset_id = created_gold_ds.json()["gold_dataset_id"]

    for qid in ["q-exp-1", "q-exp-2", "q-exp-3", "q-exp-4"]:
        created_q = client.post(
            f"/v1/gold/datasets/{gold_dataset_id}/questions",
            json={
                "question_id": qid,
                "canonical_answer": None,
                "answer_type": "free_text",
                "source_sets": [
                    {
                        "source_set_id": str(uuid4()),
                        "is_primary": True,
                        "page_ids": ["sample_0"],
                    }
                ],
            },
        )
        assert created_q.status_code == 200

    created_policy_v2 = client.post(
        "/v1/config/scoring-policies",
        json={
            "policy_version": "contest_v2026_public_rules_v2",
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
    )
    assert created_policy_v2.status_code == 200

    policy_registry_before = client.get("/v1/config/policy-registry")
    assert policy_registry_before.status_code == 200
    assert "policies" in policy_registry_before.json()

    configured_registry = client.post(
        "/v1/config/policy-registry",
        json={
            "policies": {
                "scoring": {
                    "available_versions": [
                        "contest_v2026_public_rules_v1",
                        "contest_v2026_public_rules_v2",
                    ],
                    "active_version": "contest_v2026_public_rules_v2",
                    "fallback_version": "contest_v2026_public_rules_v1",
                }
            }
        },
    )
    assert configured_registry.status_code == 200

    created_profile = client.post(
        "/v1/experiments/profiles",
        json={
            "name": "local-profile",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "gold_dataset_id": gold_dataset_id,
            "endpoint_target": "local",
            "active": True,
        },
    )
    assert created_profile.status_code == 200
    profile_id = created_profile.json()["profile_id"]

    created_experiment = client.post(
        "/v1/experiments",
        json={
            "name": "exp-v1",
            "profile_id": profile_id,
            "gold_dataset_id": gold_dataset_id,
        },
    )
    assert created_experiment.status_code == 200
    experiment_id = created_experiment.json()["experiment_id"]

    missing_baseline_proxy = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert missing_baseline_proxy.status_code == 400
    assert "baseline compare is required for proxy runs" in str(missing_baseline_proxy.json().get("detail"))

    baseline_seed = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "full",
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert baseline_seed.status_code == 202
    baseline_run_id = baseline_seed.json()["experiment_run_id"]

    baseline_status = client.get(f"/v1/experiments/runs/{baseline_run_id}")
    assert baseline_status.status_code == 200
    assert baseline_status.json()["status"] == "completed"
    assert baseline_status.json().get("baseline_experiment_run_id") == baseline_run_id
    assert baseline_status.json()["metrics"]["promotion_decision"]["status"] == "accepted"
    assert baseline_status.json()["metrics"]["promotion_decision"]["reason"] == "baseline_seed_no_compare"
    _assert_run_metadata(baseline_status.json())

    missing_baseline_proxy_after_full = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert missing_baseline_proxy_after_full.status_code == 400
    assert "baseline compare is required for proxy runs" in str(
        missing_baseline_proxy_after_full.json().get("detail")
    )

    first_run = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "auto",
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert first_run.status_code == 202
    first_run_id = first_run.json()["experiment_run_id"]

    run_status = client.get(f"/v1/experiments/runs/{first_run_id}")
    assert run_status.status_code == 200
    assert run_status.json()["status"] in {"completed", "gated_rejected"}
    _assert_run_metadata(run_status.json())
    run_metrics = run_status.json().get("metrics", {})
    policy_versions = run_metrics.get("policy_versions", {})
    assert policy_versions.get("scoring_policy_version") == "contest_v2026_public_rules_v2"

    eval_run_id = run_status.json().get("eval_run_id")
    assert isinstance(eval_run_id, str) and eval_run_id
    eval_run = client.get(f"/v1/eval/runs/{eval_run_id}")
    assert eval_run.status_code == 200
    assert eval_run.json()["scoring_policy_version"] == "contest_v2026_public_rules_v2"

    analysis = client.get(f"/v1/experiments/runs/{first_run_id}/analysis")
    assert analysis.status_code == 200
    assert "score" in analysis.json()

    _force_high_baseline_score(baseline_run_id, experiment_id)

    second_run = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": baseline_run_id,
            "proxy_sample_size": 1,
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert second_run.status_code == 202
    second_run_id = second_run.json()["experiment_run_id"]
    second_status = client.get(f"/v1/experiments/runs/{second_run_id}")
    assert second_status.status_code == 200
    assert second_status.json()["status"] == "gated_rejected"
    second_gate = (second_status.json().get("metrics", {}) or {}).get("gate", {})
    assert second_gate.get("passed") is False
    assert isinstance(second_gate.get("failed_rules"), list) and second_gate["failed_rules"]
    assert second_gate.get("telemetry_completeness_gate", {}).get("required") is True
    assert second_status.json()["metrics"]["promotion_decision"]["status"] == "rejected"
    _assert_run_metadata(second_status.json())

    second_run_repeat = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": baseline_run_id,
            "proxy_sample_size": 1,
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert second_run_repeat.status_code == 202
    assert second_run_repeat.json()["experiment_run_id"] == second_run_id

    idem_first = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": baseline_run_id,
            "proxy_sample_size": 2,
            "actor": "test",
            "agent_mode": True,
            "idempotency_key": "idem-key-1",
        },
    )
    idem_second = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": baseline_run_id,
            "proxy_sample_size": 2,
            "actor": "test",
            "agent_mode": True,
            "idempotency_key": "idem-key-1",
        },
    )
    assert idem_first.status_code == 202
    assert idem_second.status_code == 202
    assert idem_first.json()["experiment_run_id"] == idem_second.json()["experiment_run_id"]

    idem_mismatch = client.post(
        f"/v1/experiments/{experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": baseline_run_id,
            "proxy_sample_size": 2,
            "actor": "another-actor",
            "agent_mode": True,
            "idempotency_key": "idem-key-1",
        },
    )
    assert idem_mismatch.status_code == 400
    assert "idempotency key metadata mismatch" in str(idem_mismatch.json().get("detail"))

    leaderboard = client.get("/v1/experiments/leaderboard?limit=10")
    assert leaderboard.status_code == 200
    assert "items" in leaderboard.json()

    compared = client.post(
        "/v1/experiments/compare",
        json={
            "left_experiment_run_id": first_run_id,
            "right_experiment_run_id": second_run_id,
        },
    )
    assert compared.status_code == 200
    compare_payload = compared.json()
    assert "metric_deltas" in compare_payload
    assert "compare_slices" in compare_payload
    assert "value_report" in compare_payload
    compare_slices = compare_payload["compare_slices"]
    assert compare_slices.get("slice_version") == "compare_slices.v1"
    by_answer_type = compare_slices.get("by_answer_type", [])
    by_route_family = compare_slices.get("by_route_family", [])
    assert isinstance(by_answer_type, list)
    assert isinstance(by_route_family, list)
    assert [row["answer_type"] for row in by_answer_type] == sorted(row["answer_type"] for row in by_answer_type)
    assert [row["route_family"] for row in by_route_family] == sorted(row["route_family"] for row in by_route_family)
    assert compare_payload["value_report"]["report_version"] == "value_report.v1"
    assert isinstance(compare_payload["value_report"]["by_route_family"], list)
    assert isinstance(compare_payload["value_report"]["by_answerability"], list)

    fallback_profile = client.post(
        "/v1/experiments/profiles",
        json={
            "name": "fallback-profile",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "gold_dataset_id": gold_dataset_id,
            "endpoint_target": "local",
            "active": True,
            "runtime_policy": {
                "use_llm": False,
                "max_candidate_pages": 8,
                "max_context_paragraphs": 8,
                "page_index_base_export": 0,
                "scoring_policy_version": "unknown_policy_v9",
                "allow_dense_fallback": True,
                "return_debug_trace": False,
            },
        },
    )
    assert fallback_profile.status_code == 200
    fallback_profile_id = fallback_profile.json()["profile_id"]

    fallback_experiment = client.post(
        "/v1/experiments",
        json={
            "name": "exp-fallback",
            "profile_id": fallback_profile_id,
            "gold_dataset_id": gold_dataset_id,
        },
    )
    assert fallback_experiment.status_code == 200
    fallback_experiment_id = fallback_experiment.json()["experiment_id"]

    fallback_run = client.post(
        f"/v1/experiments/{fallback_experiment_id}/runs",
        json={
            "stage_mode": "full",
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert fallback_run.status_code == 202
    fallback_seed_run_id = fallback_run.json()["experiment_run_id"]
    fallback_seed_status = client.get(f"/v1/experiments/runs/{fallback_seed_run_id}")
    assert fallback_seed_status.status_code == 200
    _assert_run_metadata(fallback_seed_status.json())

    fallback_run = client.post(
        f"/v1/experiments/{fallback_experiment_id}/runs",
        json={
            "stage_mode": "proxy",
            "baseline_experiment_run_id": fallback_seed_run_id,
            "actor": "test",
            "agent_mode": True,
        },
    )
    assert fallback_run.status_code == 202
    fallback_run_id = fallback_run.json()["experiment_run_id"]
    fallback_status = client.get(f"/v1/experiments/runs/{fallback_run_id}")
    assert fallback_status.status_code == 200
    _assert_run_metadata(fallback_status.json())
    fallback_metrics = fallback_status.json().get("metrics", {})
    fallback_versions = fallback_metrics.get("policy_versions", {})
    assert fallback_versions.get("scoring_policy_version") == "contest_v2026_public_rules_v1"

    fallback_eval_run_id = fallback_status.json().get("eval_run_id")
    assert isinstance(fallback_eval_run_id, str) and fallback_eval_run_id
    fallback_eval = client.get(f"/v1/eval/runs/{fallback_eval_run_id}")
    assert fallback_eval.status_code == 200
    assert fallback_eval.json()["scoring_policy_version"] == "contest_v2026_public_rules_v1"


def test_policy_registry_incremental_multi_family_update_keeps_existing_overrides() -> None:
    client = TestClient(app)

    created_policy_v2 = client.post(
        "/v1/config/scoring-policies",
        json={
            "policy_version": "contest_v2026_public_rules_v2",
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
    )
    assert created_policy_v2.status_code == 200

    retrieval_override = client.post(
        "/v1/config/policy-registry",
        json={
            "policies": {
                "retrieval": {
                    "available_versions": ["retrieval_regression_v1", "retrieval_regression_v2"],
                    "active_version": "retrieval_regression_v2",
                    "fallback_version": "retrieval_regression_v1",
                }
            }
        },
    )
    assert retrieval_override.status_code == 200

    scoring_patch_shorthand = client.post(
        "/v1/config/policy-registry",
        json={
            "scoring": {
                "available_versions": [
                    "contest_v2026_public_rules_v1",
                    "contest_v2026_public_rules_v2",
                ],
                "active_version": "contest_v2026_public_rules_v2",
                "fallback_version": "contest_v2026_public_rules_v1",
            }
        },
    )
    assert scoring_patch_shorthand.status_code == 200

    registry = client.get("/v1/config/policy-registry")
    assert registry.status_code == 200
    policies = registry.json().get("policies", {})
    retrieval = policies.get("retrieval", {})
    assert retrieval.get("active_version") == "retrieval_regression_v2"
    assert retrieval.get("fallback_version") == "retrieval_regression_v1"
    assert "retrieval_regression_v1" in retrieval.get("available_versions", [])
    assert "retrieval_regression_v2" in retrieval.get("available_versions", [])

    scoring = policies.get("scoring", {})
    assert scoring.get("active_version") == "contest_v2026_public_rules_v2"
    assert scoring.get("fallback_version") == "contest_v2026_public_rules_v1"
