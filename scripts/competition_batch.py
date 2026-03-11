#!/usr/bin/env python3
"""Official offline competition batch runner for local dataset bundles."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import corpus_pg, runtime_pg  # noqa: E402
from legal_rag_api.contracts import QueryResponse, RuntimePolicy  # noqa: E402
from legal_rag_api.official_submission import (  # noqa: E402
    DEFAULT_ARCHITECTURE_SUMMARY,
    build_official_submission_payload,
    submission_preflight_report,
    validate_official_submission_payload,
)
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.routers import qa as qa_router  # noqa: E402
from legal_rag_api.state import competition_mode_enabled, store  # noqa: E402
from packages.scorers.contracts import evaluate_query_response_contract  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "reports" / "competition_runs"
DEFAULT_PROJECT_ID = "competition_local"
RUN_MANIFEST_VERSION = "competition_batch_run_manifest.v1"
QUESTION_STATUS_VERSION = "competition_question_status.v1"
DEFAULT_RUNTIME_POLICY = RuntimePolicy(
    use_llm=False,
    max_candidate_pages=8,
    max_context_paragraphs=8,
    page_index_base_export=0,
    scoring_policy_version="contest_v2026_public_rules_v1",
    allow_dense_fallback=False,
    return_debug_trace=False,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _git_metadata() -> Dict[str, str]:
    def _run_git(*args: str) -> str:
        try:
            process = subprocess.run(
                ["git", *args],
                cwd=str(ROOT),
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return ""
        if process.returncode != 0:
            return ""
        return str(process.stdout or "").strip()

    sha = _run_git("rev-parse", "HEAD")
    short_sha = _run_git("rev-parse", "--short", "HEAD")
    dirty = "dirty" if _run_git("status", "--porcelain") else "clean"
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return {
        "git_sha": sha,
        "git_short_sha": short_sha,
        "git_branch": branch,
        "git_worktree_state": dirty,
    }


def _assert_competition_storage_ready() -> None:
    if competition_mode_enabled() and not runtime_pg.enabled():
        raise SystemExit(
            "COMPETITION_MODE=1 requires PostgreSQL runtime storage (DATABASE_URL) for batch runner execution."
        )


def _configure_offline_otel_mode() -> None:
    # Batch runner executes outside FastAPI request spans; force offline mode so
    # telemetry completeness does not depend on unrelated app instrumentation state.
    try:
        from legal_rag_api import otel as otel_module
    except Exception:  # pragma: no cover - defensive import fallback
        return
    otel_module._OTEL_STATUS = {
        "enabled": False,
        "reason": "competition_batch_offline_runner",
    }


def _resolve_runtime_policy(page_index_base: int) -> RuntimePolicy:
    return DEFAULT_RUNTIME_POLICY.model_copy(update={"page_index_base_export": int(page_index_base)})


def _resolve_questions_payload(path: Path) -> List[Dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("questions"), list):
        rows = payload.get("questions", [])
    else:
        raise SystemExit("questions payload must be a JSON array or an object with `questions` array")
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit(f"question row at index {idx} must be an object")
        out.append(row)
    return out


def _filter_questions(
    questions: List[Dict[str, Any]],
    *,
    selected_ids: List[str],
    limit: int | None,
) -> List[Dict[str, Any]]:
    filtered = questions
    if selected_ids:
        selected_set = {item.strip() for item in selected_ids if item.strip()}
        available_ids = {str(item.get("id", "")).strip() for item in questions}
        missing_ids = sorted(qid for qid in selected_set if qid not in available_ids)
        if missing_ids:
            raise SystemExit(f"question id filter contains unknown ids: {missing_ids}")
        filtered = [item for item in questions if str(item.get("id", "")).strip() in selected_set]
    if limit is not None and limit > 0:
        filtered = filtered[:limit]
    if not filtered:
        raise SystemExit("question selection is empty after filtering")
    return filtered


def _unique_question_ids(questions: Iterable[Dict[str, Any]]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in questions:
        qid = str(item.get("id", "")).strip()
        if not qid or qid in seen:
            continue
        seen.add(qid)
        out.append(qid)
    return out


def _default_dataset_id(questions_path: Path, question_ids: List[str]) -> str:
    digest = hashlib.sha256(
        f"{questions_path.resolve()}::{','.join(question_ids)}".encode("utf-8")
    ).hexdigest()[:20]
    return f"competition_offline_{digest}"


def _question_cache_path(cache_dir: Path, question_id: str) -> Path:
    digest = hashlib.sha256(question_id.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _load_cached_response(cache_dir: Path, question_id: str) -> QueryResponse | None:
    path = _question_cache_path(cache_dir, question_id)
    if not path.exists():
        return None
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    response_payload = payload.get("query_response")
    if not isinstance(response_payload, dict):
        return None
    return QueryResponse(**response_payload)


def _save_cached_response(cache_dir: Path, question_id: str, response: QueryResponse) -> Path:
    path = _question_cache_path(cache_dir, question_id)
    _write_json(
        path,
        {
            "question_id": question_id,
            "query_response": response.model_dump(mode="json"),
            "cached_at": _iso(_utcnow()),
        },
    )
    return path


def _load_existing_status_map(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        qid = str(row.get("question_id", "")).strip()
        if not qid:
            continue
        out[qid] = row
    return out


def _write_status_map(path: Path, status_map: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for qid in sorted(status_map.keys()):
        lines.append(json.dumps(status_map[qid], ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _ensure_output_dir(path: Path, *, overwrite: bool, resume: bool) -> None:
    if overwrite and resume:
        raise SystemExit("use either --overwrite or --resume, not both")
    if path.exists():
        has_any_files = any(path.iterdir())
        if has_any_files:
            if overwrite:
                shutil.rmtree(path)
            elif not resume:
                raise SystemExit(
                    f"output directory already exists and is not empty: {path}. "
                    "Use --overwrite or --resume."
                )
    path.mkdir(parents=True, exist_ok=True)


def _resolve_architecture_summary(
    *,
    architecture_summary: str | None,
    architecture_summary_file: str | None,
) -> Tuple[str, Dict[str, str]]:
    if architecture_summary and architecture_summary_file:
        raise SystemExit("choose either --architecture-summary or --architecture-summary-file")
    if architecture_summary_file:
        path = Path(architecture_summary_file).resolve()
        if not path.exists():
            raise SystemExit(f"architecture summary file not found: {path}")
        summary = path.read_text(encoding="utf-8").strip()
        if not summary:
            raise SystemExit("architecture summary file is empty")
        return summary, {"source": "file", "path": str(path)}
    if architecture_summary:
        summary = architecture_summary.strip()
        if not summary:
            raise SystemExit("architecture summary must be non-empty")
        return summary, {"source": "cli", "path": ""}
    return DEFAULT_ARCHITECTURE_SUMMARY, {"source": "default", "path": ""}


def _persist_prediction(
    *,
    run_id: str,
    question_id: str,
    query_payload: Any,
    response: QueryResponse,
    answer_ctx: Dict[str, Any] | None,
) -> None:
    if runtime_pg.enabled():
        runtime_pg.upsert_run_question(run_id, question_id, response)
        if answer_ctx is not None:
            runtime_pg.upsert_run_question_review(
                run_id,
                question_id,
                qa_router._build_review_artifact(
                    run_id=run_id,
                    query_request=query_payload,
                    response=response,
                    candidates=answer_ctx["candidates"],
                    page_refs=answer_ctx["page_refs"],
                    retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                    solver_trace=answer_ctx["solver_trace"],
                    evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                    route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                    latency_budget_assertion=answer_ctx["latency_budget_assertion"],
                ),
            )
        runtime_pg.upsert_question_telemetry(question_id, response.telemetry.model_dump(mode="json"))
        return

    store.upsert_run_question(run_id, question_id, response)
    if answer_ctx is not None:
        store.upsert_run_question_review(
            run_id,
            question_id,
            qa_router._build_review_artifact(
                run_id=run_id,
                query_request=query_payload,
                response=response,
                candidates=answer_ctx["candidates"],
                page_refs=answer_ctx["page_refs"],
                retrieval_profile_id=answer_ctx["retrieval_profile_id"],
                solver_trace=answer_ctx["solver_trace"],
                evidence_selection_trace=answer_ctx["evidence_selection_trace"],
                route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
                latency_budget_assertion=answer_ctx["latency_budget_assertion"],
            ).model_dump(mode="json"),
        )
    store.question_telemetry[question_id] = response.telemetry.model_dump(mode="json")


async def _run_question(
    *,
    project_id: str,
    dataset_id: str,
    question_id: str,
    runtime_policy: RuntimePolicy,
) -> Tuple[Any, QueryResponse, Dict[str, Any]]:
    query_payload = qa_router._build_question_from_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        question_id=question_id,
        runtime_policy=runtime_policy,
    )
    response, answer_ctx = await qa_router._answer_query(query_payload)
    return query_payload, response, answer_ctx


def _question_contract_snapshot(response: QueryResponse) -> Dict[str, Any]:
    contract = evaluate_query_response_contract(
        answer=response.answer,
        answer_type=response.answer_type,
        abstained=response.abstained,
        confidence=response.confidence,
        sources=response.sources,
        telemetry=response.telemetry,
    )
    return {
        "competition_contract_valid": bool(contract.get("competition_contract_valid", False)),
        "issue_count": int(contract.get("issue_count", 0) or 0),
        "blocking_failures": list(contract.get("blocking_failures", []) or []),
    }


def _build_status_row(
    *,
    question_id: str,
    response: QueryResponse | None,
    success: bool,
    resumed_from_cache: bool,
    error_message: str = "",
) -> Dict[str, Any]:
    if response is None:
        return {
            "status_version": QUESTION_STATUS_VERSION,
            "question_id": question_id,
            "success": False,
            "error": error_message or "unknown_error",
            "resumed_from_cache": resumed_from_cache,
        }
    contract = _question_contract_snapshot(response)
    return {
        "status_version": QUESTION_STATUS_VERSION,
        "question_id": question_id,
        "answer_type": response.answer_type,
        "route_name": response.route_name,
        "success": success,
        "validation": contract,
        "error": error_message,
        "abstained": bool(response.abstained),
        "answer_is_null": response.answer is None,
        "resumed_from_cache": resumed_from_cache,
    }


def _summarize_markdown(manifest: Dict[str, Any]) -> str:
    counts = manifest.get("counts", {})
    validation = manifest.get("validation", {})
    artifacts = manifest.get("artifacts", {})
    inputs = manifest.get("inputs", {})
    lines = [
        "# Competition Batch Run Summary",
        "",
        f"- run_id: `{manifest.get('run_id', '')}`",
        f"- status: `{manifest.get('status', '')}`",
        f"- started_at_utc: `{manifest.get('started_at_utc', '')}`",
        f"- completed_at_utc: `{manifest.get('completed_at_utc', '')}`",
        "",
        "## Inputs",
        "",
        f"- questions_path: `{inputs.get('questions_path', '')}`",
        f"- documents_path: `{inputs.get('documents_path', '')}`",
        f"- project_id: `{inputs.get('project_id', '')}`",
        f"- dataset_id: `{inputs.get('dataset_id', '')}`",
        "",
        "## Counts",
        "",
        f"- question_count: `{counts.get('question_count', 0)}`",
        f"- success_count: `{counts.get('success_count', 0)}`",
        f"- failure_count: `{counts.get('failure_count', 0)}`",
        f"- resumed_from_cache_count: `{counts.get('resumed_from_cache_count', 0)}`",
        "",
        "## Validation",
        "",
        f"- strict_contract_mode: `{validation.get('strict_contract_mode', False)}`",
        f"- preflight_blocking_failed: `{validation.get('preflight_blocking_failed', False)}`",
        f"- official_submission_valid: `{validation.get('official_submission_valid', False)}`",
        "",
        "## Artifacts",
        "",
        f"- submission_path: `{artifacts.get('submission_path', '')}`",
        f"- question_status_path: `{artifacts.get('question_status_path', '')}`",
        f"- preflight_report_path: `{artifacts.get('preflight_report_path', '')}`",
        f"- validation_report_path: `{artifacts.get('validation_report_path', '')}`",
    ]
    return "\n".join(lines) + "\n"


def _validate_submission_file(
    submission_path: Path,
    *,
    report_path: Path,
) -> Tuple[dict[str, Any], bool]:
    payload = _load_json(submission_path)
    report = validate_official_submission_payload(payload)
    report["submission_path"] = str(submission_path.resolve())
    _write_json(report_path, report)
    return report, bool(report.get("valid", False))


def _prepare_corpus(
    *,
    documents_path: Path,
    project_id: str,
    parse_policy: str,
    dedupe_enabled: bool,
) -> dict[str, Any]:
    if competition_mode_enabled() and not corpus_pg.enabled():
        raise SystemExit(
            "COMPETITION_MODE=1 requires PostgreSQL corpus storage (DATABASE_URL) for `prepare`."
        )
    if not documents_path.exists():
        raise SystemExit(f"documents bundle not found: {documents_path}")
    if not documents_path.is_file():
        raise SystemExit(f"documents path is not a file: {documents_path}")
    return corpus_router.import_zip(
        {
            "project_id": project_id,
            "blob_url": str(documents_path.resolve()),
            "parse_policy": parse_policy,
            "dedupe_enabled": bool(dedupe_enabled),
        }
    )


def command_prepare(args: argparse.Namespace) -> int:
    _assert_competition_storage_ready()
    started_at = _utcnow()
    documents_path = Path(args.documents).resolve()
    result = _prepare_corpus(
        documents_path=documents_path,
        project_id=str(args.project_id),
        parse_policy=str(args.parse_policy),
        dedupe_enabled=bool(args.dedupe_enabled),
    )
    completed_at = _utcnow()
    report = {
        "command": "prepare",
        "started_at_utc": _iso(started_at),
        "completed_at_utc": _iso(completed_at),
        "documents_path": str(documents_path),
        "project_id": str(args.project_id),
        "result": result,
        "code_version": _git_metadata(),
    }
    output_path = Path(args.output).resolve()
    _write_json(output_path, report)
    _print_json(report)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    submission_path = Path(args.submission).resolve()
    if not submission_path.exists():
        raise SystemExit(f"submission not found: {submission_path}")
    report_path = (
        Path(args.report).resolve()
        if args.report
        else submission_path.parent / f"{submission_path.stem}.validation_report.json"
    )
    report, is_valid = _validate_submission_file(
        submission_path=submission_path,
        report_path=report_path,
    )
    _print_json(report)
    return 0 if is_valid else 1


def command_run(args: argparse.Namespace) -> int:
    _assert_competition_storage_ready()
    _configure_offline_otel_mode()
    started_at = _utcnow()
    output_dir = Path(args.output).resolve()
    _ensure_output_dir(output_dir, overwrite=bool(args.overwrite), resume=bool(args.resume))

    questions_path = Path(args.questions).resolve()
    if not questions_path.exists():
        raise SystemExit(f"questions file not found: {questions_path}")

    questions_payload = _resolve_questions_payload(questions_path)
    filtered_questions = _filter_questions(
        questions_payload,
        selected_ids=list(args.question_ids or []),
        limit=args.limit,
    )
    question_ids = _unique_question_ids(filtered_questions)
    if not question_ids:
        raise SystemExit("no valid question ids found in selected questions")

    project_id = str(args.project_id).strip() or DEFAULT_PROJECT_ID
    dataset_id = str(args.dataset_id).strip() if args.dataset_id else _default_dataset_id(questions_path, question_ids)
    runtime_policy = _resolve_runtime_policy(int(args.page_index_base))
    architecture_summary, architecture_summary_meta = _resolve_architecture_summary(
        architecture_summary=args.architecture_summary,
        architecture_summary_file=args.architecture_summary_file,
    )

    prepare_result: dict[str, Any] | None = None
    documents_path = ""
    if args.documents:
        documents = Path(args.documents).resolve()
        documents_path = str(documents)
        prepare_result = _prepare_corpus(
            documents_path=documents,
            project_id=project_id,
            parse_policy=str(args.parse_policy),
            dedupe_enabled=bool(args.dedupe_enabled),
        )

    import_result = qa_router.import_questions(
        dataset_id,
        {
            "project_id": project_id,
            "source": "competition_batch_runner",
            "questions": filtered_questions,
        },
    )

    if runtime_pg.enabled():
        run = runtime_pg.create_run(dataset_id, len(question_ids), status="running")
    else:
        run = store.create_run(dataset_id, len(question_ids), status="running")
    run_id = str(run["run_id"])

    question_cache_dir = output_dir / "question_results"
    question_cache_dir.mkdir(parents=True, exist_ok=True)
    question_status_path = output_dir / "question_status.jsonl"
    status_map = _load_existing_status_map(question_status_path) if args.resume else {}
    responses_by_id: Dict[str, QueryResponse] = {}
    success_count = 0
    failure_count = 0
    resumed_count = 0

    for question_id in question_ids:
        resumed_from_cache = False
        response: QueryResponse | None = None
        try:
            if args.resume:
                cached = _load_cached_response(question_cache_dir, question_id)
                if cached is not None:
                    resumed_from_cache = True
                    resumed_count += 1
                    response = cached
                    _persist_prediction(
                        run_id=run_id,
                        question_id=question_id,
                        query_payload=None,
                        response=response,
                        answer_ctx=None,
                    )
            if response is None:
                query_payload, response, answer_ctx = asyncio.run(
                    _run_question(
                        project_id=project_id,
                        dataset_id=dataset_id,
                        question_id=question_id,
                        runtime_policy=runtime_policy,
                    )
                )
                _persist_prediction(
                    run_id=run_id,
                    question_id=question_id,
                    query_payload=query_payload,
                    response=response,
                    answer_ctx=answer_ctx,
                )
                _save_cached_response(question_cache_dir, question_id, response)

            responses_by_id[question_id] = response
            success_count += 1
            status_map[question_id] = _build_status_row(
                question_id=question_id,
                response=response,
                success=True,
                resumed_from_cache=resumed_from_cache,
            )
        except Exception as exc:  # noqa: BLE001
            failure_count += 1
            status_map[question_id] = _build_status_row(
                question_id=question_id,
                response=None,
                success=False,
                resumed_from_cache=resumed_from_cache,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    _write_status_map(question_status_path, status_map)

    preflight_report_path = output_dir / "preflight_report.json"
    validation_report_path = output_dir / "submission.validation_report.json"
    submission_path = output_dir / "submission.json"
    run_summary_path = output_dir / "run_summary.md"
    run_manifest_path = output_dir / "run_manifest.json"

    preflight = submission_preflight_report(responses_by_id, strict_contract_mode=True)
    _write_json(preflight_report_path, preflight)

    submission_payload = build_official_submission_payload(
        responses_by_id,
        default_page_index_base=int(args.page_index_base),
        architecture_summary=architecture_summary,
    )
    _write_json(submission_path, submission_payload)

    validation_report, submission_valid = _validate_submission_file(
        submission_path=submission_path,
        report_path=validation_report_path,
    )

    completed_at = _utcnow()
    run_status = "completed"
    top_level_errors: List[str] = []
    if failure_count > 0:
        run_status = "failed"
        top_level_errors.append("one_or_more_questions_failed")
    if bool(preflight.get("blocking_failed", False)):
        run_status = "failed"
        top_level_errors.append("submission_contract_preflight_failed")
    if not submission_valid:
        run_status = "failed"
        top_level_errors.append("official_submission_validation_failed")

    if runtime_pg.enabled():
        runtime_pg.set_run_status(run_id, run_status)
    else:
        store.set_run_status(run_id, run_status)

    manifest = {
        "manifest_version": RUN_MANIFEST_VERSION,
        "run_id": run_id,
        "status": run_status,
        "started_at_utc": _iso(started_at),
        "completed_at_utc": _iso(completed_at),
        "inputs": {
            "questions_path": str(questions_path),
            "documents_path": documents_path,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "question_id_filter": list(args.question_ids or []),
            "limit": int(args.limit) if args.limit is not None else None,
        },
        "counts": {
            "question_count": len(question_ids),
            "success_count": success_count,
            "failure_count": failure_count,
            "resumed_from_cache_count": resumed_count,
        },
        "artifacts": {
            "output_dir": str(output_dir),
            "submission_path": str(submission_path),
            "question_status_path": str(question_status_path),
            "preflight_report_path": str(preflight_report_path),
            "validation_report_path": str(validation_report_path),
            "run_summary_path": str(run_summary_path),
        },
        "validation": {
            "strict_contract_mode": bool(preflight.get("strict_contract_mode", True)),
            "preflight_blocking_failed": bool(preflight.get("blocking_failed", False)),
            "invalid_prediction_count": int(preflight.get("invalid_prediction_count", 0) or 0),
            "official_submission_valid": bool(validation_report.get("valid", False)),
        },
        "architecture_summary": architecture_summary_meta,
        "prepare_result": prepare_result,
        "import_result": import_result,
        "code_version": _git_metadata(),
        "errors": top_level_errors,
    }
    _write_json(run_manifest_path, manifest)
    run_summary_path.write_text(_summarize_markdown(manifest), encoding="utf-8")

    _print_json(
        {
            "status": run_status,
            "run_id": run_id,
            "manifest_path": str(run_manifest_path),
            "submission_path": str(submission_path),
            "question_status_path": str(question_status_path),
            "relative_manifest_path": _repo_relative(run_manifest_path),
        }
    )
    return 0 if run_status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Official offline competition batch runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="Ingest local documents bundle into local runtime corpus store")
    p_prepare.add_argument("--documents", required=True, help="Path to local documents.zip")
    p_prepare.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    p_prepare.add_argument("--parse-policy", default="balanced")
    p_prepare.add_argument("--dedupe-enabled", action="store_true", default=True)
    p_prepare.add_argument("--no-dedupe", dest="dedupe_enabled", action="store_false")
    p_prepare.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_ROOT / "prepare_report.json"),
        help="Path to write prepare report JSON",
    )

    p_run = sub.add_parser("run", help="Run local batch inference and write official submission artifacts")
    p_run.add_argument("--questions", required=True, help="Path to local questions JSON file")
    p_run.add_argument(
        "--output",
        required=True,
        help="Output directory for run artifacts (submission.json, run_manifest.json, statuses)",
    )
    p_run.add_argument("--documents", default="", help="Optional local documents.zip path to prepare before run")
    p_run.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    p_run.add_argument("--dataset-id", default="", help="Optional dataset id override")
    p_run.add_argument("--page-index-base", type=int, default=0, choices=[0, 1])
    p_run.add_argument("--parse-policy", default="balanced")
    p_run.add_argument("--dedupe-enabled", action="store_true", default=True)
    p_run.add_argument("--no-dedupe", dest="dedupe_enabled", action="store_false")
    p_run.add_argument("--overwrite", action="store_true", default=False)
    p_run.add_argument("--resume", action="store_true", default=False)
    p_run.add_argument("--limit", type=int, default=None, help="Process first N selected questions")
    p_run.add_argument(
        "--question-id",
        dest="question_ids",
        action="append",
        default=[],
        help="Restrict run to specific question id (repeatable)",
    )
    p_run.add_argument("--architecture-summary", default=None)
    p_run.add_argument("--architecture-summary-file", default=None)

    p_validate = sub.add_parser("validate", help="Validate an existing official submission.json without rerun")
    p_validate.add_argument("--submission", required=True, help="Path to submission.json")
    p_validate.add_argument("--report", default="", help="Path to write validation report JSON")

    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return command_prepare(args)
    if args.command == "run":
        return command_run(args)
    if args.command == "validate":
        return command_validate(args)
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
