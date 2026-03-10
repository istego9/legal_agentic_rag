from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.public_question_taxonomy import (  # noqa: E402
    ANSWERABILITY_RISKS,
    ANSWER_TYPES,
    DEFAULT_TAXONOMY_PATH,
    DOCUMENT_SCOPES,
    EVIDENCE_TOPOLOGIES,
    PRIMARY_ROUTES,
    TARGET_DOC_TYPES,
    TEMPORAL_SENSITIVITIES,
    load_and_validate_public_taxonomy,
    load_public_question_taxonomy,
)


SCHEMA_PATH = ROOT / "schemas" / "public_question_taxonomy_row.schema.json"


def test_taxonomy_rows_validate_against_contract() -> None:
    rows = load_public_question_taxonomy()
    assert len(rows) == 100
    assert all(row.question_id for row in rows)


def test_taxonomy_coverage_is_one_to_one_with_public_dataset() -> None:
    public_questions, taxonomy_rows, errors = load_and_validate_public_taxonomy()
    assert not errors
    assert len(taxonomy_rows) == len(public_questions)


def test_taxonomy_question_ids_are_unique() -> None:
    rows = load_public_question_taxonomy()
    question_ids = [row.question_id for row in rows]
    assert len(question_ids) == len(set(question_ids))


def test_taxonomy_schema_enum_sets_match_contract_constants() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["properties"]
    assert tuple(props["answer_type_expected"]["enum"]) == ANSWER_TYPES
    assert tuple(props["primary_route"]["enum"]) == PRIMARY_ROUTES
    assert tuple(props["document_scope"]["enum"]) == DOCUMENT_SCOPES
    assert tuple(props["target_doc_types"]["items"]["enum"]) == TARGET_DOC_TYPES
    assert tuple(props["evidence_topology"]["enum"]) == EVIDENCE_TOPOLOGIES
    assert tuple(props["temporal_sensitivity"]["enum"]) == TEMPORAL_SENSITIVITIES
    assert tuple(props["answerability_risk"]["enum"]) == ANSWERABILITY_RISKS
    assert Path(DEFAULT_TAXONOMY_PATH).exists()

