from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PUBLIC_DATASET_PATH = ROOT / "public_dataset.json"
DEFAULT_TAXONOMY_PATH = ROOT / "datasets" / "taxonomy" / "public_question_taxonomy.v1.jsonl"

ANSWER_TYPES: Tuple[str, ...] = ("boolean", "number", "date", "name", "names", "free_text")
PRIMARY_ROUTES: Tuple[str, ...] = (
    "case_entity_lookup",
    "case_outcome_or_value",
    "case_cross_compare",
    "law_article_lookup",
    "law_relation_or_history",
    "law_scope_or_definition",
    "cross_law_compare",
    "negative_or_unanswerable",
)
DOCUMENT_SCOPES: Tuple[str, ...] = ("single_doc", "cross_doc")
TARGET_DOC_TYPES: Tuple[str, ...] = ("case", "law", "regulation", "enactment_notice")
EVIDENCE_TOPOLOGIES: Tuple[str, ...] = ("single_page", "multi_page", "multi_doc", "notice_mediated")
TEMPORAL_SENSITIVITIES: Tuple[str, ...] = ("none", "current_version", "historical_version")
ANSWERABILITY_RISKS: Tuple[str, ...] = ("low", "medium", "high")

AnswerTypeExpected = Literal["boolean", "number", "date", "name", "names", "free_text"]
PrimaryRoute = Literal[
    "case_entity_lookup",
    "case_outcome_or_value",
    "case_cross_compare",
    "law_article_lookup",
    "law_relation_or_history",
    "law_scope_or_definition",
    "cross_law_compare",
    "negative_or_unanswerable",
]
DocumentScope = Literal["single_doc", "cross_doc"]
TargetDocType = Literal["case", "law", "regulation", "enactment_notice"]
EvidenceTopology = Literal["single_page", "multi_page", "multi_doc", "notice_mediated"]
TemporalSensitivity = Literal["none", "current_version", "historical_version"]
AnswerabilityRisk = Literal["low", "medium", "high"]


class PublicQuestionTaxonomyRow(BaseModel):
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer_type_expected: AnswerTypeExpected
    primary_route: PrimaryRoute
    document_scope: DocumentScope
    target_doc_types: List[TargetDocType] = Field(min_length=1)
    evidence_topology: EvidenceTopology
    temporal_sensitivity: TemporalSensitivity
    answerability_risk: AnswerabilityRisk
    notes: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("target_doc_types")
    @classmethod
    def _dedupe_target_doc_types(cls, value: List[TargetDocType]) -> List[TargetDocType]:
        seen = set()
        out: List[TargetDocType] = []
        for item in value:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        if not out:
            raise ValueError("target_doc_types must contain at least one value")
        return out


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object row")
        yield payload


def load_public_dataset_questions(path: Path = DEFAULT_PUBLIC_DATASET_PATH) -> List[Dict[str, str]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path}: public dataset must be a JSON array")

    rows: List[Dict[str, str]] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{idx}: public question row must be an object")
        question_id = _as_text(item.get("id"))
        question = _as_text(item.get("question"))
        answer_type = _as_text(item.get("answer_type"))
        if not question_id:
            raise ValueError(f"{path}:{idx}: missing id")
        if not question:
            raise ValueError(f"{path}:{idx}: missing question")
        if answer_type not in ANSWER_TYPES:
            raise ValueError(f"{path}:{idx}: unsupported answer_type={answer_type!r}")
        rows.append({"id": question_id, "question": question, "answer_type": answer_type})
    return rows


def load_public_question_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> List[PublicQuestionTaxonomyRow]:
    if not path.exists():
        raise FileNotFoundError(f"taxonomy dataset not found: {path}")
    rows: List[PublicQuestionTaxonomyRow] = []
    for line_no, payload in enumerate(_iter_jsonl(path), start=1):
        try:
            rows.append(PublicQuestionTaxonomyRow.model_validate(payload))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_no}: taxonomy row validation failed: {exc}") from exc
    if not rows:
        raise ValueError(f"{path}: taxonomy dataset is empty")
    return rows


def validate_taxonomy_coverage(
    public_questions: List[Dict[str, str]],
    taxonomy_rows: List[PublicQuestionTaxonomyRow],
) -> List[str]:
    errors: List[str] = []

    public_by_id: Dict[str, Dict[str, str]] = {}
    for row in public_questions:
        question_id = row["id"]
        if question_id in public_by_id:
            errors.append(f"public_dataset duplicate question id: {question_id}")
            continue
        public_by_id[question_id] = row

    taxonomy_by_id: Dict[str, PublicQuestionTaxonomyRow] = {}
    for row in taxonomy_rows:
        if row.question_id in taxonomy_by_id:
            errors.append(f"taxonomy duplicate question_id: {row.question_id}")
            continue
        taxonomy_by_id[row.question_id] = row

    missing_in_taxonomy = sorted(set(public_by_id) - set(taxonomy_by_id))
    for question_id in missing_in_taxonomy:
        errors.append(f"taxonomy missing question_id: {question_id}")

    unexpected_in_taxonomy = sorted(set(taxonomy_by_id) - set(public_by_id))
    for question_id in unexpected_in_taxonomy:
        errors.append(f"taxonomy has unknown question_id: {question_id}")

    for question_id, public_row in public_by_id.items():
        taxonomy_row = taxonomy_by_id.get(question_id)
        if taxonomy_row is None:
            continue
        if taxonomy_row.question != public_row["question"]:
            errors.append(
                f"taxonomy question text mismatch for {question_id}: "
                f"expected={public_row['question']!r} got={taxonomy_row.question!r}"
            )
        if taxonomy_row.answer_type_expected != public_row["answer_type"]:
            errors.append(
                f"taxonomy answer_type_expected mismatch for {question_id}: "
                f"expected={public_row['answer_type']!r} got={taxonomy_row.answer_type_expected!r}"
            )

    return errors


def load_and_validate_public_taxonomy(
    *,
    public_dataset_path: Path = DEFAULT_PUBLIC_DATASET_PATH,
    taxonomy_path: Path = DEFAULT_TAXONOMY_PATH,
) -> Tuple[List[Dict[str, str]], List[PublicQuestionTaxonomyRow], List[str]]:
    public_questions = load_public_dataset_questions(public_dataset_path)
    taxonomy_rows = load_public_question_taxonomy(taxonomy_path)
    errors = validate_taxonomy_coverage(public_questions, taxonomy_rows)
    return public_questions, taxonomy_rows, errors

