#!/usr/bin/env python3
"""Adjudicate and lock the pilot gold subset through the review console flow."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import corpus_pg, runtime_pg  # noqa: E402
from legal_rag_api.artifacts import ensure_artifact_dir  # noqa: E402
from legal_rag_api.contracts import CandidateAnswer, RuntimePolicy  # noqa: E402
from legal_rag_api.main import app  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.routers import qa as qa_router  # noqa: E402
from legal_rag_api.routers.qa import FREE_TEXT_NO_ANSWER  # noqa: E402
from legal_rag_api.state import load_persisted_state, store  # noqa: E402


DEFAULT_DOCUMENTS = ROOT / "datasets" / "official_fetch_2026-03-11" / "documents.zip"
DEFAULT_SUBSET = ROOT / "datasets" / "gold" / "pilot_gold_questions_v1.jsonl"
DEFAULT_OUTPUT_DIR = ensure_artifact_dir("gold", "pilot_gold_v1")
DEFAULT_GOLD_OUTPUT = ROOT / "datasets" / "gold" / "pilot_gold_v1.jsonl"
DEFAULT_REPORT_OUTPUT = ROOT / "reports" / "gold" / "pilot_gold_v1_report.md"
DEFAULT_DISAGREEMENT_OUTPUT = ROOT / "reports" / "gold" / "pilot_gold_disagreement_log_v1.jsonl"
PILOT_GOLD_VERSION = "pilot_gold_v1"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        payload = json.loads(raw)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(dict(row), ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _load_subset(path: Path) -> List[Dict[str, Any]]:
    rows = _read_jsonl(path)
    if len(rows) != 25:
        raise SystemExit(f"pilot subset must contain 25 rows, got {len(rows)}")
    return rows


def _runtime_policy_payload(*, max_candidate_pages: int, max_context_paragraphs: int, allow_dense_fallback: bool) -> Dict[str, Any]:
    return RuntimePolicy(
        use_llm=False,
        max_candidate_pages=max_candidate_pages,
        max_context_paragraphs=max_context_paragraphs,
        page_index_base_export=0,
        scoring_policy_version="contest_v2026_public_rules_v1",
        allow_dense_fallback=allow_dense_fallback,
        return_debug_trace=False,
    ).model_dump(mode="json")


def _canonical_source_page_ids(candidate: Mapping[str, Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for source in candidate.get("sources", []) if isinstance(candidate.get("sources"), list) else []:
        if not isinstance(source, Mapping):
            continue
        token = str(source.get("source_page_id") or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _normalized_answer(candidate: Mapping[str, Any]) -> str:
    answerability = str(candidate.get("answerability", "")).strip()
    answer = candidate.get("answer")
    if answerability == "abstain":
        return "__abstain__"
    if answer is None:
        return "__null__"
    if isinstance(answer, list):
        return json.dumps(answer, ensure_ascii=False, sort_keys=True)
    return str(answer).strip()


def _agreement_state(candidates: List[Mapping[str, Any]]) -> str:
    available = [
        candidate
        for candidate in candidates
        if str(candidate.get("candidate_kind", "")) in {"system", "strong_model", "challenger"}
        and str(candidate.get("support_status", "not_run")) != "unavailable"
    ]
    if not available:
        return "no_available_candidates"
    normalized = {_normalized_answer(candidate) for candidate in available}
    answerabilities = {str(candidate.get("answerability", "")).strip() for candidate in available}
    if len(normalized) == 1 and len(answerabilities) == 1:
        if "__abstain__" in normalized:
            return "all_abstain"
        return "consensus"
    answerable = [
        candidate
        for candidate in available
        if str(candidate.get("answerability", "")).strip() == "answerable" and _canonical_source_page_ids(candidate)
    ]
    if len(answerable) == 1 and len({str(candidate.get("candidate_kind", "")) for candidate in available}) >= 1:
        return "single_grounded_candidate"
    return "disagreement"


def _preferred_candidate(candidates: List[Mapping[str, Any]]) -> Optional[str]:
    by_kind = {str(candidate.get("candidate_kind", "")): candidate for candidate in candidates}
    available_answerable = [
        candidate
        for candidate in candidates
        if str(candidate.get("candidate_kind", "")) in {"system", "strong_model", "challenger"}
        and str(candidate.get("support_status", "not_run")) != "unavailable"
        and str(candidate.get("answerability", "")).strip() == "answerable"
        and _canonical_source_page_ids(candidate)
    ]
    if not available_answerable:
        return None
    normalized = Counter(_normalized_answer(candidate) for candidate in available_answerable)
    top_answer, top_count = normalized.most_common(1)[0]
    agreeing = [candidate for candidate in available_answerable if _normalized_answer(candidate) == top_answer]
    if top_count >= 2:
        for kind in ("system", "strong_model", "challenger"):
            if kind in {str(candidate.get("candidate_kind", "")) for candidate in agreeing}:
                return kind
    if len(available_answerable) == 1:
        return str(available_answerable[0].get("candidate_kind", "")).strip()
    system_candidate = by_kind.get("system")
    if system_candidate and str(system_candidate.get("answerability", "")).strip() == "answerable" and _canonical_source_page_ids(system_candidate):
        system_answer = _normalized_answer(system_candidate)
        contradicting = [
            candidate
            for candidate in available_answerable
            if str(candidate.get("candidate_kind", "")) != "system"
            and _normalized_answer(candidate) != system_answer
        ]
        if not contradicting:
            return "system"
    return None


def _unavailable_candidate(candidate_kind: str, question_id: str, reason: str) -> Dict[str, Any]:
    return CandidateAnswer(
        candidate_id=f"{candidate_kind}:{question_id}",
        candidate_kind=candidate_kind,  # type: ignore[arg-type]
        answer=None,
        answerability="abstain",
        sources=[],
        support_status="unavailable",
        unavailable_reason=reason,
        label=candidate_kind.replace("_", " "),
        metadata={"generated_by": "pilot_gold_v1"},
    ).model_dump(mode="json")


def _load_review_record(client: TestClient, run_id: str, question_id: str) -> Dict[str, Any]:
    response = client.get(f"/v1/review/questions/{question_id}", params={"run_id": run_id})
    if response.status_code != 200:
        raise SystemExit(f"failed to fetch review record for {question_id}: {response.status_code} {response.text}")
    return response.json()


def _ensure_candidates(client: TestClient, run_id: str, question_id: str, *, strong_profile_id: str, challenger_profile_id: str) -> Dict[str, Any]:
    response = client.post(
        f"/v1/review/questions/{question_id}/generate-candidates",
        params={"run_id": run_id},
        json={
            "reviewer": "pilot_gold_bot",
            "strong_profile_id": strong_profile_id,
            "challenger_profile_id": challenger_profile_id,
        },
    )
    if response.status_code != 200:
        record = _load_review_record(client, run_id, question_id)
    else:
        record = response.json()["record"]
    by_kind = {candidate["candidate_kind"]: candidate for candidate in record.get("candidate_bundle", [])}
    changed = False
    if "strong_model" not in by_kind:
        record.setdefault("candidate_bundle", []).append(
            _unavailable_candidate("strong_model", question_id, "profile_generation_failed")
        )
        changed = True
    if "challenger" not in by_kind:
        record.setdefault("candidate_bundle", []).append(
            _unavailable_candidate("challenger", question_id, "profile_generation_failed")
        )
        changed = True
    if "mini_check" not in by_kind:
        record.setdefault("candidate_bundle", []).append(
            _unavailable_candidate("mini_check", question_id, "mini_check_not_run")
        )
        changed = True
    if changed:
        artifact = runtime_pg.get_run_question_review(run_id, question_id) if runtime_pg.enabled() else store.get_run_question_review(run_id, question_id)
        if artifact:
            artifact.candidate_bundle = [
                CandidateAnswer.model_validate(candidate)
                for candidate in record["candidate_bundle"]
            ]
            if runtime_pg.enabled():
                runtime_pg.upsert_run_question_review(run_id, question_id, artifact)
            else:
                store.upsert_run_question_review(run_id, question_id, artifact.model_dump(mode="json"))
        record = _load_review_record(client, run_id, question_id)
    return record


def _try_mini_check(
    client: TestClient,
    run_id: str,
    question_id: str,
    *,
    candidate: Mapping[str, Any],
    answer_type: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    response = client.post(
        f"/v1/review/questions/{question_id}/mini-check",
        params={"run_id": run_id},
        json={
            "reviewer": "pilot_gold_bot",
            "candidate_kind": str(candidate.get("candidate_kind", "")).strip() or "system",
            "candidate_answer": candidate.get("answer"),
            "candidate_answerability": str(candidate.get("answerability", "")).strip() or "abstain",
            "answer_type": answer_type,
            "evidence": candidate.get("sources", []),
        },
    )
    if response.status_code == 200:
        payload = response.json()
        return payload.get("mini_check_result"), None
    return None, response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text


def _upsert_unresolved_stub(*, gold_dataset_id: str, question_row: Mapping[str, Any], note: str) -> None:
    existing = runtime_pg.find_gold_question_by_dataset_question(gold_dataset_id, str(question_row["question_id"])) if runtime_pg.enabled() else store.find_gold_question_by_dataset_question(gold_dataset_id, str(question_row["question_id"]))
    payload = {
        "question_id": str(question_row["question_id"]),
        "canonical_answer": None,
        "answer_type": str(question_row["answer_type"]),
        "source_sets": [],
        "review_status": "draft",
        "reviewers": ["pilot_gold_bot"],
        "notes": note,
    }
    if existing:
        existing.canonical_answer = None
        existing.answer_type = str(question_row["answer_type"])
        existing.source_sets = []
        existing.review_status = "draft"
        existing.reviewers = sorted(set([*existing.reviewers, "pilot_gold_bot"]))
        existing.notes = note
        if runtime_pg.enabled():
            runtime_pg.upsert_gold_question(existing)
        else:
            store.gold_questions[gold_dataset_id][existing.gold_question_id] = existing
        return
    if runtime_pg.enabled():
        runtime_pg.add_gold_question(gold_dataset_id, payload)
    else:
        store.add_gold_question(gold_dataset_id, payload)


def _list_gold_questions(gold_dataset_id: str) -> List[Dict[str, Any]]:
    if runtime_pg.enabled():
        items = runtime_pg.list_gold_questions(gold_dataset_id).values()
        return [item.model_dump(mode="json") for item in items]
    return [item.model_dump(mode="json") for item in store.gold_questions.get(gold_dataset_id, {}).values()]


def _reject_reasons(record: Mapping[str, Any], accepted_kind: Optional[str]) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []
    accepted_value = None
    if accepted_kind:
        for candidate in record.get("candidate_bundle", []):
            if str(candidate.get("candidate_kind", "")) == accepted_kind:
                accepted_value = _normalized_answer(candidate)
                break
    for candidate in record.get("candidate_bundle", []):
        kind = str(candidate.get("candidate_kind", ""))
        if kind == accepted_kind:
            continue
        support_status = str(candidate.get("support_status", "not_run"))
        unavailable_reason = str(candidate.get("unavailable_reason", "")).strip()
        if support_status == "unavailable":
            reason = unavailable_reason or "unavailable"
        elif str(candidate.get("answerability", "")) == "abstain" and accepted_kind:
            reason = "abstained_while_other_candidate_answered"
        elif accepted_value is not None and _normalized_answer(candidate) != accepted_value:
            reason = "answer_mismatch"
        else:
            reason = "not_selected"
        reasons.append({"candidate_kind": kind, "reason": reason})
    return reasons


def _build_report(
    *,
    locked_count: int,
    unresolved_count: int,
    disagreement_histogram: Counter[str],
    reason_histogram: Counter[str],
    blockers: List[str],
    artifact_dir: Path,
    run_id: str,
    gold_dataset_id: str,
) -> str:
    lines = [
        "# Pilot Gold V1 Report",
        "",
        f"- run_id: `{run_id}`",
        f"- gold_dataset_id: `{gold_dataset_id}`",
        f"- artifact_dir: `{artifact_dir}`",
        "",
        "## Outcome",
        "",
        f"- locked_count: `{locked_count}`",
        f"- unresolved_count: `{unresolved_count}`",
        "",
        "## Disagreement Buckets",
        "",
    ]
    if disagreement_histogram:
        for bucket, count in disagreement_histogram.most_common():
            lines.append(f"- `{bucket}`: `{count}`")
    else:
        lines.append("- `none`")
    lines.extend(["", "## Top 5 Adjudication Reasons", ""])
    for reason, count in reason_histogram.most_common(5):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## Blockers Before Full Gold", ""])
    for blocker in blockers:
        lines.append(f"- {blocker}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adjudicate and lock the pilot gold subset")
    parser.add_argument("--documents", default=str(DEFAULT_DOCUMENTS))
    parser.add_argument("--subset", default=str(DEFAULT_SUBSET))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--gold-output", default=str(DEFAULT_GOLD_OUTPUT))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT_OUTPUT))
    parser.add_argument("--disagreement-output", default=str(DEFAULT_DISAGREEMENT_OUTPUT))
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    subset_rows = _load_subset(Path(args.subset).resolve())
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    documents_path = Path(args.documents).resolve()
    if not documents_path.exists():
        raise SystemExit(f"documents bundle not found: {documents_path}")

    # Ensure local in-memory state has corpus for the same process.
    load_persisted_state()
    project_id = f"pilot-gold-v1-{uuid4()}"
    dataset_id = f"pilot-gold-v1-{uuid4()}"
    corpus_router.import_zip(
        {
            "project_id": project_id,
            "blob_url": str(documents_path),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        }
    )

    client = TestClient(app)
    question_payloads = [
        {
            "id": row["question_id"],
            "question": row["question"],
            "answer_type": row["answer_type"],
            "difficulty": "medium",
            "tags": ["pilot_gold_v1", row["route_family"], row["risk_tier"]],
        }
        for row in subset_rows
    ]
    imported = client.post(
        f"/v1/qa/datasets/{dataset_id}/import-questions",
        json={"project_id": project_id, "source": "pilot_gold_v1", "questions": question_payloads},
    )
    if imported.status_code != 200:
        raise SystemExit(f"failed to import pilot gold questions: {imported.status_code} {imported.text}")

    batch = client.post(
        "/v1/qa/ask-batch",
        json={
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_ids": [row["question_id"] for row in subset_rows],
            "runtime_policy": _runtime_policy_payload(max_candidate_pages=8, max_context_paragraphs=8, allow_dense_fallback=False),
        },
    )
    if batch.status_code != 202:
        raise SystemExit(f"failed to create pilot gold review run: {batch.status_code} {batch.text}")
    run_id = batch.json()["run_id"]

    gold_target = client.post(f"/v1/review/runs/{run_id}/gold-target")
    if gold_target.status_code != 200:
        raise SystemExit(f"failed to ensure review gold target: {gold_target.status_code} {gold_target.text}")
    gold_dataset_id = gold_target.json()["gold_dataset_id"]

    strong_profile = client.post(
        "/v1/experiments/profiles",
        json={
            "name": "pilot-gold-strong",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "gold_dataset_id": gold_dataset_id,
            "runtime_policy": _runtime_policy_payload(max_candidate_pages=12, max_context_paragraphs=12, allow_dense_fallback=True),
        },
    )
    challenger_profile = client.post(
        "/v1/experiments/profiles",
        json={
            "name": "pilot-gold-challenger",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "gold_dataset_id": gold_dataset_id,
            "runtime_policy": _runtime_policy_payload(max_candidate_pages=4, max_context_paragraphs=6, allow_dense_fallback=False),
        },
    )
    if strong_profile.status_code != 200 or challenger_profile.status_code != 200:
        raise SystemExit("failed to create strong/challenger experiment profiles for pilot gold")
    strong_profile_id = strong_profile.json()["profile_id"]
    challenger_profile_id = challenger_profile.json()["profile_id"]

    disagreement_rows: List[Dict[str, Any]] = []
    reason_histogram: Counter[str] = Counter()
    disagreement_histogram: Counter[str] = Counter()
    locked_count = 0
    unresolved_count = 0

    candidate_bundle_rows: List[Dict[str, Any]] = []

    for row in subset_rows:
        question_id = str(row["question_id"])
        record = _ensure_candidates(
            client,
            run_id,
            question_id,
            strong_profile_id=strong_profile_id,
            challenger_profile_id=challenger_profile_id,
        )
        candidates = list(record.get("candidate_bundle", []))
        agreement_state = _agreement_state(candidates)
        accepted_kind = _preferred_candidate(candidates)
        adjudication_reason = ""
        mini_check_payload: Optional[Dict[str, Any]] = None
        mini_check_error: Optional[str] = None

        if row["route_family"] == "negative_or_unanswerable":
            adjudication_reason = "expected_no_answer_requires_manual_confirmation"
            client.post(
                f"/v1/review/questions/{question_id}/custom-decision",
                params={"run_id": run_id},
                json={
                    "reviewer": "pilot_gold_bot",
                    "final_answer": FREE_TEXT_NO_ANSWER if row["answer_type"] == "free_text" else None,
                    "answerability": "abstain",
                    "final_sources": [],
                    "adjudication_note": "Expected adversarial/no-answer question; retained abstain and left unresolved because no source pages support a lock.",
                },
            )
            _upsert_unresolved_stub(
                gold_dataset_id=gold_dataset_id,
                question_row=row,
                note="unresolved: expected no-answer question remains unlocked because accepted abstain has no source pages",
            )
            unresolved_count += 1
        elif accepted_kind is not None:
            accepted = client.post(
                f"/v1/review/questions/{question_id}/accept-candidate",
                params={"run_id": run_id},
                json={
                    "reviewer": "pilot_gold_bot",
                    "candidate_kind": accepted_kind,
                    "reviewer_confidence": 0.8,
                    "adjudication_note": (
                        "Locked from the first grounded candidate bundle. "
                        "Alternative candidates were unavailable, abstained, or disagreed without stronger page-grounded support."
                    ),
                },
            )
            if accepted.status_code != 200:
                adjudication_reason = "accept_candidate_failed"
                _upsert_unresolved_stub(
                    gold_dataset_id=gold_dataset_id,
                    question_row=row,
                    note=f"unresolved: accept_candidate failed for {accepted_kind}",
                )
                unresolved_count += 1
            else:
                accepted_record = accepted.json()
                chosen_candidate = next(
                    (candidate for candidate in accepted_record.get("candidate_bundle", []) if candidate.get("candidate_kind") == accepted_kind),
                    None,
                )
                if chosen_candidate and chosen_candidate.get("sources"):
                    mini_check_payload, mini_check_error = _try_mini_check(
                        client,
                        run_id,
                        question_id,
                        candidate=chosen_candidate,
                        answer_type=str(row["answer_type"]),
                    )
                if mini_check_payload and mini_check_payload.get("verdict") == "not_supported":
                    adjudication_reason = "mini_check_not_supported"
                    _upsert_unresolved_stub(
                        gold_dataset_id=gold_dataset_id,
                        question_row=row,
                        note="unresolved: mini-check contradicted the selected candidate",
                    )
                    unresolved_count += 1
                else:
                    locked = client.post(
                        f"/v1/review/questions/{question_id}/lock-gold",
                        params={"run_id": run_id},
                        json={
                            "reviewer": "pilot_gold_bot",
                            "reviewer_confidence": 0.8,
                            "adjudication_note": (
                                accepted_record["accepted_decision"]["adjudication_note"]
                                if accepted_record.get("accepted_decision")
                                else "pilot gold adjudication"
                            ),
                        },
                    )
                    if locked.status_code == 200:
                        locked_count += 1
                        adjudication_reason = "locked_from_grounded_candidate"
                    else:
                        adjudication_reason = "lock_gold_failed"
                        _upsert_unresolved_stub(
                            gold_dataset_id=gold_dataset_id,
                            question_row=row,
                            note=f"unresolved: lock_gold failed for accepted candidate {accepted_kind}",
                        )
                        unresolved_count += 1
        else:
            adjudication_reason = "no_grounded_candidate_consensus"
            client.post(
                f"/v1/review/questions/{question_id}/custom-decision",
                params={"run_id": run_id},
                json={
                    "reviewer": "pilot_gold_bot",
                    "final_answer": FREE_TEXT_NO_ANSWER if row["answer_type"] == "free_text" else None,
                    "answerability": "abstain",
                    "final_sources": [],
                    "adjudication_note": "No sufficiently grounded candidate consensus; left unresolved.",
                },
            )
            _upsert_unresolved_stub(
                gold_dataset_id=gold_dataset_id,
                question_row=row,
                note="unresolved: no grounded candidate consensus",
            )
            unresolved_count += 1

        record = _load_review_record(client, run_id, question_id)
        candidate_bundle_rows.append(
            {
                "question_id": question_id,
                "system_candidate": next((candidate for candidate in record.get("candidate_bundle", []) if candidate.get("candidate_kind") == "system"), None),
                "strong_candidate": next((candidate for candidate in record.get("candidate_bundle", []) if candidate.get("candidate_kind") == "strong_model"), None),
                "challenger_candidate": next((candidate for candidate in record.get("candidate_bundle", []) if candidate.get("candidate_kind") == "challenger"), None),
                "mini_check": mini_check_payload or {"status": "not_run" if mini_check_error is None else "unavailable", "detail": mini_check_error},
                "shared_evidence": record.get("document_viewer", {}),
                "agreement_state": agreement_state,
                "needs_manual_review": record.get("status") != "gold_locked",
            }
        )

        disagreement_flags = list(record.get("disagreement_flags", []))
        for flag in disagreement_flags:
            disagreement_histogram[flag] += 1
        reason_histogram[adjudication_reason] += 1
        disagreement_rows.append(
            {
                "question_id": question_id,
                "route_family": row["route_family"],
                "agreement_state": agreement_state,
                "record_status": record.get("status"),
                "adjudication_reason": adjudication_reason,
                "mini_check_verdict": mini_check_payload.get("verdict") if mini_check_payload else None,
                "mini_check_error": mini_check_error,
                "disagreement_flags": disagreement_flags,
                "rejected_candidates": _reject_reasons(record, record.get("accepted_decision", {}).get("decision_source")),
                "accepted_decision": record.get("accepted_decision"),
            }
        )

    gold_rows = sorted(_list_gold_questions(gold_dataset_id), key=lambda row: str(row.get("question_id", "")))
    _write_jsonl(Path(args.gold_output).resolve(), gold_rows)
    _write_jsonl(Path(args.disagreement_output).resolve(), disagreement_rows)
    _write_jsonl(artifact_dir / "pilot_candidate_bundles_v1.jsonl", candidate_bundle_rows)

    blockers = [
        "Strong/challenger candidates still depend on lightweight experimental profile variations; they are not independent model families.",
        "Unresolved rows remain where all grounded candidates abstain or where no source pages support a lockable decision.",
        "Adversarial/no-answer questions cannot be locked until the review flow supports no-answer gold with explicit source policy or a separate locked-no-answer contract.",
    ]
    report = _build_report(
        locked_count=locked_count,
        unresolved_count=unresolved_count,
        disagreement_histogram=disagreement_histogram,
        reason_histogram=reason_histogram,
        blockers=blockers,
        artifact_dir=artifact_dir,
        run_id=run_id,
        gold_dataset_id=gold_dataset_id,
    )
    report_path = Path(args.report_output).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    _write_json(
        artifact_dir / "pilot_gold_v1_manifest.json",
        {
            "version": PILOT_GOLD_VERSION,
            "run_id": run_id,
            "gold_dataset_id": gold_dataset_id,
            "locked_count": locked_count,
            "unresolved_count": unresolved_count,
            "gold_output_path": str(Path(args.gold_output).resolve()),
            "disagreement_output_path": str(Path(args.disagreement_output).resolve()),
        },
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "run_id": run_id,
                "gold_dataset_id": gold_dataset_id,
                "locked_count": locked_count,
                "unresolved_count": unresolved_count,
                "gold_output_path": str(Path(args.gold_output).resolve()),
                "disagreement_output_path": str(Path(args.disagreement_output).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
