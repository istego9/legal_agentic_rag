"""Pydantic contracts mirrored from OpenAPI/JSON Schema for API boundaries."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, ConfigDict

AnswerValue = Union[str, int, float, bool, List[str], List[int], List[float], None]
AnswerType = Literal["boolean", "number", "date", "name", "names", "free_text"]
Difficulty = Literal["easy", "medium", "hard", "adversarial"]
SourceEnum = Literal[
    "public_competition",
    "private_competition",
    "internal_gold",
    "synthetic",
    "manual",
]
RouteHint = Optional[
    Literal[
        "article_lookup",
        "single_case_extraction",
        "cross_case_compare",
        "cross_law_compare",
        "history_lineage",
        "no_answer",
    ]
]

SectionKind = Literal[
    "cover",
    "heading",
    "definition",
    "operative_provision",
    "exception",
    "penalty",
    "procedure",
    "schedule_item",
    "cross_reference",
    "footnote",
    "parties",
    "procedural_history",
    "facts",
    "issues",
    "reasoning",
    "holding",
    "order",
    "disposition",
]
ProvisionKind = Literal[
    "definition",
    "right",
    "obligation",
    "prohibition",
    "exemption",
    "penalty",
    "procedure",
    "administrative_power",
    "interpretation",
]
HistoricalRelationType = Literal["original", "amended", "restated", "repealed", "superseded"]
EdgeType = Literal[
    "amends",
    "amended_by",
    "repeals",
    "supersedes",
    "restates",
    "refers_to",
    "enabled_by",
    "comes_into_force_via",
    "same_legal_concept_as",
    "cites",
    "overrules",
    "same_party_as",
    "same_judge_as",
]
DocTypeCore = Literal["law", "regulation", "enactment_notice", "case", "other"]
DocumentStatus = Literal["parsed", "indexed", "failed"]
LawStatus = Literal["in_force", "partially_in_force", "repealed", "superseded"]
RegulationType = Literal["rule", "regulation", "order", "direction", "practice_direction"]
CommencementScopeType = Literal["full", "partial", "staged", "exception_based"]
CaseSectionKind = Literal[
    "parties",
    "procedural_history",
    "facts",
    "issues",
    "reasoning",
    "order",
    "disposition",
]
ChunkType = Literal["paragraph", "heading", "list_item", "table_row", "footnote"]
SourceObjectType = Literal["document", "page", "paragraph", "provision", "chunk", "case_party", "case_judge"]
OntologyEntryKind = Literal["object_type", "relation_type", "property_type"]
OntologyEntryStatus = Literal["candidate", "active"]
AssertionProvenance = Literal["rules", "agent", "merged"]
CorpusEnrichmentJobStatus = Literal["queued", "running", "partial", "completed", "failed"]
LegalModality = Literal[
    "obligation",
    "prohibition",
    "permission",
    "definition",
    "power",
    "procedure",
    "penalty",
    "exception",
]


class PageRef(BaseModel):
    project_id: Optional[str] = None
    document_id: Optional[str] = None
    pdf_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    page_num: int = Field(ge=0)
    page_index_base: Literal[0, 1]
    source_page_id: str = Field(pattern=r"^[A-Za-z0-9._-]+_[0-9]+$")
    used: bool
    evidence_role: Optional[
        Literal["primary", "supporting", "title", "lineage", "negative_check"]
    ] = None
    score: Optional[float] = Field(default=None, ge=0, le=1)


class Telemetry(BaseModel):
    request_started_at: datetime
    first_token_at: Optional[datetime] = None
    completed_at: datetime
    ttft_ms: int = Field(ge=0)
    total_response_ms: int = Field(ge=0)
    time_per_output_token_ms: Optional[float] = Field(default=None, ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_name: str
    route_name: str
    judge_model_name: Optional[str] = None
    search_profile: str = "default"
    telemetry_complete: bool
    trace_id: str


class Question(BaseModel):
    id: str
    dataset_id: Optional[str] = None
    question: str = Field(min_length=1)
    answer_type: AnswerType
    source: Optional[SourceEnum] = "manual"
    difficulty: Optional[Difficulty] = "easy"
    route_hint: RouteHint = None
    tags: List[str] = Field(default_factory=list)


class RuntimePolicy(BaseModel):
    use_llm: bool
    max_candidate_pages: int = Field(ge=1, le=100)
    max_context_paragraphs: int = Field(ge=1, le=64)
    page_index_base_export: Literal[0, 1]
    scoring_policy_version: str
    allow_dense_fallback: bool
    return_debug_trace: bool = False


class QueryRequest(BaseModel):
    project_id: str
    question: Question
    runtime_policy: RuntimePolicy


class QueryResponse(BaseModel):
    question_id: str
    answer: AnswerValue
    answer_normalized: Optional[str] = None
    answer_type: AnswerType
    confidence: float = Field(ge=0, le=1)
    route_name: str
    abstained: bool
    sources: List[PageRef]
    telemetry: Telemetry
    debug: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True)


class SubmissionAnswer(BaseModel):
    question_id: str
    answer: AnswerValue
    sources: List[str] = Field(default_factory=list)
    telemetry: Telemetry


SOURCE_PAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+_[0-9]+$")


def export_used_source_page_ids(sources: List[PageRef]) -> List[str]:
    out: List[str] = []
    seen = set()
    for source in sources:
        if not source.used:
            continue
        source_page_id = str(source.source_page_id).strip()
        if not source_page_id:
            continue
        if not SOURCE_PAGE_ID_PATTERN.fullmatch(source_page_id):
            continue
        if source_page_id in seen:
            continue
        seen.add(source_page_id)
        out.append(source_page_id)
    return out


SharedContractName = Literal[
    "PageRef",
    "Telemetry",
    "RuntimePolicy",
    "QueryRequest",
    "QueryResponse",
    "SubmissionAnswer",
]
SharedContractOwner = Literal["control-plane"]
SharedContractConsumer = Literal[
    "api",
    "runtime",
    "eval",
    "experiments",
    "storage",
    "web",
    "submission_export",
]
SharedContractChangePolicy = Literal["version_bump_required"]


class SharedContractSpec(BaseModel):
    contract_name: SharedContractName
    schema_version: str = Field(pattern=r"^[a-z0-9_.-]+$")
    owner: SharedContractOwner
    source_of_truth: str
    consumers: List[SharedContractConsumer] = Field(default_factory=list)
    change_policy: SharedContractChangePolicy
    notes: List[str] = Field(default_factory=list)


class SharedContractRegistry(BaseModel):
    registry_version: str = Field(pattern=r"^[a-z0-9_.-]+$")
    contracts: List[SharedContractSpec] = Field(default_factory=list)
    frozen_invariants: List[str] = Field(default_factory=list)


SHARED_CONTRACT_REGISTRY_VERSION = "shared_contract_registry.v1"
SHARED_CONTRACT_REGISTRY = SharedContractRegistry(
    registry_version=SHARED_CONTRACT_REGISTRY_VERSION,
    contracts=[
        SharedContractSpec(
            contract_name="PageRef",
            schema_version="page_ref.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "eval", "web", "submission_export"],
            change_policy="version_bump_required",
            notes=[
                "source_page_id must remain canonical pdf_id_page",
                "competition grounding remains page-level",
            ],
        ),
        SharedContractSpec(
            contract_name="Telemetry",
            schema_version="telemetry.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "eval", "experiments", "submission_export"],
            change_policy="version_bump_required",
            notes=[
                "telemetry must remain complete and serializable",
                "ttft and total response timings stay explicit",
            ],
        ),
        SharedContractSpec(
            contract_name="RuntimePolicy",
            schema_version="runtime_policy.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "experiments", "web"],
            change_policy="version_bump_required",
            notes=[
                "page_index_base_export remains explicit",
                "scoring_policy_version is required for runtime/eval comparability",
            ],
        ),
        SharedContractSpec(
            contract_name="QueryRequest",
            schema_version="query_request.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "web"],
            change_policy="version_bump_required",
            notes=[
                "question and runtime_policy stay required",
                "request boundary remains additive-only unless versioned",
            ],
        ),
        SharedContractSpec(
            contract_name="QueryResponse",
            schema_version="query_response.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "eval", "experiments", "storage", "web"],
            change_policy="version_bump_required",
            notes=[
                "sources continue to use PageRef",
                "telemetry continues to use Telemetry",
                "abstained remains explicit",
            ],
        ),
        SharedContractSpec(
            contract_name="SubmissionAnswer",
            schema_version="submission_answer.v1",
            owner="control-plane",
            source_of_truth="apps/api/src/legal_rag_api/contracts.py",
            consumers=["api", "runtime", "eval", "submission_export"],
            change_policy="version_bump_required",
            notes=[
                "sources remain exported as page source ids",
                "export artifact keeps telemetry attached",
            ],
        ),
    ],
    frozen_invariants=[
        "competition_source_unit=page",
        "source_page_id=pdf_id_page",
        "paragraph_is_retrieval_unit_only",
        "submission_export_sources_are_page_ids",
    ],
)


class AskBatchRequest(BaseModel):
    project_id: str
    dataset_id: str
    question_ids: List[str]
    runtime_policy: RuntimePolicy


class RunSummary(BaseModel):
    run_id: str
    dataset_id: str
    status: str
    question_count: int
    created_at: datetime


class ExportRequest(BaseModel):
    page_index_base: Literal[0, 1]


class OfficialSubmissionExportRequest(ExportRequest):
    architecture_summary: Optional[str] = Field(default=None, max_length=500)


class DocumentManifest(BaseModel):
    document_id: str
    project_id: str
    pdf_id: str
    canonical_doc_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    doc_type: Literal["law", "regulation", "enactment_notice", "case", "other"]
    title: Optional[str] = None
    citation_title: Optional[str] = None
    law_number: Optional[str] = None
    case_id: Optional[str] = None
    year: Optional[int] = None
    edition_date: Optional[str] = None
    page_count: int = Field(ge=1)
    duplicate_group_id: Optional[str] = None
    status: DocumentStatus
    title_raw: Optional[str] = None
    title_normalized: Optional[str] = None
    short_title: Optional[str] = None
    language: Optional[str] = None
    jurisdiction: Optional[str] = None
    issued_date: Optional[str] = None
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    repealed_date: Optional[str] = None
    is_current_version: Optional[bool] = None
    version_group_id: Optional[str] = None
    version_sequence: Optional[int] = None
    supersedes_doc_id: Optional[str] = None
    superseded_by_doc_id: Optional[str] = None
    parser_version: Optional[str] = None
    ocr_used: Optional[bool] = None
    extraction_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    ingested_at: Optional[str] = None
    last_reprocessed_at: Optional[str] = None
    topic_tags: List[str] = Field(default_factory=list)
    legal_domains: List[str] = Field(default_factory=list)
    entity_names: List[str] = Field(default_factory=list)
    citation_keys: List[str] = Field(default_factory=list)
    search_text_compact: Optional[str] = None
    search_priority_score: Optional[float] = None


class ParagraphChunk(BaseModel):
    paragraph_id: str
    page_id: str
    document_id: str
    paragraph_index: int = Field(ge=0)
    heading_path: List[str] = Field(default_factory=list)
    text: str
    summary_tag: Optional[str] = None
    paragraph_class: str
    entities: List[str] = Field(default_factory=list)
    article_refs: List[str] = Field(default_factory=list)
    law_refs: List[str] = Field(default_factory=list)
    case_refs: List[str] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    money_mentions: List[str] = Field(default_factory=list)
    version_lineage_id: Optional[str] = None
    embedding_vector_id: Optional[str] = None
    chunk_type: Optional[ChunkType] = None
    chunk_index_on_page: Optional[int] = Field(default=None, ge=0)
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    text_clean: Optional[str] = None
    text_compact: Optional[str] = None
    retrieval_text: Optional[str] = None
    heading_path_full: List[str] = Field(default_factory=list)
    section_kind: Optional[SectionKind] = None
    structural_level: Optional[int] = Field(default=None, ge=0)
    parent_section_id: Optional[str] = None
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    entity_names_normalized: List[str] = Field(default_factory=list)
    schedule_refs: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    topic_tags: List[str] = Field(default_factory=list)
    legal_action_tags: List[str] = Field(default_factory=list)
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    is_current_version: Optional[bool] = None
    canonical_concept_id: Optional[str] = None
    historical_relation_type: Optional[HistoricalRelationType] = None
    exact_terms: List[str] = Field(default_factory=list)
    search_keywords: List[str] = Field(default_factory=list)
    rank_hints: List[str] = Field(default_factory=list)
    answer_candidate_types: List[str] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    parser_flags: List[str] = Field(default_factory=list)
    extraction_method: Optional[str] = None
    tagging_model_version: Optional[str] = None
    last_tagged_at: Optional[str] = None
    llm_status: Optional[str] = None
    llm_summary: Optional[str] = None
    llm_section_type: Optional[str] = None
    llm_tags: List[str] = Field(default_factory=list)
    llm_payload: Dict[str, Any] = Field(default_factory=dict)
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None
    llm_updated_at: Optional[str] = None


class OntologyRegistryEntry(BaseModel):
    entry_id: str
    kind: OntologyEntryKind
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: OntologyEntryStatus
    parent_key: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    usage_count: int = Field(default=0, ge=0)
    sample_chunk_ids: List[str] = Field(default_factory=list)
    created_by: str = Field(min_length=1)


class ChunkOntologyAssertion(BaseModel):
    assertion_id: str
    paragraph_id: str
    page_id: str
    document_id: str
    source_page_id: str = Field(pattern=r"^[A-Za-z0-9._-]+_[0-9]+$")
    subject_type: str = Field(min_length=1)
    subject_text: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    modality: LegalModality
    action: Optional[str] = None
    beneficiary: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    condition_text: Optional[str] = None
    exception_text: Optional[str] = None
    temporal_scope: Optional[str] = None
    citation_refs: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    provenance: AssertionProvenance


class DocumentOntologyView(BaseModel):
    document_id: str
    project_id: str
    source_page_ids: List[str] = Field(default_factory=list)
    chunk_assertion_ids: List[str] = Field(default_factory=list)
    object_types: List[str] = Field(default_factory=list)
    relation_types: List[str] = Field(default_factory=list)
    property_types: List[str] = Field(default_factory=list)
    candidate_entry_keys: List[str] = Field(default_factory=list)
    active_entry_keys: List[str] = Field(default_factory=list)
    actor_summary: List[str] = Field(default_factory=list)
    beneficiary_summary: List[str] = Field(default_factory=list)
    conflict_map: Dict[str, List[str]] = Field(default_factory=dict)
    assertion_count: int = Field(default=0, ge=0)
    created_by: str = Field(min_length=1)
    updated_at: datetime


class CorpusEnrichmentJob(BaseModel):
    job_id: str
    project_id: str
    import_job_id: str
    processing_profile_version: str = Field(min_length=1)
    llm_enabled: bool = False
    llm_model_version: Optional[str] = None
    llm_prompt_version: Optional[str] = None
    status: CorpusEnrichmentJobStatus
    document_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    processed_document_count: int = Field(default=0, ge=0)
    processed_chunk_count: int = Field(default=0, ge=0)
    failed_document_ids: List[str] = Field(default_factory=list)
    failed_chunk_ids: List[str] = Field(default_factory=list)
    candidate_entry_count: int = Field(default=0, ge=0)
    active_entry_count: int = Field(default=0, ge=0)
    role_sequence: List[str] = Field(default_factory=list)
    chunk_stage_runs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    document_stage_runs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    retryable_targets: Dict[str, List[str]] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RunQuestionReviewArtifact(BaseModel):
    run_id: str
    question_id: str
    question: Dict[str, Any] = Field(default_factory=dict)
    response: QueryResponse
    evidence: Dict[str, Any] = Field(default_factory=dict)
    document_viewer: Dict[str, Any] = Field(default_factory=dict)
    promotion_preview: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class GoldQuestion(BaseModel):
    gold_question_id: str
    question_id: str
    gold_dataset_id: str
    canonical_answer: AnswerValue
    acceptable_answers: List[AnswerValue] = Field(default_factory=list)
    answer_type: AnswerType
    source_sets: List[Dict[str, Any]]
    review_status: Literal["draft", "reviewed", "locked"]
    reviewers: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class GoldDataset(BaseModel):
    gold_dataset_id: str
    project_id: str
    name: str
    version: str
    status: Literal["draft", "review", "locked", "archived"]
    base_dataset_id: Optional[str] = None
    question_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class EvalRun(BaseModel):
    eval_run_id: str
    run_id: str
    gold_dataset_id: str
    scoring_policy_version: str
    judge_policy_version: str
    status: Literal["queued", "running", "completed", "failed"]
    metrics: Dict[str, Any] = Field(default_factory=dict)


class EvalRequest(BaseModel):
    run_id: str
    gold_dataset_id: str
    scoring_policy_version: str
    judge_policy_version: str


class EvalCompareRequest(BaseModel):
    left_eval_run_id: str
    right_eval_run_id: str


class ExperimentProfileCreate(BaseModel):
    name: str = Field(min_length=1)
    project_id: str
    dataset_id: str
    gold_dataset_id: str
    endpoint_target: str = "local"
    active: bool = True
    processing_profile: Dict[str, Any] = Field(default_factory=dict)
    retrieval_profile: Dict[str, Any] = Field(default_factory=dict)
    runtime_policy: Optional[RuntimePolicy] = None


class ExperimentProfile(BaseModel):
    profile_id: str
    name: str
    project_id: str
    dataset_id: str
    gold_dataset_id: str
    endpoint_target: str
    active: bool = True
    processing_profile: Dict[str, Any] = Field(default_factory=dict)
    retrieval_profile: Dict[str, Any] = Field(default_factory=dict)
    runtime_policy: Optional[RuntimePolicy] = None
    created_at: datetime
    updated_at: datetime


class ExperimentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    profile_id: str
    gold_dataset_id: Optional[str] = None
    baseline_experiment_run_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Experiment(BaseModel):
    experiment_id: str
    name: str
    profile_id: str
    gold_dataset_id: str
    baseline_experiment_run_id: Optional[str] = None
    status: Literal["draft", "active", "archived"]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExperimentRunCreateRequest(BaseModel):
    stage_mode: Literal["auto", "proxy", "full"] = "auto"
    baseline_experiment_run_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    proxy_sample_size: Optional[int] = Field(default=None, ge=1, le=100000)
    actor: str = "ui"
    agent_mode: bool = False


class ExperimentRun(BaseModel):
    experiment_run_id: str
    experiment_id: str
    profile_id: str
    gold_dataset_id: str
    stage_type: Literal["proxy", "full"]
    status: Literal["queued", "running", "gated_rejected", "completed", "failed"]
    gate_passed: Optional[bool] = None
    qa_run_id: Optional[str] = None
    eval_run_id: Optional[str] = None
    sample_size: int = Field(ge=0)
    question_count: int = Field(ge=0)
    baseline_experiment_run_id: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ExperimentQuestionMetric(BaseModel):
    question_id: str
    answer_score: float = Field(ge=0, le=1)
    grounding_score: float = Field(ge=0, le=1)
    telemetry_factor: float = Field(ge=0, le=1.05)
    ttft_factor: float = Field(ge=0, le=1.05)
    overall_score: float = Field(ge=0, le=1.2)
    route_name: Optional[str] = None
    segment: Optional[str] = None
    delta_vs_baseline: Optional[float] = None
    error_tags: List[str] = Field(default_factory=list)


class ExperimentAnalysis(BaseModel):
    experiment_run: ExperimentRun
    score: Dict[str, Any] = Field(default_factory=dict)
    gate: Dict[str, Any] = Field(default_factory=dict)
    items: List[ExperimentQuestionMetric] = Field(default_factory=list)
    deltas: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)


class ExperimentCompareRequest(BaseModel):
    left_experiment_run_id: str
    right_experiment_run_id: str


class ExperimentLeaderboardItem(BaseModel):
    experiment_run_id: str
    experiment_id: str
    experiment_name: str
    stage_type: str
    overall_score: float
    answer_score_mean: float = 0.0
    grounding_score_mean: float = 0.0
    telemetry_factor: float = 0.0
    ttft_factor: float = 0.0
    created_at: datetime


class SyntheticJob(BaseModel):
    job_id: str
    project_id: str
    status: Literal["queued", "running", "review", "published", "failed", "cancelled"]
    source_scope: Dict[str, Any]
    generation_policy: Dict[str, Any]


class SourceSetCreate(BaseModel):
    is_primary: bool
    page_ids: List[str]
    notes: Optional[str] = None


class ReviewRequest(BaseModel):
    decision: Literal["approve", "changes_requested", "lock"]
    comment: Optional[str] = None


class CandidateApproveRequest(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    edited_question: Optional[str] = None
    edited_answer: Optional[AnswerValue] = None
    edited_source_pages: Optional[List[str]] = None


class ScoringPolicy(BaseModel):
    policy_version: str
    policy_type: Literal["contest_emulation", "internal_strict"]
    beta: float = Field(ge=0)
    ttft_curve: Dict[str, Any] = Field(default_factory=dict)
    telemetry_policy: str = "run_level_factor"


class DocumentBase(BaseModel):
    document_id: str
    project_id: str
    pdf_id: str
    canonical_doc_id: str
    doc_type: DocTypeCore
    source_file_name: Optional[str] = None
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duplicate_group_id: Optional[str] = None
    title_raw: Optional[str] = None
    title_normalized: Optional[str] = None
    short_title: Optional[str] = None
    citation_title: Optional[str] = None
    language: Optional[str] = None
    jurisdiction: Optional[str] = None
    issued_date: Optional[str] = None
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    repealed_date: Optional[str] = None
    is_current_version: bool = True
    version_group_id: Optional[str] = None
    version_sequence: Optional[int] = None
    supersedes_doc_id: Optional[str] = None
    superseded_by_doc_id: Optional[str] = None
    page_count: int = Field(ge=1)
    parser_version: Optional[str] = None
    ocr_used: Optional[bool] = None
    extraction_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    ingested_at: Optional[str] = None
    last_reprocessed_at: Optional[str] = None
    topic_tags: List[str] = Field(default_factory=list)
    legal_domains: List[str] = Field(default_factory=list)
    entity_names: List[str] = Field(default_factory=list)
    citation_keys: List[str] = Field(default_factory=list)
    search_text_compact: Optional[str] = None
    search_priority_score: Optional[float] = None
    status: DocumentStatus = "parsed"


class LawDocument(BaseModel):
    document_id: str
    law_number: Optional[str] = None
    law_year: Optional[int] = None
    law_family_code: Optional[str] = None
    instrument_kind: Optional[str] = None
    administering_authority: Optional[str] = None
    promulgation_date: Optional[str] = None
    commencement_date: Optional[str] = None
    last_consolidated_date: Optional[str] = None
    status: Optional[LawStatus] = None
    parent_law_id: Optional[str] = None
    amends_law_ids: List[str] = Field(default_factory=list)
    amended_by_doc_ids: List[str] = Field(default_factory=list)
    part_count: Optional[int] = Field(default=None, ge=0)
    chapter_count: Optional[int] = Field(default=None, ge=0)
    section_count: Optional[int] = Field(default=None, ge=0)
    article_count: Optional[int] = Field(default=None, ge=0)
    schedule_count: Optional[int] = Field(default=None, ge=0)
    definition_term_count: Optional[int] = Field(default=None, ge=0)
    defined_terms: List[str] = Field(default_factory=list)
    regulated_subjects: List[str] = Field(default_factory=list)
    obligation_categories: List[str] = Field(default_factory=list)
    penalty_categories: List[str] = Field(default_factory=list)
    procedure_categories: List[str] = Field(default_factory=list)
    exceptions_present: Optional[bool] = None
    cross_references: List[str] = Field(default_factory=list)
    concept_lineage_ids: List[str] = Field(default_factory=list)
    edition_scope: Optional[str] = None
    effective_logic_type: Optional[str] = None


class RegulationDocument(BaseModel):
    document_id: str
    regulation_number: Optional[str] = None
    regulation_year: Optional[int] = None
    regulation_type: Optional[RegulationType] = None
    issuing_authority: Optional[str] = None
    enabled_by_law_id: Optional[str] = None
    enabled_by_law_title: Optional[str] = None
    enabled_by_article_refs: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    is_current_version: Optional[bool] = None
    regulated_entities: List[str] = Field(default_factory=list)
    compliance_subjects: List[str] = Field(default_factory=list)
    reporting_requirements: List[str] = Field(default_factory=list)
    filing_requirements: List[str] = Field(default_factory=list)
    penalty_or_consequence_present: Optional[bool] = None
    procedural_steps: List[str] = Field(default_factory=list)
    amends_regulation_ids: List[str] = Field(default_factory=list)
    related_law_ids: List[str] = Field(default_factory=list)
    cross_references: List[str] = Field(default_factory=list)


class EnactmentNoticeDocument(BaseModel):
    document_id: str
    notice_number: Optional[str] = None
    notice_year: Optional[int] = None
    notice_type: Optional[str] = None
    issuing_authority: Optional[str] = None
    target_doc_id: Optional[str] = None
    target_doc_type: Optional[DocTypeCore] = None
    target_title: Optional[str] = None
    target_law_number: Optional[str] = None
    target_law_year: Optional[int] = None
    commencement_scope_type: Optional[CommencementScopeType] = None
    commencement_date: Optional[str] = None
    commencement_date_text_raw: Optional[str] = None
    target_article_refs: List[str] = Field(default_factory=list)
    excluded_article_refs: List[str] = Field(default_factory=list)
    conditions_precedent: List[str] = Field(default_factory=list)
    territorial_scope: Optional[str] = None
    exception_text_present: Optional[bool] = None
    overrides_prior_notice_ids: List[str] = Field(default_factory=list)
    related_notice_ids: List[str] = Field(default_factory=list)
    linked_version_group_id: Optional[str] = None


class CaseDocument(BaseModel):
    document_id: str
    case_number: Optional[str] = None
    neutral_citation: Optional[str] = None
    court_name: Optional[str] = None
    court_level: Optional[str] = None
    chamber_or_division: Optional[str] = None
    jurisdiction: Optional[str] = None
    filing_date: Optional[str] = None
    hearing_date: Optional[str] = None
    decision_date: Optional[str] = None
    judgment_date: Optional[str] = None
    claimant_names: List[str] = Field(default_factory=list)
    respondent_names: List[str] = Field(default_factory=list)
    appellant_names: List[str] = Field(default_factory=list)
    defendant_names: List[str] = Field(default_factory=list)
    party_names_normalized: List[str] = Field(default_factory=list)
    judge_names: List[str] = Field(default_factory=list)
    presiding_judge: Optional[str] = None
    panel_size: Optional[int] = Field(default=None, ge=0)
    procedural_stage: Optional[str] = None
    cause_of_action: Optional[str] = None
    legal_topics: List[str] = Field(default_factory=list)
    claim_amounts: List[str] = Field(default_factory=list)
    relief_sought: List[str] = Field(default_factory=list)
    issues_present: List[str] = Field(default_factory=list)
    final_disposition: Optional[str] = None
    outcome_for_claimant: Optional[str] = None
    outcome_for_respondent: Optional[str] = None
    cited_law_ids: List[str] = Field(default_factory=list)
    cited_article_refs: List[str] = Field(default_factory=list)
    cited_case_ids: List[str] = Field(default_factory=list)


class PageModel(BaseModel):
    page_id: str
    document_id: str
    pdf_id: str
    page_number: int = Field(ge=0)
    page_label_raw: Optional[str] = None
    page_text_raw: str
    page_text_clean: Optional[str] = None
    page_class: Optional[str] = None
    heading_path: List[str] = Field(default_factory=list)
    contains_dates: bool = False
    contains_money: bool = False
    contains_party_names: bool = False
    contains_judges: bool = False
    contains_article_refs: bool = False
    contains_schedule_refs: bool = False
    contains_amendment_language: bool = False
    contains_commencement_language: bool = False
    dominant_section_kind: Optional[SectionKind] = None
    search_text_compact: Optional[str] = None


class ChunkBase(BaseModel):
    chunk_id: str
    document_id: str
    pdf_id: str
    page_id: str
    page_number: int = Field(ge=0)
    chunk_type: ChunkType = "paragraph"
    chunk_index_on_page: int = Field(ge=0)
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    text_raw: str
    text_clean: Optional[str] = None
    text_compact: Optional[str] = None
    retrieval_text: Optional[str] = None
    embedding_text: Optional[str] = None
    heading_path: List[str] = Field(default_factory=list)
    section_kind: Optional[SectionKind] = None
    structural_level: Optional[int] = Field(default=None, ge=0)
    parent_section_id: Optional[str] = None
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    entity_names: List[str] = Field(default_factory=list)
    entity_names_normalized: List[str] = Field(default_factory=list)
    article_refs: List[str] = Field(default_factory=list)
    schedule_refs: List[str] = Field(default_factory=list)
    law_refs: List[str] = Field(default_factory=list)
    case_refs: List[str] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    money_values: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    topic_tags: List[str] = Field(default_factory=list)
    legal_action_tags: List[str] = Field(default_factory=list)
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    is_current_version: Optional[bool] = None
    version_lineage_id: Optional[str] = None
    canonical_concept_id: Optional[str] = None
    historical_relation_type: Optional[HistoricalRelationType] = None
    exact_terms: List[str] = Field(default_factory=list)
    search_keywords: List[str] = Field(default_factory=list)
    rank_hints: List[str] = Field(default_factory=list)
    answer_candidate_types: List[str] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    parser_flags: List[str] = Field(default_factory=list)
    extraction_method: Optional[str] = None
    tagging_model_version: Optional[str] = None
    last_tagged_at: Optional[str] = None


class LawChunkFacet(BaseModel):
    chunk_id: str
    law_number: Optional[str] = None
    law_year: Optional[int] = None
    article_number: Optional[str] = None
    article_number_normalized: Optional[str] = None
    article_title: Optional[str] = None
    part_ref: Optional[str] = None
    chapter_ref: Optional[str] = None
    section_ref: Optional[str] = None
    schedule_number: Optional[str] = None
    schedule_title: Optional[str] = None
    definition_term: Optional[str] = None
    provision_kind: Optional[ProvisionKind] = None
    administering_authority: Optional[str] = None
    amends_law_ids: List[str] = Field(default_factory=list)
    amended_by_doc_ids: List[str] = Field(default_factory=list)


class RegulationChunkFacet(BaseModel):
    chunk_id: str
    regulation_number: Optional[str] = None
    regulation_year: Optional[int] = None
    regulation_type: Optional[RegulationType] = None
    enabled_by_law_id: Optional[str] = None
    enabled_by_article_refs: List[str] = Field(default_factory=list)
    provision_number: Optional[str] = None
    provision_kind: Optional[ProvisionKind] = None
    regulated_entities: List[str] = Field(default_factory=list)
    compliance_subjects: List[str] = Field(default_factory=list)
    reporting_requirement_present: Optional[bool] = None
    filing_requirement_present: Optional[bool] = None


class EnactmentNoticeChunkFacet(BaseModel):
    chunk_id: str
    notice_number: Optional[str] = None
    notice_year: Optional[int] = None
    target_doc_id: Optional[str] = None
    target_law_number: Optional[str] = None
    target_article_refs: List[str] = Field(default_factory=list)
    excluded_article_refs: List[str] = Field(default_factory=list)
    commencement_scope_type: Optional[CommencementScopeType] = None
    commencement_date: Optional[str] = None
    rule_type: Optional[str] = None
    condition_text_present: Optional[bool] = None


class CaseChunkFacet(BaseModel):
    chunk_id: str
    case_number: Optional[str] = None
    neutral_citation: Optional[str] = None
    court_name: Optional[str] = None
    court_level: Optional[str] = None
    decision_date: Optional[str] = None
    section_kind_case: Optional[CaseSectionKind] = None
    party_names: List[str] = Field(default_factory=list)
    party_roles_present: List[str] = Field(default_factory=list)
    judge_names: List[str] = Field(default_factory=list)
    presiding_judge: Optional[str] = None
    claim_amounts: List[str] = Field(default_factory=list)
    relief_sought: List[str] = Field(default_factory=list)
    disposition_label: Optional[str] = None
    outcome_side: Optional[str] = None
    cited_law_ids: List[str] = Field(default_factory=list)
    cited_case_ids: List[str] = Field(default_factory=list)


class RelationEdge(BaseModel):
    edge_id: str
    source_object_type: SourceObjectType
    source_object_id: str
    target_object_type: SourceObjectType
    target_object_id: str
    edge_type: EdgeType
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    source_page_id: Optional[str] = None
    created_by: Optional[str] = None


class ChunkSearchDocument(BaseModel):
    chunk_id: str
    document_id: str
    pdf_id: str
    page_id: str
    page_number: int = Field(ge=0)
    doc_type: DocTypeCore
    title_normalized: Optional[str] = None
    short_title: Optional[str] = None
    jurisdiction: Optional[str] = None
    status: Optional[str] = None
    is_current_version: Optional[bool] = None
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    heading_path: List[str] = Field(default_factory=list)
    section_kind: Optional[SectionKind] = None
    text_clean: str
    retrieval_text: str
    entity_names: List[str] = Field(default_factory=list)
    article_refs: List[str] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    money_values: List[str] = Field(default_factory=list)
    exact_terms: List[str] = Field(default_factory=list)
    search_keywords: List[str] = Field(default_factory=list)
    version_lineage_id: Optional[str] = None
    canonical_concept_id: Optional[str] = None
    historical_relation_type: Optional[HistoricalRelationType] = None
    law_number: Optional[str] = None
    law_year: Optional[int] = None
    regulation_number: Optional[str] = None
    regulation_year: Optional[int] = None
    notice_number: Optional[str] = None
    notice_year: Optional[int] = None
    case_number: Optional[str] = None
    court_name: Optional[str] = None
    decision_date: Optional[str] = None
    article_number: Optional[str] = None
    section_ref: Optional[str] = None
    schedule_number: Optional[str] = None
    provision_kind: Optional[ProvisionKind] = None
    administering_authority: Optional[str] = None
    enabled_by_law_id: Optional[str] = None
    target_doc_id: Optional[str] = None
    target_article_refs: List[str] = Field(default_factory=list)
    commencement_date: Optional[str] = None
    commencement_scope_type: Optional[CommencementScopeType] = None
    judge_names: List[str] = Field(default_factory=list)
    party_names_normalized: List[str] = Field(default_factory=list)
    final_disposition: Optional[str] = None
    edge_types: List[EdgeType] = Field(default_factory=list)


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: Optional[DocTypeCore] = None
    status: Optional[str] = None
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None
    is_current_version: Optional[bool] = None
    law_number: Optional[str] = None
    article_number: Optional[str] = None
    regulation_number: Optional[str] = None
    notice_number: Optional[str] = None
    case_number: Optional[str] = None
    court_name: Optional[str] = None
    target_doc_id: Optional[str] = None
    version_lineage_id: Optional[str] = None
    canonical_concept_id: Optional[str] = None
    edge_type: Optional[EdgeType] = None
    enabled_by_law_id: Optional[str] = None
    provision_kind: Optional[ProvisionKind] = None
    decision_date: Optional[str] = None


class CorpusSearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1)
    search_profile: str
    top_k: int = Field(ge=1, le=100)
    filters: Optional[SearchFilters] = None


class CorpusSearchItem(BaseModel):
    paragraph_id: str
    page_id: str
    score: float
    snippet: str
    source_page_id: str
    pdf_id: str
    page_num: int
    document_id: str
    chunk_projection: Optional[ChunkSearchDocument] = None
