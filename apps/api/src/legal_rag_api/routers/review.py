from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from legal_rag_api import corpus_pg, runtime_pg
from legal_rag_api.azure_llm import AzureLLMClient
from legal_rag_api.contracts import (
    AcceptedDecision,
    CandidateAnswer,
    EvidenceRef,
    GoldQuestion,
    MiniCheckResult,
    Question,
    QuestionReviewRecord,
    ReviewAcceptCandidateRequest,
    ReviewCandidateGenerationRequest,
    ReviewCustomDecisionRequest,
    ReviewExportRequest,
    ReviewLockGoldRequest,
    ReviewMiniCheckRequest,
    ReviewRunSummary,
    ReviewUnlockGoldRequest,
    RunQuestionReviewArtifact,
    RuntimePolicy,
    SOURCE_PAGE_ID_PATTERN,
)
from legal_rag_api.routers import qa as qa_router
from legal_rag_api.state import competition_mode_enabled, store

router = APIRouter(prefix="/v1/review", tags=["Review"])

REPO_ROOT = Path(__file__).resolve().parents[5]
REPORTS_DIR = REPO_ROOT / "reports" / "review_runs"
MINI_CHECK_PROMPT_PATH = REPO_ROOT / "packages" / "prompts" / "mini_check_prompt_v1.json"
llm_client = AzureLLMClient()
_CANDIDATE_ORDER = {
    "system": 0,
    "strong_model": 1,
    "challenger": 2,
    "mini_check": 3,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _review_console_enabled() -> bool:
    env_enabled = os.getenv("REVIEW_CONSOLE_V1", "1").strip().lower() not in {"0", "false", "off"}
    if competition_mode_enabled():
        return env_enabled
    return bool(env_enabled and store.feature_flags.get("review_console_v1", True))


def _review_mini_check_enabled() -> bool:
    env_enabled = os.getenv("REVIEW_MINI_CHECK_V1", "1").strip().lower() not in {"0", "false", "off"}
    if competition_mode_enabled():
        return env_enabled
    return bool(env_enabled and store.feature_flags.get("review_mini_check_v1", True))


def _ensure_review_enabled() -> None:
    if not _review_console_enabled():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="review console disabled")


def _ensure_mini_check_enabled() -> None:
    if not _review_mini_check_enabled():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="review mini-check disabled")


def _append_review_audit(event: str, target: str, payload: Dict[str, Any]) -> None:
    if runtime_pg.enabled():
        runtime_pg.append_audit(event, target, payload)
        return
    store.audit_log.append(
        {
            "event": event,
            "target": target,
            "at": _utcnow().isoformat(),
            "payload": payload,
        }
    )


def _get_run(run_id: str) -> Dict[str, Any]:
    if runtime_pg.enabled():
        run = runtime_pg.get_run(run_id)
    else:
        run = store.runs.get(run_id)
    if not run:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run not found")
    return run


def _list_run_review_artifacts(run_id: str) -> Dict[str, RunQuestionReviewArtifact]:
    if runtime_pg.enabled():
        return runtime_pg.list_run_question_reviews(run_id)
    return store.list_run_question_reviews(run_id)


def _get_run_review_artifact(run_id: str, question_id: str) -> RunQuestionReviewArtifact:
    if runtime_pg.enabled():
        artifact = runtime_pg.get_run_question_review(run_id, question_id)
    else:
        artifact = store.get_run_question_review(run_id, question_id)
    if not artifact:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="run question detail not found")
    return artifact


def _persist_artifact(artifact: RunQuestionReviewArtifact) -> RunQuestionReviewArtifact:
    if runtime_pg.enabled():
        runtime_pg.upsert_run_question_review(artifact.run_id, artifact.question_id, artifact)
    else:
        store.upsert_run_question_review(artifact.run_id, artifact.question_id, artifact.model_dump(mode="json"))
    return artifact


def _get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    if not profile_id.strip():
        return None
    if runtime_pg.enabled():
        return runtime_pg.get_exp_profile(profile_id)
    return store.exp_profiles.get(profile_id)


def _get_gold_dataset(gold_dataset_id: str) -> Dict[str, Any] | GoldQuestion | Any:
    if runtime_pg.enabled():
        dataset = runtime_pg.get_gold_dataset(gold_dataset_id)
    else:
        dataset = store.gold_datasets.get(gold_dataset_id)
    if not dataset:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="gold dataset not found")
    return dataset


def _find_gold_question_by_dataset_question(gold_dataset_id: str, question_id: str) -> Optional[GoldQuestion]:
    if runtime_pg.enabled():
        return runtime_pg.find_gold_question_by_dataset_question(gold_dataset_id, question_id)
    return store.find_gold_question_by_dataset_question(gold_dataset_id, question_id)


def _upsert_gold_question(question: GoldQuestion) -> None:
    if runtime_pg.enabled():
        runtime_pg.upsert_gold_question(question)
    else:
        store.gold_questions[question.gold_dataset_id][question.gold_question_id] = question


def _answerability_from_response(artifact: RunQuestionReviewArtifact) -> str:
    return "abstain" if artifact.response.abstained else "answerable"


def _stringify_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _normalized_answer_value(candidate: CandidateAnswer) -> str:
    return _stringify_answer(candidate.answer).strip().lower()


def _page_text_for_page_id(page_id: str) -> str:
    if not page_id:
        return ""
    if corpus_pg.enabled():
        page = corpus_pg.get_page(page_id) or {}
    else:
        page = store.pages.get(page_id, {})
    return str(page.get("text") or page.get("page_text_raw") or page.get("page_text_clean") or "")


def _document_title_lookup(artifact: RunQuestionReviewArtifact) -> Dict[str, str]:
    documents = artifact.document_viewer.get("documents", []) if isinstance(artifact.document_viewer, dict) else []
    out: Dict[str, str] = {}
    for row in documents:
        if not isinstance(row, dict):
            continue
        document_id = str(row.get("document_id", "")).strip()
        if not document_id:
            continue
        out[document_id] = str(row.get("title") or row.get("pdf_id") or document_id)
    return out


def _snippet_lookup(artifact: RunQuestionReviewArtifact) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    documents = artifact.document_viewer.get("documents", []) if isinstance(artifact.document_viewer, dict) else []
    for document in documents:
        if not isinstance(document, dict):
            continue
        for page in document.get("pages", []) if isinstance(document.get("pages"), list) else []:
            if not isinstance(page, dict):
                continue
            source_page_id = str(page.get("source_page_id", "")).strip()
            if source_page_id:
                lookup[source_page_id] = {
                    "document_id": str(document.get("document_id", "")).strip(),
                    "doc_title": str(document.get("title") or document.get("document_id") or ""),
                    "snippet": str(page.get("chunk_text", "") or "").strip(),
                    "page_id": str(page.get("page_id", "")).strip(),
                    "page_number": int(page.get("page_num", 0) or 0),
                }
    return lookup


def _evidence_ref_from_source(
    source: Any,
    *,
    source_origin: str,
    title_lookup: Dict[str, str],
    snippet_lookup: Dict[str, Dict[str, Any]],
) -> EvidenceRef:
    if isinstance(source, EvidenceRef):
        ref = source.model_copy()
        ref.source_origin = source_origin
        return ref
    if hasattr(source, "model_dump"):
        payload = source.model_dump(mode="json")
    elif isinstance(source, dict):
        payload = dict(source)
    else:
        payload = {}
    source_page_id = str(payload.get("source_page_id", "")).strip()
    snippet_meta = snippet_lookup.get(source_page_id, {})
    document_id = str(payload.get("document_id") or snippet_meta.get("document_id") or "")
    return EvidenceRef(
        doc_id=document_id or str(payload.get("pdf_id", "")),
        doc_title=title_lookup.get(document_id) or str(snippet_meta.get("doc_title") or ""),
        page_number=int(payload.get("page_num", payload.get("page_number", snippet_meta.get("page_number", 0))) or 0),
        snippet=str(payload.get("snippet") or snippet_meta.get("snippet") or "").strip() or None,
        paragraph_id=str(payload.get("paragraph_id") or payload.get("chunk_id") or "").strip() or None,
        is_used=bool(payload.get("used") or payload.get("is_used")),
        source_origin=source_origin,  # type: ignore[arg-type]
        highlight_offsets=list(payload.get("highlight_offsets") or []),
        source_page_id=source_page_id or None,
        parse_warnings=list(payload.get("parse_warnings") or []),
    )


def _candidate_from_artifact(
    artifact: RunQuestionReviewArtifact,
    *,
    candidate_kind: str,
    run_id: str,
    unavailable_reason: Optional[str] = None,
    label: Optional[str] = None,
) -> CandidateAnswer:
    title_lookup = _document_title_lookup(artifact)
    snippet_lookup = _snippet_lookup(artifact)
    sources = [
        _evidence_ref_from_source(
            source,
            source_origin=candidate_kind,
            title_lookup=title_lookup,
            snippet_lookup=snippet_lookup,
        )
        for source in artifact.response.sources
    ]
    reasoning_summary = None
    if isinstance(artifact.response.debug, dict):
        solver_trace = artifact.response.debug.get("solver_trace")
        if isinstance(solver_trace, dict):
            reasoning_summary = str(
                solver_trace.get("reasoning_summary")
                or solver_trace.get("path")
                or solver_trace.get("abstain_reason")
                or ""
            ).strip() or None
    return CandidateAnswer(
        candidate_id=f"{candidate_kind}:{run_id}:{artifact.question_id}",
        candidate_kind=candidate_kind,  # type: ignore[arg-type]
        answer=artifact.response.answer,
        answerability=_answerability_from_response(artifact),  # type: ignore[arg-type]
        confidence=artifact.response.confidence,
        reasoning_summary=reasoning_summary,
        sources=sources,
        support_status="not_run",
        run_id=run_id,
        created_at=artifact.created_at,
        label=label or candidate_kind.replace("_", " "),
        unavailable_reason=unavailable_reason,
        metadata={
            "route_name": artifact.response.route_name,
            "trace_id": artifact.response.telemetry.trace_id,
            "telemetry_complete": artifact.response.telemetry.telemetry_complete,
        },
    )


def _mini_check_candidate(result: MiniCheckResult, artifact: RunQuestionReviewArtifact) -> CandidateAnswer:
    sources = []
    for source in artifact.accepted_decision.final_sources if artifact.accepted_decision else []:
        if isinstance(source, EvidenceRef):
            sources.append(source.model_copy())
    return CandidateAnswer(
        candidate_id=f"mini_check:{artifact.run_id}:{artifact.question_id}",
        candidate_kind="mini_check",
        answer=result.extracted_answer if result.extracted_answer is not None else result.candidate_answer,
        answerability="answerable" if result.verdict != "insufficient_evidence" else "abstain",
        confidence=result.confidence,
        reasoning_summary=result.rationale,
        sources=sources,
        support_status=result.verdict if result.verdict in {"supported", "not_supported", "insufficient_evidence"} else "not_run",
        run_id=artifact.run_id,
        created_at=result.created_at,
        label="mini-check",
        unavailable_reason=result.unavailable_reason,
        metadata={"conflict_type": result.conflict_type, "model_name": result.model_name},
    )


def _sorted_candidates(candidates: Iterable[CandidateAnswer]) -> List[CandidateAnswer]:
    return sorted(
        candidates,
        key=lambda row: (_CANDIDATE_ORDER.get(row.candidate_kind, 99), row.created_at or _utcnow()),
    )


def _normalized_candidate_bundle(artifact: RunQuestionReviewArtifact) -> List[CandidateAnswer]:
    existing: Dict[str, CandidateAnswer] = {}
    for candidate in artifact.candidate_bundle:
        existing[candidate.candidate_kind] = candidate
    if "system" not in existing:
        existing["system"] = _candidate_from_artifact(artifact, candidate_kind="system", run_id=artifact.run_id, label="System")
    if artifact.mini_check_result and "mini_check" not in existing:
        existing["mini_check"] = _mini_check_candidate(artifact.mini_check_result, artifact)
    return _sorted_candidates(existing.values())


def _source_page_ids(sources: Iterable[EvidenceRef]) -> List[str]:
    out: List[str] = []
    seen = set()
    for source in sources:
        source_page_id = str(source.source_page_id or "").strip()
        if not source_page_id:
            continue
        if source_page_id in seen:
            continue
        seen.add(source_page_id)
        out.append(source_page_id)
    return out


def _history_version_ambiguity(artifact: RunQuestionReviewArtifact) -> bool:
    if artifact.response.route_name != "history_lineage":
        return False
    legal_context = artifact.evidence.get("legal_context_flags", {}) if isinstance(artifact.evidence, dict) else {}
    return bool(isinstance(legal_context, dict) and legal_context.get("is_current_vs_historical_question"))


def _derive_disagreement_flags(artifact: RunQuestionReviewArtifact, candidates: List[CandidateAnswer]) -> List[str]:
    flags = set(str(flag) for flag in artifact.disagreement_flags)
    comparable = [candidate for candidate in candidates if candidate.candidate_kind in {"system", "strong_model", "challenger"}]
    answer_values = {_normalized_answer_value(candidate) for candidate in comparable if _normalized_answer_value(candidate)}
    answerability_values = {candidate.answerability for candidate in comparable}
    source_sets = [set(_source_page_ids(candidate.sources)) for candidate in comparable]

    if len(answer_values) > 1:
        flags.add("answer_conflict")
    if len(answerability_values) > 1:
        flags.add("answerability_conflict")
    if len(source_sets) > 1 and all(source_sets):
        overlap = set.intersection(*source_sets) if source_sets else set()
        if not overlap:
            flags.add("sources_conflict")
    if artifact.mini_check_result and artifact.mini_check_result.verdict == "not_supported":
        flags.add("mini_check_fail")
    system_candidate = next((candidate for candidate in candidates if candidate.candidate_kind == "system"), None)
    accepted_sources = artifact.accepted_decision.final_sources if artifact.accepted_decision else []
    if not _source_page_ids(accepted_sources or (system_candidate.sources if system_candidate else [])):
        flags.add("missing_sources")
    telemetry = artifact.response.telemetry
    if not telemetry.telemetry_complete or not str(telemetry.trace_id).strip():
        flags.add("telemetry_bad")
    if any(not SOURCE_PAGE_ID_PATTERN.fullmatch(source_page_id) for candidate in comparable for source_page_id in _source_page_ids(candidate.sources)):
        flags.add("contract_failure_present")
    if not artifact.evidence or not isinstance(artifact.evidence.get("telemetry_shadow", {}), dict):
        flags.add("trace_incomplete")
    if _history_version_ambiguity(artifact):
        flags.add("history_version_ambiguity")
    return sorted(flags)


def _derive_status(artifact: RunQuestionReviewArtifact, candidates: List[CandidateAnswer], flags: List[str]) -> str:
    if artifact.status == "exported":
        return artifact.status
    if artifact.accepted_decision and artifact.accepted_decision.locked_at:
        return "gold_locked"
    if not candidates:
        return "not_ready"
    if artifact.accepted_decision:
        return "review_in_progress"
    auto_lock_flags = {"answer_conflict", "answerability_conflict", "sources_conflict", "contract_failure_present", "telemetry_bad", "history_version_ambiguity"}
    comparable = [candidate for candidate in candidates if candidate.candidate_kind in {"system", "strong_model", "challenger"}]
    source_sets = [set(_source_page_ids(candidate.sources)) for candidate in comparable if _source_page_ids(candidate.sources)]
    overlap_exists = bool(source_sets and set.intersection(*source_sets))
    if comparable and len(comparable) >= 2 and not auto_lock_flags.intersection(flags) and overlap_exists:
        return "auto_lock_candidate"
    return "needs_review"


def _artifact_to_record(artifact: RunQuestionReviewArtifact) -> QuestionReviewRecord:
    candidates = _normalized_candidate_bundle(artifact)
    flags = _derive_disagreement_flags(artifact, candidates)
    status = _derive_status(artifact, candidates, flags)
    question_payload = artifact.question if isinstance(artifact.question, dict) else {}
    route_decision = artifact.evidence.get("route_decision", {}) if isinstance(artifact.evidence, dict) else {}
    question_metadata = {
        "dataset_id": question_payload.get("dataset_id"),
        "source": question_payload.get("source"),
        "difficulty": question_payload.get("difficulty"),
        "route_hint": question_payload.get("route_hint"),
        "tags": question_payload.get("tags", []),
    }
    return QuestionReviewRecord(
        question_id=artifact.question_id,
        question=str(question_payload.get("question") or artifact.question_id),
        answer_type=str(question_payload.get("answer_type") or artifact.response.answer_type),
        primary_route=str(artifact.response.route_name or route_decision.get("raw_route") or ""),
        document_scope=str(route_decision.get("document_scope_guess") or ""),
        risk_tier="high" if any(flag in flags for flag in {"answer_conflict", "sources_conflict", "telemetry_bad", "contract_failure_present"}) else "medium" if flags else "low",
        status=status,  # type: ignore[arg-type]
        disagreement_flags=flags,
        current_run_id=artifact.run_id,
        trace_id=str(artifact.response.telemetry.trace_id or ""),
        candidate_bundle=candidates,
        accepted_decision=artifact.accepted_decision,
        mini_check_result=artifact.mini_check_result,
        report_summary=artifact.report_summary,
        question_metadata=question_metadata,
        evidence=artifact.evidence,
        document_viewer=artifact.document_viewer,
        promotion_preview=artifact.promotion_preview,
        comparison_context=artifact.comparison_context,
        created_at=artifact.created_at,
        updated_at=artifact.accepted_decision.updated_at if artifact.accepted_decision and artifact.accepted_decision.updated_at else artifact.created_at,
    )


def _review_summary(run_id: str, records: List[QuestionReviewRecord]) -> ReviewRunSummary:
    histogram: Dict[str, int] = {}
    route_breakdown: Dict[str, int] = {}
    answer_type_breakdown: Dict[str, int] = {}
    for record in records:
        route_breakdown[record.primary_route or "unknown"] = route_breakdown.get(record.primary_route or "unknown", 0) + 1
        answer_type_breakdown[record.answer_type] = answer_type_breakdown.get(record.answer_type, 0) + 1
        for flag in record.disagreement_flags:
            histogram[flag] = histogram.get(flag, 0) + 1
    return ReviewRunSummary(
        run_id=run_id,
        total_questions=len(records),
        auto_lock_candidates=sum(1 for record in records if record.status == "auto_lock_candidate"),
        locked_gold_count=sum(1 for record in records if record.status == "gold_locked"),
        needs_review_count=sum(1 for record in records if record.status == "needs_review"),
        disagreement_histogram=histogram,
        answerability_conflict_count=histogram.get("answerability_conflict", 0),
        source_conflict_count=histogram.get("sources_conflict", 0),
        mini_check_failure_count=histogram.get("mini_check_fail", 0),
        route_breakdown=route_breakdown,
        answer_type_breakdown=answer_type_breakdown,
    )


def _matches_search(record: QuestionReviewRecord, search: str) -> bool:
    token = search.strip().lower()
    if not token:
        return True
    haystack = " ".join(
        [
            record.question_id,
            record.question,
            record.primary_route or "",
            record.document_scope or "",
            " ".join(source.doc_id for candidate in record.candidate_bundle for source in candidate.sources),
            " ".join((source.doc_title or "") for candidate in record.candidate_bundle for source in candidate.sources),
        ]
    ).lower()
    return token in haystack


def _filter_records(
    records: List[QuestionReviewRecord],
    *,
    route: str,
    answer_type: str,
    status: str,
    disagreement_only: bool,
    needs_review_only: bool,
    gold_locked_only: bool,
    no_answer_only: bool,
    missing_sources_only: bool,
    contract_failures_only: bool,
    search: str,
) -> List[QuestionReviewRecord]:
    out: List[QuestionReviewRecord] = []
    for record in records:
        if route and record.primary_route != route:
            continue
        if answer_type and record.answer_type != answer_type:
            continue
        if status and record.status != status:
            continue
        if disagreement_only and not record.disagreement_flags:
            continue
        if needs_review_only and record.status != "needs_review":
            continue
        if gold_locked_only and record.status != "gold_locked":
            continue
        if no_answer_only and not any(candidate.answerability == "abstain" for candidate in record.candidate_bundle if candidate.candidate_kind == "system"):
            continue
        if missing_sources_only and "missing_sources" not in record.disagreement_flags:
            continue
        if contract_failures_only and "contract_failure_present" not in record.disagreement_flags and "telemetry_bad" not in record.disagreement_flags:
            continue
        if not _matches_search(record, search):
            continue
        out.append(record)
    return out


def _build_pdf_preview_payload(artifact: RunQuestionReviewArtifact, document_id: str = "", page_id: str = "") -> Dict[str, Any]:
    viewer = artifact.document_viewer if isinstance(artifact.document_viewer, dict) else {}
    documents = viewer.get("documents", []) if isinstance(viewer.get("documents"), list) else []
    selected_document = next((row for row in documents if isinstance(row, dict) and str(row.get("document_id")) == document_id), None)
    if selected_document is None:
        selected_document = next((row for row in documents if isinstance(row, dict)), {})
    pages = selected_document.get("pages", []) if isinstance(selected_document, dict) and isinstance(selected_document.get("pages"), list) else []
    selected_page = next((row for row in pages if isinstance(row, dict) and str(row.get("page_id")) == page_id), None)
    if selected_page is None:
        selected_page = next((row for row in pages if isinstance(row, dict) and row.get("used")), None)
    if selected_page is None:
        selected_page = next((row for row in pages if isinstance(row, dict)), {})
    selected_page_id = str(selected_page.get("page_id", "")).strip()
    return {
        "run_id": artifact.run_id,
        "question_id": artifact.question_id,
        "document_id": str(selected_document.get("document_id", "")).strip(),
        "title": str(selected_document.get("title") or selected_document.get("document_id") or ""),
        "pdf_id": str(selected_document.get("pdf_id") or ""),
        "file_url": str(selected_document.get("file_url") or ""),
        "page": {
            "page_id": selected_page_id,
            "page_num": int(selected_page.get("page_num", 0) or 0),
            "source_page_id": str(selected_page.get("source_page_id") or ""),
            "used": bool(selected_page.get("used")),
            "chunk_text": str(selected_page.get("chunk_text") or ""),
            "page_text": _page_text_for_page_id(selected_page_id),
            "parse_warnings": list(selected_page.get("parse_warnings") or []),
        },
        "fallback": {
            "doc_id": str(selected_document.get("document_id") or ""),
            "page_number": int(selected_page.get("page_num", 0) or 0),
            "text": _page_text_for_page_id(selected_page_id) or str(selected_page.get("chunk_text") or ""),
            "parse_warnings": list(selected_page.get("parse_warnings") or []),
        },
    }


def _runtime_policy_from_profile(profile: Dict[str, Any]) -> RuntimePolicy:
    payload = profile.get("runtime_policy")
    if isinstance(payload, dict):
        candidate = dict(payload)
        if not str(candidate.get("scoring_policy_version", "")).strip():
            candidate["scoring_policy_version"] = "contest_v2026_public_rules_v1"
        return RuntimePolicy(**candidate)
    return RuntimePolicy(
        use_llm=False,
        max_candidate_pages=8,
        max_context_paragraphs=8,
        page_index_base_export=0,
        scoring_policy_version="contest_v2026_public_rules_v1",
        allow_dense_fallback=True,
        return_debug_trace=False,
    )


def _build_query_from_record(record: QuestionReviewRecord, profile: Dict[str, Any]) -> qa_router.QueryRequest:
    question = Question(
        id=record.question_id,
        dataset_id=record.question_metadata.get("dataset_id"),
        question=record.question,
        answer_type=record.answer_type,  # type: ignore[arg-type]
        source=record.question_metadata.get("source", "manual"),
        difficulty=record.question_metadata.get("difficulty", "easy"),
        route_hint=record.question_metadata.get("route_hint"),
        tags=list(record.question_metadata.get("tags", [])),
    )
    return qa_router.QueryRequest(
        project_id=str(profile.get("project_id", "")),
        question=question,
        runtime_policy=_runtime_policy_from_profile(profile),
    )


async def _generate_candidate_from_profile(
    artifact: RunQuestionReviewArtifact,
    record: QuestionReviewRecord,
    *,
    profile_id: str,
    candidate_kind: str,
) -> CandidateAnswer:
    profile = _get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"profile not found: {profile_id}")
    request_payload = _build_query_from_record(record, profile)
    response, answer_ctx = await qa_router._answer_query(request_payload)
    generated_run_id = f"{artifact.run_id}:{candidate_kind}:{uuid4()}"
    generated_artifact = qa_router._build_review_artifact(
        run_id=generated_run_id,
        query_request=request_payload,
        response=response,
        candidates=answer_ctx["candidates"],
        page_refs=answer_ctx["page_refs"],
        retrieval_profile_id=answer_ctx["retrieval_profile_id"],
        solver_trace=answer_ctx["solver_trace"],
        evidence_selection_trace=answer_ctx["evidence_selection_trace"],
        route_recall_diagnostics=answer_ctx["route_recall_diagnostics"],
        latency_budget_assertion=answer_ctx["latency_budget_assertion"],
    )
    candidate = _candidate_from_artifact(
        generated_artifact,
        candidate_kind=candidate_kind,
        run_id=generated_run_id,
        label="Strong model" if candidate_kind == "strong_model" else "Challenger",
    )
    candidate.metadata["profile_id"] = profile_id
    candidate.metadata["generated_from_profile"] = True
    return candidate


def _load_prompt_contract() -> Dict[str, Any]:
    return json.loads(MINI_CHECK_PROMPT_PATH.read_text(encoding="utf-8"))


def _safe_json_load(text: str) -> Dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=f"mini-check response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail="mini-check response must be a JSON object")
    return payload


def _review_record_payload(record: QuestionReviewRecord) -> Dict[str, Any]:
    return record.model_dump(mode="json")


def _report_markdown(summary: ReviewRunSummary, records: List[QuestionReviewRecord]) -> str:
    lines = [
        f"# Review Report: {summary.run_id}",
        "",
        f"- Total questions: {summary.total_questions}",
        f"- Auto-lock candidates: {summary.auto_lock_candidates}",
        f"- Gold locked: {summary.locked_gold_count}",
        f"- Needs review: {summary.needs_review_count}",
        f"- Mini-check failures: {summary.mini_check_failure_count}",
        "",
        "## Questions",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"### {record.question_id}",
                f"- Status: {record.status}",
                f"- Route: {record.primary_route or '-'}",
                f"- Answer type: {record.answer_type}",
                f"- Flags: {', '.join(record.disagreement_flags) if record.disagreement_flags else 'none'}",
                f"- Accepted decision: {record.accepted_decision.final_answer if record.accepted_decision else 'not set'}",
                "",
            ]
        )
    return "\n".join(lines)


@router.get("/questions")
def list_review_questions(
    run_id: str = Query(..., alias="run_id"),
    route: str = Query(default=""),
    answer_type: str = Query(default=""),
    status: str = Query(default=""),
    disagreement_only: bool = Query(default=False),
    needs_review_only: bool = Query(default=False),
    gold_locked_only: bool = Query(default=False),
    no_answer_only: bool = Query(default=False),
    missing_sources_only: bool = Query(default=False),
    contract_failures_only: bool = Query(default=False),
    search: str = Query(default=""),
) -> dict:
    _ensure_review_enabled()
    _get_run(run_id)
    records = [_artifact_to_record(artifact) for artifact in _list_run_review_artifacts(run_id).values()]
    filtered = _filter_records(
        records,
        route=route.strip(),
        answer_type=answer_type.strip(),
        status=status.strip(),
        disagreement_only=disagreement_only,
        needs_review_only=needs_review_only,
        gold_locked_only=gold_locked_only,
        no_answer_only=no_answer_only,
        missing_sources_only=missing_sources_only,
        contract_failures_only=contract_failures_only,
        search=search,
    )
    return {
        "run_id": run_id,
        "items": [_review_record_payload(record) for record in filtered],
        "total": len(filtered),
        "summary": _review_summary(run_id, records).model_dump(mode="json"),
    }


@router.get("/questions/{questionId}")
def get_review_question(questionId: str, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    return _artifact_to_record(artifact).model_dump(mode="json")


@router.get("/questions/{questionId}/pdf-preview")
def get_pdf_preview(
    questionId: str,
    run_id: str = Query(..., alias="run_id"),
    document_id: str = Query(default=""),
    page_id: str = Query(default=""),
) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    return _build_pdf_preview_payload(artifact, document_id=document_id.strip(), page_id=page_id.strip())


@router.get("/report/{runId}")
def get_review_report(runId: str) -> dict:
    _ensure_review_enabled()
    _get_run(runId)
    records = [_artifact_to_record(artifact) for artifact in _list_run_review_artifacts(runId).values()]
    return {
        "run_id": runId,
        "items": [_review_record_payload(record) for record in records],
        "summary": _review_summary(runId, records).model_dump(mode="json"),
    }


@router.post("/questions/{questionId}/generate-candidates")
async def generate_candidates(questionId: str, payload: ReviewCandidateGenerationRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    record = _artifact_to_record(artifact)
    candidates = {candidate.candidate_kind: candidate for candidate in _normalized_candidate_bundle(artifact)}

    generated: List[CandidateAnswer] = []
    explicit_sources = [
        ("strong_model", payload.strong_run_id.strip() if payload.strong_run_id else ""),
        ("challenger", payload.challenger_run_id.strip() if payload.challenger_run_id else ""),
    ]
    for candidate_kind, source_run_id in explicit_sources:
        if not source_run_id:
            continue
        source_artifact = _get_run_review_artifact(source_run_id, questionId)
        candidates[candidate_kind] = _candidate_from_artifact(
            source_artifact,
            candidate_kind=candidate_kind,
            run_id=source_run_id,
            label="Strong model" if candidate_kind == "strong_model" else "Challenger",
        )
        candidates[candidate_kind].metadata["source_run_id"] = source_run_id
        generated.append(candidates[candidate_kind])

    profile_sources = [
        ("strong_model", payload.strong_profile_id.strip() if payload.strong_profile_id else ""),
        ("challenger", payload.challenger_profile_id.strip() if payload.challenger_profile_id else ""),
    ]
    for candidate_kind, profile_id in profile_sources:
        if not profile_id or candidate_kind in {candidate.candidate_kind for candidate in generated}:
            continue
        candidates[candidate_kind] = await _generate_candidate_from_profile(
            artifact,
            record,
            profile_id=profile_id,
            candidate_kind=candidate_kind,
        )
        generated.append(candidates[candidate_kind])

    artifact.candidate_bundle = _sorted_candidates(candidates.values())
    artifact.comparison_context = {
        **artifact.comparison_context,
        "strong_run_id": payload.strong_run_id,
        "challenger_run_id": payload.challenger_run_id,
        "strong_profile_id": payload.strong_profile_id,
        "challenger_profile_id": payload.challenger_profile_id,
    }
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = _derive_status(artifact, artifact.candidate_bundle, artifact.disagreement_flags)  # type: ignore[assignment]
    _persist_artifact(artifact)
    _append_review_audit(
        "review_candidates_generated",
        f"{run_id}:{questionId}",
        {
            "reviewer": payload.reviewer,
            "generated_candidate_kinds": [candidate.candidate_kind for candidate in generated],
        },
    )
    return {
        "run_id": run_id,
        "question_id": questionId,
        "generated": [candidate.model_dump(mode="json") for candidate in generated],
        "record": _artifact_to_record(artifact).model_dump(mode="json"),
    }


@router.post("/questions/{questionId}/mini-check")
async def run_mini_check(questionId: str, payload: ReviewMiniCheckRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    _ensure_mini_check_enabled()
    if not llm_client.config.enabled:
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="mini-check unavailable: Azure OpenAI is not configured")
    artifact = _get_run_review_artifact(run_id, questionId)
    prompt_contract = _load_prompt_contract()
    prompt_payload = {
        "question_id": questionId,
        "question": str((artifact.question or {}).get("question") or ""),
        "answer_type": payload.answer_type,
        "candidate_answer": payload.candidate_answer,
        "candidate_answerability": payload.candidate_answerability,
        "evidence": [
            {
                "doc_id": evidence.doc_id,
                "page_number": evidence.page_number,
                "snippet": evidence.snippet or "",
            }
            for evidence in payload.evidence
        ],
    }
    prompt = "\n\n".join(
        [
            "Prompt contract:",
            json.dumps(prompt_contract, ensure_ascii=False, indent=2),
            "Payload:",
            json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        ]
    )
    raw_response, _usage = await llm_client.complete_chat(
        prompt,
        system_prompt=str(prompt_contract.get("system", "")),
        user_context={"job": "review_mini_check", "question_id": questionId},
        max_tokens=220,
        temperature=0.0,
    )
    parsed = _safe_json_load(raw_response)
    result = MiniCheckResult(
        verdict=str(parsed.get("verdict", "insufficient_evidence")),
        extracted_answer=parsed.get("extracted_answer"),
        confidence=float(parsed.get("confidence", 0.0) or 0.0),
        rationale=str(parsed.get("rationale", "")).strip(),
        conflict_type=str(parsed.get("conflict_type", "none")),
        candidate_answer=payload.candidate_answer,
        candidate_kind=payload.candidate_kind,
        created_at=_utcnow(),
        model_name=llm_client.config.deployment,
    )
    artifact.mini_check_result = result
    bundle = {candidate.candidate_kind: candidate for candidate in _normalized_candidate_bundle(artifact)}
    bundle["mini_check"] = CandidateAnswer(
        candidate_id=f"mini_check:{run_id}:{questionId}",
        candidate_kind="mini_check",
        answer=result.extracted_answer if result.extracted_answer is not None else payload.candidate_answer,
        answerability="answerable" if result.verdict != "insufficient_evidence" else "abstain",
        confidence=result.confidence,
        reasoning_summary=result.rationale,
        sources=payload.evidence,
        support_status=result.verdict,
        run_id=run_id,
        created_at=result.created_at,
        label="Mini-check",
        metadata={"conflict_type": result.conflict_type, "candidate_kind": payload.candidate_kind},
    )
    artifact.candidate_bundle = _sorted_candidates(bundle.values())
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = _derive_status(artifact, artifact.candidate_bundle, artifact.disagreement_flags)  # type: ignore[assignment]
    _persist_artifact(artifact)
    _append_review_audit(
        "review_mini_check_executed",
        f"{run_id}:{questionId}",
        {"reviewer": payload.reviewer, "candidate_kind": payload.candidate_kind, "verdict": result.verdict},
    )
    return {
        "run_id": run_id,
        "question_id": questionId,
        "mini_check_result": result.model_dump(mode="json"),
        "record": _artifact_to_record(artifact).model_dump(mode="json"),
    }


@router.post("/questions/{questionId}/accept-candidate")
def accept_candidate(questionId: str, payload: ReviewAcceptCandidateRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    candidates = {candidate.candidate_kind: candidate for candidate in _normalized_candidate_bundle(artifact)}
    candidate = candidates.get(payload.candidate_kind)
    if not candidate:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"candidate not available: {payload.candidate_kind}")
    artifact.accepted_decision = AcceptedDecision(
        final_answer=candidate.answer,
        final_sources=candidate.sources,
        answerability=candidate.answerability,
        decision_source=payload.candidate_kind,
        reviewer=payload.reviewer,
        reviewer_confidence=payload.reviewer_confidence,
        adjudication_note=payload.adjudication_note,
        updated_at=_utcnow(),
    )
    artifact.candidate_bundle = _sorted_candidates(candidates.values())
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = _derive_status(artifact, artifact.candidate_bundle, artifact.disagreement_flags)  # type: ignore[assignment]
    _persist_artifact(artifact)
    _append_review_audit(
        "review_candidate_accepted",
        f"{run_id}:{questionId}",
        {"reviewer": payload.reviewer, "candidate_kind": payload.candidate_kind},
    )
    return _artifact_to_record(artifact).model_dump(mode="json")


@router.post("/questions/{questionId}/custom-decision")
def custom_decision(questionId: str, payload: ReviewCustomDecisionRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    artifact.accepted_decision = AcceptedDecision(
        final_answer=payload.final_answer,
        final_sources=payload.final_sources,
        answerability=payload.answerability,
        decision_source="custom",
        reviewer=payload.reviewer,
        reviewer_confidence=payload.reviewer_confidence,
        adjudication_note=payload.adjudication_note,
        updated_at=_utcnow(),
    )
    artifact.candidate_bundle = _normalized_candidate_bundle(artifact)
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = _derive_status(artifact, artifact.candidate_bundle, artifact.disagreement_flags)  # type: ignore[assignment]
    _persist_artifact(artifact)
    _append_review_audit(
        "review_custom_decision_saved",
        f"{run_id}:{questionId}",
        {"reviewer": payload.reviewer},
    )
    return _artifact_to_record(artifact).model_dump(mode="json")


@router.post("/questions/{questionId}/lock-gold")
def lock_gold(questionId: str, payload: ReviewLockGoldRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    dataset = _get_gold_dataset(payload.gold_dataset_id)
    if dataset.status == "locked":
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="gold dataset is locked and immutable")
    decision = artifact.accepted_decision
    if not decision:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="accepted decision is required before lock-gold")
    page_ids = _source_page_ids(decision.final_sources)
    if not page_ids:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="accepted decision has no source pages")
    existing = _find_gold_question_by_dataset_question(payload.gold_dataset_id, questionId)
    note = payload.adjudication_note or decision.adjudication_note
    if existing:
        existing.canonical_answer = decision.final_answer
        existing.answer_type = str(artifact.question.get("answer_type") or artifact.response.answer_type)
        existing.source_sets = [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": page_ids, "notes": note}]
        existing.review_status = "locked"
        if payload.reviewer:
            existing.reviewers = sorted(set([*existing.reviewers, payload.reviewer]))
        existing.notes = note
        _upsert_gold_question(existing)
        gold_question = existing
    else:
        if runtime_pg.enabled():
            gold_question = runtime_pg.add_gold_question(
                payload.gold_dataset_id,
                {
                    "question_id": questionId,
                    "canonical_answer": decision.final_answer,
                    "answer_type": str(artifact.question.get("answer_type") or artifact.response.answer_type),
                    "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": page_ids, "notes": note}],
                    "review_status": "locked",
                    "reviewers": [payload.reviewer] if payload.reviewer else [],
                    "notes": note,
                },
            )
        else:
            gold_question = store.add_gold_question(
                payload.gold_dataset_id,
                {
                    "question_id": questionId,
                    "canonical_answer": decision.final_answer,
                    "answer_type": str(artifact.question.get("answer_type") or artifact.response.answer_type),
                    "source_sets": [{"source_set_id": str(uuid4()), "is_primary": True, "page_ids": page_ids, "notes": note}],
                    "review_status": "locked",
                    "reviewers": [payload.reviewer] if payload.reviewer else [],
                    "notes": note,
                },
            )
    artifact.accepted_decision = AcceptedDecision(
        final_answer=decision.final_answer,
        final_sources=decision.final_sources,
        answerability=decision.answerability,
        decision_source=decision.decision_source,
        reviewer=payload.reviewer or decision.reviewer,
        reviewer_confidence=payload.reviewer_confidence if payload.reviewer_confidence is not None else decision.reviewer_confidence,
        adjudication_note=note,
        locked_at=_utcnow(),
        updated_at=_utcnow(),
        gold_dataset_id=payload.gold_dataset_id,
        gold_question_id=gold_question.gold_question_id,
    )
    artifact.candidate_bundle = _normalized_candidate_bundle(artifact)
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = "gold_locked"
    _persist_artifact(artifact)
    _append_review_audit(
        "review_gold_locked",
        f"{run_id}:{questionId}",
        {"reviewer": payload.reviewer, "gold_dataset_id": payload.gold_dataset_id},
    )
    return _artifact_to_record(artifact).model_dump(mode="json")


@router.post("/questions/{questionId}/unlock-gold")
def unlock_gold(questionId: str, payload: ReviewUnlockGoldRequest, run_id: str = Query(..., alias="run_id")) -> dict:
    _ensure_review_enabled()
    artifact = _get_run_review_artifact(run_id, questionId)
    dataset = _get_gold_dataset(payload.gold_dataset_id)
    if dataset.status == "locked":
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="gold dataset is locked and immutable")
    gold_question = _find_gold_question_by_dataset_question(payload.gold_dataset_id, questionId)
    if gold_question:
        gold_question.review_status = "draft"
        if payload.reviewer:
            gold_question.reviewers = sorted(set([*gold_question.reviewers, payload.reviewer]))
        if payload.adjudication_note:
            gold_question.notes = f"{gold_question.notes or ''}{chr(10) if gold_question.notes else ''}{payload.adjudication_note}"
        _upsert_gold_question(gold_question)
    if artifact.accepted_decision:
        artifact.accepted_decision.locked_at = None
        artifact.accepted_decision.updated_at = _utcnow()
    artifact.candidate_bundle = _normalized_candidate_bundle(artifact)
    artifact.disagreement_flags = _derive_disagreement_flags(artifact, artifact.candidate_bundle)
    artifact.status = "review_in_progress"
    _persist_artifact(artifact)
    _append_review_audit(
        "review_gold_unlocked",
        f"{run_id}:{questionId}",
        {"reviewer": payload.reviewer, "gold_dataset_id": payload.gold_dataset_id},
    )
    return _artifact_to_record(artifact).model_dump(mode="json")


@router.post("/report/{runId}/export")
def export_review_report(runId: str, payload: ReviewExportRequest) -> dict:
    _ensure_review_enabled()
    _get_run(runId)
    records = [_artifact_to_record(artifact) for artifact in _list_run_review_artifacts(runId).values()]
    summary = _review_summary(runId, records)
    output_dir = REPORTS_DIR / runId
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "review_report.json"
    md_path = output_dir / "review_report.md"
    status_path = output_dir / "question_status.jsonl"
    bundle_path = output_dir / "candidate_bundle.jsonl"
    json_payload = {
        "run_id": runId,
        "summary": summary.model_dump(mode="json"),
        "items": [_review_record_payload(record) for record in records],
    }
    if payload.format in {"json", "both"}:
        json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        status_path.write_text(
            "\n".join(json.dumps({"question_id": record.question_id, "status": record.status, "flags": record.disagreement_flags}, ensure_ascii=False) for record in records),
            encoding="utf-8",
        )
        bundle_path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "question_id": record.question_id,
                        "candidate_bundle": [candidate.model_dump(mode="json") for candidate in record.candidate_bundle],
                    },
                    ensure_ascii=False,
                )
                for record in records
            ),
            encoding="utf-8",
        )
    if payload.format in {"markdown", "both"}:
        md_path.write_text(_report_markdown(summary, records), encoding="utf-8")
    for artifact in _list_run_review_artifacts(runId).values():
        artifact.status = "exported"
        artifact.report_summary = {
            **artifact.report_summary,
            "exported_at": _utcnow().isoformat(),
            "artifact_dir": str(output_dir),
        }
        _persist_artifact(artifact)
    _append_review_audit("review_report_exported", runId, {"reviewer": payload.reviewer, "format": payload.format})
    return {
        "run_id": runId,
        "artifact_dir": output_dir.as_uri(),
        "review_report_json": json_path.as_uri(),
        "review_report_markdown": md_path.as_uri(),
        "question_status_jsonl": status_path.as_uri(),
        "candidate_bundle_jsonl": bundle_path.as_uri(),
        "summary": summary.model_dump(mode="json"),
    }
