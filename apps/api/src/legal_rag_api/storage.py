"""In-memory stores used by the bootstrap implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

from packages.contracts.corpus_scope import resolve_corpus_import_project_id

from .contracts import (
    CorpusEnrichmentJob,
    EvalRun,
    GoldDataset,
    GoldQuestion,
    RunQuestionReviewArtifact,
    QueryResponse,
    ScoringPolicy,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_id() -> str:
    return str(uuid4())


@dataclass
class InMemoryStore:
    feature_flags: Dict[str, bool] = field(default_factory=dict)
    documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    document_bases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    law_documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    regulation_documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    enactment_notice_documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    paragraphs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    chunk_bases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    law_chunk_facets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    regulation_chunk_facets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    enactment_notice_chunk_facets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_chunk_facets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    relation_edges: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    chunk_search_documents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ontology_registry_entries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    chunk_ontology_assertions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    document_ontology_views: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    corpus_enrichment_jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_extraction_runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_document_extractions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_chunk_extractions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    case_extraction_qc_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    datasets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    run_questions: Dict[str, Dict[str, QueryResponse]] = field(default_factory=dict)
    run_question_reviews: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    eval_runs: Dict[str, EvalRun] = field(default_factory=dict)
    gold_datasets: Dict[str, GoldDataset] = field(default_factory=dict)
    gold_questions: Dict[str, Dict[str, GoldQuestion]] = field(default_factory=dict)
    synth_jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    synth_candidates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    import_jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    scoring_policies: Dict[str, ScoringPolicy] = field(default_factory=dict)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)
    question_telemetry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    corpus_jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    config_versions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_experiments: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_stage_cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_scores: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exp_question_metrics: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    exp_artifacts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    exp_ops_log: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.feature_flags:
            self.feature_flags = {
                "canonical_chunk_model_v1": os.getenv("CANONICAL_CHUNK_MODEL_V1", "1") not in {"0", "false", "False"},
                "experiment_platform_v1": os.getenv("EXPERIMENT_PLATFORM_V1", "1") not in {"0", "false", "False"},
                "review_console_v1": os.getenv("REVIEW_CONSOLE_V1", "1") not in {"0", "false", "False"},
                "review_mini_check_v1": os.getenv("REVIEW_MINI_CHECK_V1", "1") not in {"0", "false", "False"},
            }
        if not self.scoring_policies:
            self.scoring_policies["contest_v2026_public_rules_v1"] = ScoringPolicy(
                policy_version="contest_v2026_public_rules_v1",
                policy_type="contest_emulation",
                beta=2.5,
                ttft_curve={
                    "mode": "piecewise_linear_avg_ttft",
                    "best_seconds": 1.0,
                    "best_factor": 1.05,
                    "worst_seconds": 5.0,
                    "worst_factor": 0.85,
                },
                telemetry_policy="run_level_factor",
            )

    # ---------------------------------------------
    # Corpus
    # ---------------------------------------------
    def add_document(self, document: Dict[str, Any]) -> str:
        document_id = document.get("document_id") or _gen_id()
        document["document_id"] = document_id
        self.documents[document_id] = document
        return document_id

    def upsert_page(self, page: Dict[str, Any]) -> str:
        page_id = page.get("page_id") or _gen_id()
        page["page_id"] = page_id
        self.pages[page_id] = page
        return page_id

    def upsert_paragraph(self, paragraph: Dict[str, Any]) -> str:
        paragraph_id = paragraph.get("paragraph_id") or _gen_id()
        paragraph["paragraph_id"] = paragraph_id
        self.paragraphs[paragraph_id] = paragraph
        return paragraph_id

    def upsert_relation_edge(self, edge: Dict[str, Any]) -> str:
        edge_id = edge.get("edge_id") or _gen_id()
        edge["edge_id"] = edge_id
        self.relation_edges[edge_id] = edge
        return edge_id

    def upsert_chunk_search_document(self, chunk_doc: Dict[str, Any]) -> str:
        chunk_id = chunk_doc.get("chunk_id") or _gen_id()
        chunk_doc["chunk_id"] = chunk_id
        self.chunk_search_documents[chunk_id] = chunk_doc
        return chunk_id

    def upsert_ontology_registry_entry(self, payload: Dict[str, Any]) -> str:
        entry_id = payload.get("entry_id") or _gen_id()
        payload["entry_id"] = entry_id
        self.ontology_registry_entries[entry_id] = payload
        return entry_id

    def upsert_chunk_ontology_assertion(self, payload: Dict[str, Any]) -> str:
        assertion_id = payload.get("assertion_id") or _gen_id()
        payload["assertion_id"] = assertion_id
        self.chunk_ontology_assertions[assertion_id] = payload
        return assertion_id

    def upsert_document_ontology_view(self, payload: Dict[str, Any]) -> str:
        document_id = str(payload.get("document_id") or "")
        if not document_id:
            document_id = _gen_id()
            payload["document_id"] = document_id
        self.document_ontology_views[document_id] = payload
        return document_id

    def create_corpus_enrichment_job(
        self,
        *,
        project_id: str,
        import_job_id: str,
        processing_profile_version: str,
        document_count: int,
        chunk_count: int,
    ) -> CorpusEnrichmentJob:
        now = _utcnow()
        job = CorpusEnrichmentJob(
            job_id=_gen_id(),
            project_id=project_id,
            import_job_id=import_job_id,
            processing_profile_version=processing_profile_version,
            status="queued",
            document_count=document_count,
            chunk_count=chunk_count,
            processed_document_count=0,
            processed_chunk_count=0,
            candidate_entry_count=0,
            active_entry_count=0,
            created_at=now,
            updated_at=now,
        )
        self.corpus_enrichment_jobs[job.job_id] = job.model_dump(mode="json")
        return job

    def update_corpus_enrichment_job(self, job_id: str, patch: Dict[str, Any]) -> Optional[CorpusEnrichmentJob]:
        current = self.corpus_enrichment_jobs.get(job_id)
        if not isinstance(current, dict):
            return None
        merged = {**current, **patch, "updated_at": _utcnow().isoformat()}
        job = CorpusEnrichmentJob(**merged)
        self.corpus_enrichment_jobs[job_id] = job.model_dump(mode="json")
        return job

    def create_case_extraction_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(payload.get("run_id") or _gen_id())
        now = _utcnow().isoformat()
        row = {
            **payload,
            "run_id": run_id,
            "started_at": str(payload.get("started_at") or now),
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }
        self.case_extraction_runs[run_id] = row
        return row

    def update_case_extraction_run(self, run_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.case_extraction_runs.get(run_id)
        if not isinstance(current, dict):
            return None
        merged = {**current, **patch, "updated_at": _utcnow().isoformat()}
        self.case_extraction_runs[run_id] = merged
        return merged

    def get_case_extraction_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        value = self.case_extraction_runs.get(run_id)
        return value.copy() if isinstance(value, dict) else None

    def list_case_extraction_runs(
        self,
        *,
        document_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        rows = list(self.case_extraction_runs.values())
        if document_id:
            rows = [item for item in rows if str(item.get("document_id", "")) == str(document_id)]
        if pipeline_name:
            rows = [item for item in rows if str(item.get("pipeline_name", "")) == str(pipeline_name)]
        rows = sorted(rows, key=lambda item: str(item.get("started_at", "")), reverse=True)
        return rows[: max(1, limit)]

    def upsert_case_document_extraction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document_extraction_id = str(payload.get("document_extraction_id") or _gen_id())
        now = _utcnow().isoformat()
        row = {
            **payload,
            "document_extraction_id": document_extraction_id,
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }
        self.case_document_extractions[document_extraction_id] = row
        return row

    def get_case_document_extraction(self, document_extraction_id: str) -> Optional[Dict[str, Any]]:
        value = self.case_document_extractions.get(document_extraction_id)
        return value.copy() if isinstance(value, dict) else None

    def list_case_document_extractions(
        self,
        *,
        document_id: Optional[str] = None,
        run_id: Optional[str] = None,
        active_only: bool = False,
        schema_version: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        rows = list(self.case_document_extractions.values())
        if document_id:
            rows = [item for item in rows if str(item.get("document_id", "")) == str(document_id)]
        if run_id:
            rows = [item for item in rows if str(item.get("run_id", "")) == str(run_id)]
        if schema_version:
            rows = [item for item in rows if str(item.get("schema_version", "")) == str(schema_version)]
        if active_only:
            rows = [item for item in rows if bool(item.get("is_active", False))]
        rows = sorted(rows, key=lambda item: str(item.get("created_at", "")), reverse=True)
        return rows[: max(1, limit)]

    def set_case_document_extraction_active(self, document_extraction_id: str) -> Optional[Dict[str, Any]]:
        target = self.case_document_extractions.get(document_extraction_id)
        if not isinstance(target, dict):
            return None
        document_id = str(target.get("document_id", ""))
        schema_version = str(target.get("schema_version", ""))
        now = _utcnow().isoformat()
        for key, row in list(self.case_document_extractions.items()):
            if not isinstance(row, dict):
                continue
            if str(row.get("document_id", "")) != document_id:
                continue
            if str(row.get("schema_version", "")) != schema_version:
                continue
            updated = dict(row)
            updated["is_active"] = key == document_extraction_id
            updated["updated_at"] = now
            self.case_document_extractions[key] = updated
        return self.case_document_extractions.get(document_extraction_id)

    def upsert_case_chunk_extraction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chunk_extraction_id = str(payload.get("chunk_extraction_id") or _gen_id())
        now = _utcnow().isoformat()
        row = {
            **payload,
            "chunk_extraction_id": chunk_extraction_id,
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }
        self.case_chunk_extractions[chunk_extraction_id] = row
        return row

    def list_case_chunk_extractions(
        self,
        *,
        document_extraction_id: Optional[str] = None,
        run_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        rows = list(self.case_chunk_extractions.values())
        if document_extraction_id:
            rows = [
                item
                for item in rows
                if str(item.get("document_extraction_id", "")) == str(document_extraction_id)
            ]
        if run_id:
            rows = [item for item in rows if str(item.get("run_id", "")) == str(run_id)]
        if document_id:
            rows = [item for item in rows if str(item.get("document_id", "")) == str(document_id)]
        rows = sorted(rows, key=lambda item: str(item.get("created_at", "")))
        return rows[: max(1, limit)]

    def upsert_case_qc_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        qc_result_id = str(payload.get("qc_result_id") or _gen_id())
        now = _utcnow().isoformat()
        row = {
            **payload,
            "qc_result_id": qc_result_id,
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }
        self.case_extraction_qc_results[qc_result_id] = row
        return row

    def list_case_qc_results(
        self,
        *,
        run_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        rows = list(self.case_extraction_qc_results.values())
        if run_id:
            rows = [item for item in rows if str(item.get("run_id", "")) == str(run_id)]
        if document_id:
            rows = [item for item in rows if str(item.get("document_id", "")) == str(document_id)]
        rows = sorted(rows, key=lambda item: str(item.get("created_at", "")), reverse=True)
        return rows[: max(1, limit)]

    # ---------------------------------------------
    # Runs
    # ---------------------------------------------
    def create_run(self, dataset_id: str, question_count: int, status: str = "queued") -> Dict[str, Any]:
        run_id = _gen_id()
        now = _utcnow()
        self.runs[run_id] = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "status": status,
            "question_count": question_count,
            "created_at": now,
            "updated_at": now,
        }
        self.run_questions[run_id] = {}
        return self.runs[run_id]

    def set_run_status(self, run_id: str, status: str) -> None:
        if run_id in self.runs:
            self.runs[run_id]["status"] = status
            self.runs[run_id]["updated_at"] = _utcnow()

    def upsert_run_question(self, run_id: str, question_id: str, response: QueryResponse) -> None:
        if run_id not in self.run_questions:
            self.run_questions[run_id] = {}
        self.run_questions[run_id][question_id] = response
        if run_id in self.runs:
            predicted = self.runs[run_id]
            predicted["question_count"] = max(predicted.get("question_count", 0), len(self.run_questions[run_id]))
            predicted["updated_at"] = _utcnow()

    def upsert_run_question_review(self, run_id: str, question_id: str, payload: Dict[str, Any]) -> RunQuestionReviewArtifact:
        artifact = RunQuestionReviewArtifact(**payload)
        if run_id not in self.run_question_reviews:
            self.run_question_reviews[run_id] = {}
        self.run_question_reviews[run_id][question_id] = artifact.model_dump(mode="json")
        return artifact

    def get_run_question_review(self, run_id: str, question_id: str) -> Optional[RunQuestionReviewArtifact]:
        payload = self.run_question_reviews.get(run_id, {}).get(question_id)
        if not isinstance(payload, dict):
            return None
        return RunQuestionReviewArtifact(**payload)

    def list_run_question_reviews(self, run_id: str) -> Dict[str, RunQuestionReviewArtifact]:
        out: Dict[str, RunQuestionReviewArtifact] = {}
        for question_id, payload in self.run_question_reviews.get(run_id, {}).items():
            if not isinstance(payload, dict):
                continue
            out[str(question_id)] = RunQuestionReviewArtifact(**payload)
        return out

    # ---------------------------------------------
    # Gold
    # ---------------------------------------------
    def create_gold_dataset(self, payload: Dict[str, Any]) -> GoldDataset:
        gold_dataset_id = _gen_id()
        now = _utcnow()
        ds = GoldDataset(
            gold_dataset_id=gold_dataset_id,
            project_id=payload["project_id"],
            name=payload["name"],
            version=payload["version"],
            status="draft",
            base_dataset_id=payload.get("base_dataset_id"),
            question_count=0,
            created_at=now,
            updated_at=now,
        )
        self.gold_datasets[gold_dataset_id] = ds
        self.gold_questions[gold_dataset_id] = {}
        self.audit_log.append(
            {
                "event": "gold_dataset_created",
                "target": gold_dataset_id,
                "at": now.isoformat(),
                "payload": payload,
            }
        )
        return ds

    def add_gold_question(self, dataset_id: str, question: Dict[str, Any]) -> GoldQuestion:
        gold_question_id = _gen_id()
        payload = GoldQuestion(
            gold_question_id=gold_question_id,
            question_id=question["question_id"],
            gold_dataset_id=dataset_id,
            canonical_answer=question["canonical_answer"],
            acceptable_answers=question.get("acceptable_answers", []),
            answer_type=question["answer_type"],
            source_sets=question["source_sets"],
            review_status=question.get("review_status", "draft"),
            reviewers=question.get("reviewers", []),
            notes=question.get("notes"),
        )
        self.gold_questions[dataset_id][gold_question_id] = payload
        if dataset_id in self.gold_datasets:
            ds = self.gold_datasets[dataset_id]
            data = ds.model_dump()
            data["question_count"] = max(ds.question_count, len(self.gold_questions[dataset_id]))
            data["updated_at"] = _utcnow()
            self.gold_datasets[dataset_id] = GoldDataset(**data)
        self.audit_log.append(
            {
                "event": "gold_question_created",
                "target": gold_question_id,
                "dataset": dataset_id,
                "at": _utcnow().isoformat(),
            }
        )
        return payload

    def set_gold_question_review(
        self,
        gold_question_id: str,
        dataset_id: str,
        decision: str,
        comment: Optional[str] = None,
    ) -> GoldQuestion:
        q = self.gold_questions[dataset_id][gold_question_id]
        if decision == "approve":
            q.review_status = "reviewed"
        elif decision == "lock":
            q.review_status = "locked"
        elif decision == "changes_requested":
            q.review_status = "draft"
        if comment:
            q.notes = f"{q.notes or ''}{('\\n' if q.notes else '')}{comment}"
        self.gold_questions[dataset_id][gold_question_id] = q
        self.audit_log.append(
            {
                "event": "gold_question_review",
                "target": gold_question_id,
                "decision": decision,
                "at": _utcnow().isoformat(),
            }
        )
        return q

    def find_gold_question_by_dataset_question(self, dataset_id: str, question_id: str) -> Optional[GoldQuestion]:
        for candidate in self.gold_questions.get(dataset_id, {}).values():
            if candidate.question_id == question_id:
                return candidate
        return None

    # ---------------------------------------------
    # Synthetic
    # ---------------------------------------------
    def create_synth_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        job_id = _gen_id()
        job = {
            "job_id": job_id,
            "project_id": payload["project_id"],
            "status": "queued",
            "source_scope": payload["source_scope"],
            "generation_policy": payload["generation_policy"],
            "candidates": [],
            "created_at": _utcnow().isoformat(),
            "updated_at": _utcnow().isoformat(),
        }
        self.synth_jobs[job_id] = job
        self.synth_candidates[job_id] = {}
        self.audit_log.append(
            {
                "event": "synth_job_created",
                "target": job_id,
                "at": _utcnow().isoformat(),
            }
        )
        return self.synth_jobs[job_id]

    # ---------------------------------------------
    # Eval
    # ---------------------------------------------
    def create_eval_run(self, payload: EvalRun) -> EvalRun:
        self.eval_runs[payload.eval_run_id] = payload
        return payload

    # ---------------------------------------------
    # Search / lookup helpers
    # ---------------------------------------------
    def get_question_payload(self, dataset_id: str, question_id: str) -> Optional[Dict[str, Any]]:
        dataset = self.datasets.get(dataset_id)
        if not isinstance(dataset, dict):
            return None
        questions = dataset.get("questions")
        if isinstance(questions, dict):
            cached = questions.get(question_id)
            if isinstance(cached, dict):
                return cached
        return None

    def page_records(self) -> List[Dict[str, Any]]:
        return list(self.pages.values())

    def paragraph_records(self) -> List[Dict[str, Any]]:
        return list(self.paragraphs.values())

    # ---------------------------------------------
    # Import jobs
    # ---------------------------------------------
    def create_corpus_import(self, project_id: str, blob_url: str, parse_policy: str, dedupe_enabled: bool) -> str:
        project_id = resolve_corpus_import_project_id(project_id)
        job_id = _gen_id()
        self.import_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "project_id": project_id,
            "blob_url": blob_url,
            "parse_policy": parse_policy,
            "dedupe_enabled": dedupe_enabled,
            "processing_profile_version": "parser_only_v1",
            "created_at": _utcnow().isoformat(),
        }
        self.corpus_jobs[job_id] = self.import_jobs[job_id]
        return job_id

    # ---------------------------------------------
    # Experiments
    # ---------------------------------------------
    def create_exp_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = _utcnow().isoformat()
        profile = {
            "profile_id": _gen_id(),
            "name": str(payload["name"]),
            "project_id": str(payload["project_id"]),
            "dataset_id": str(payload["dataset_id"]),
            "gold_dataset_id": str(payload["gold_dataset_id"]),
            "endpoint_target": str(payload.get("endpoint_target", "local")),
            "active": bool(payload.get("active", True)),
            "processing_profile": payload.get("processing_profile", {}),
            "retrieval_profile": payload.get("retrieval_profile", {}),
            "runtime_policy": payload.get("runtime_policy"),
            "created_at": now,
            "updated_at": now,
        }
        self.exp_profiles[profile["profile_id"]] = profile
        return profile

    def create_experiment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = _utcnow().isoformat()
        experiment = {
            "experiment_id": _gen_id(),
            "name": str(payload["name"]),
            "profile_id": str(payload["profile_id"]),
            "gold_dataset_id": str(payload["gold_dataset_id"]),
            "baseline_experiment_run_id": payload.get("baseline_experiment_run_id"),
            "status": str(payload.get("status", "active")),
            "metadata": payload.get("metadata", {}),
            "created_at": now,
            "updated_at": now,
        }
        self.exp_experiments[experiment["experiment_id"]] = experiment
        return experiment

    def create_experiment_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = _gen_id()
        now = _utcnow().isoformat()
        run = {
            "experiment_run_id": run_id,
            "experiment_id": str(payload["experiment_id"]),
            "profile_id": str(payload["profile_id"]),
            "gold_dataset_id": str(payload["gold_dataset_id"]),
            "stage_type": str(payload.get("stage_type", "proxy")),
            "status": str(payload.get("status", "queued")),
            "gate_passed": payload.get("gate_passed"),
            "idempotency_key": payload.get("idempotency_key"),
            "qa_run_id": payload.get("qa_run_id"),
            "eval_run_id": payload.get("eval_run_id"),
            "sample_size": int(payload.get("sample_size", 0)),
            "question_count": int(payload.get("question_count", 0)),
            "baseline_experiment_run_id": payload.get("baseline_experiment_run_id"),
            "metrics": payload.get("metrics", {}),
            "created_at": now,
            "started_at": payload.get("started_at"),
            "completed_at": payload.get("completed_at"),
            "error_message": payload.get("error_message"),
        }
        self.exp_runs[run_id] = run
        self.exp_question_metrics[run_id] = {}
        self.exp_artifacts.setdefault(run_id, [])
        return run

    def update_experiment_run(self, experiment_run_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current = self.exp_runs.get(experiment_run_id)
        if not current:
            return None
        merged = {**current, **patch}
        self.exp_runs[experiment_run_id] = merged
        return merged

    def find_experiment_run_by_idempotency(self, experiment_id: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
        matches = [
            row
            for row in self.exp_runs.values()
            if row.get("experiment_id") == experiment_id and row.get("idempotency_key") == idempotency_key
        ]
        if not matches:
            return None
        matches.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
        return matches[0]

    def upsert_exp_stage_cache(self, stage_type: str, cache_key: str, experiment_run_id: str, payload: Dict[str, Any]) -> None:
        key = f"{stage_type}:{cache_key}"
        self.exp_stage_cache[key] = {
            "stage_type": stage_type,
            "cache_key": cache_key,
            "experiment_run_id": experiment_run_id,
            "payload": payload,
            "created_at": _utcnow().isoformat(),
        }

    def get_exp_stage_cache(self, stage_type: str, cache_key: str) -> Optional[Dict[str, Any]]:
        return self.exp_stage_cache.get(f"{stage_type}:{cache_key}")

    def upsert_exp_score(self, experiment_run_id: str, experiment_id: str, stage_type: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        score = {
            "score_id": _gen_id(),
            "experiment_run_id": experiment_run_id,
            "experiment_id": experiment_id,
            "stage_type": stage_type,
            "answer_score_mean": float(metrics.get("answer_score_mean", 0.0)),
            "grounding_score_mean": float(metrics.get("grounding_score_mean", 0.0)),
            "telemetry_factor": float(metrics.get("telemetry_factor", 0.0)),
            "ttft_factor": float(metrics.get("ttft_factor", 0.0)),
            "overall_score": float(metrics.get("overall_score", 0.0)),
            "payload": metrics,
            "created_at": _utcnow().isoformat(),
        }
        self.exp_scores[experiment_run_id] = score
        return score

    def upsert_exp_question_metric(self, experiment_run_id: str, question_id: str, metric: Dict[str, Any]) -> None:
        bucket = self.exp_question_metrics.setdefault(experiment_run_id, {})
        bucket[question_id] = metric

    def list_exp_question_metrics(self, experiment_run_id: str) -> List[Dict[str, Any]]:
        return list(self.exp_question_metrics.get(experiment_run_id, {}).values())

    def upsert_exp_artifact(self, experiment_run_id: str, artifact_type: str, artifact_url: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        artifact = {
            "artifact_id": _gen_id(),
            "experiment_run_id": experiment_run_id,
            "artifact_type": artifact_type,
            "artifact_url": artifact_url,
            "payload": payload,
            "created_at": _utcnow().isoformat(),
        }
        self.exp_artifacts.setdefault(experiment_run_id, []).append(artifact)
        return artifact

    def list_exp_artifacts(self, experiment_run_id: str) -> List[Dict[str, Any]]:
        return list(self.exp_artifacts.get(experiment_run_id, []))

    def append_exp_ops_log(
        self,
        actor: str,
        command_name: str,
        target: Optional[str],
        status: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> str:
        op_id = _gen_id()
        self.exp_ops_log.append(
            {
                "op_id": op_id,
                "started_at": _utcnow().isoformat(),
                "finished_at": _utcnow().isoformat(),
                "actor": actor,
                "command_name": command_name,
                "target": target,
                "status": status,
                "payload": payload or {},
                "idempotency_key": idempotency_key,
                "error_message": error_message,
            }
        )
        return op_id

    def list_exp_leaderboard(self, *, limit: int = 50, stage_type: Optional[str] = None, experiment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for run_id, score in self.exp_scores.items():
            run = self.exp_runs.get(run_id)
            if not run:
                continue
            if run.get("status") != "completed":
                continue
            if stage_type and run.get("stage_type") != stage_type:
                continue
            if experiment_id and run.get("experiment_id") != experiment_id:
                continue
            experiment = self.exp_experiments.get(str(run.get("experiment_id")), {})
            rows.append(
                {
                    "experiment_run_id": run_id,
                    "experiment_id": run.get("experiment_id"),
                    "experiment_name": experiment.get("name", "unknown"),
                    "stage_type": run.get("stage_type"),
                    "overall_score": float(score.get("overall_score", 0.0)),
                    "answer_score_mean": float(score.get("answer_score_mean", 0.0)),
                    "grounding_score_mean": float(score.get("grounding_score_mean", 0.0)),
                    "telemetry_factor": float(score.get("telemetry_factor", 0.0)),
                    "ttft_factor": float(score.get("ttft_factor", 0.0)),
                    "created_at": run.get("created_at"),
                }
            )
        rows.sort(key=lambda row: (row["overall_score"], str(row.get("created_at"))), reverse=True)
        return rows[:limit]
