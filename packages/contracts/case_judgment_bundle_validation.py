from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "case_judgment_bundle"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "case_judgment_bundle" / "examples"

SCHEMA_FILES = (
    "case_cluster.schema.json",
    "full_judgment_case_chunk.schema.json",
    "full_judgment_case_document.schema.json",
    "full_judgment_case_page.schema.json",
    "workflow_state_case_parse.schema.json",
    "workflow_state_eval.schema.json",
)

FIXTURE_FILES = (
    "arb_016_2023_case_cluster_example.json",
    "enf_269_2023_full_judgment_document_example.json",
    "enf_269_2023_selected_chunks_example.json",
    "enf_269_2023_section_map.json",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return _is_integer(value)
    if type_name == "number":
        return _is_number(value)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    return True


def _type_list(schema: dict[str, Any]) -> list[str]:
    type_spec = schema.get("type")
    if type_spec is None:
        return []
    if isinstance(type_spec, str):
        return [type_spec]
    if isinstance(type_spec, list):
        out: list[str] = []
        for item in type_spec:
            if isinstance(item, str):
                out.append(item)
        return out
    return []


def _validate_date_string(value: str, path: str, errors: list[str]) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        errors.append(f"{path}: invalid date format, expected YYYY-MM-DD")


def _validate_schema_node(schema: dict[str, Any], payload: Any, path: str, errors: list[str]) -> None:
    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}: expected const={schema['const']!r}, got {payload!r}")
        return

    if "enum" in schema and payload not in schema["enum"]:
        errors.append(f"{path}: value {payload!r} not in enum {schema['enum']!r}")
        return

    expected_types = _type_list(schema)
    if expected_types:
        if not any(_matches_type(payload, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected_types!r}, got {type(payload).__name__}")
            return

    if schema.get("format") == "date" and isinstance(payload, str):
        _validate_date_string(payload, path, errors)

    if isinstance(payload, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in payload:
                    errors.append(f"{path}: missing required key {key!r}")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, value in payload.items():
                node = properties.get(key)
                if isinstance(node, dict):
                    _validate_schema_node(node, value, f"{path}.{key}", errors)
        return

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, value in enumerate(payload):
                _validate_schema_node(item_schema, value, f"{path}[{idx}]", errors)


def validate_payload(schema: dict[str, Any], payload: Any, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    _validate_schema_node(schema, payload, path, errors)
    return errors


def load_bundle_mirror() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    fixtures: dict[str, Any] = {}

    for name in SCHEMA_FILES:
        schema_path = SCHEMA_DIR / name
        if not schema_path.exists():
            raise FileNotFoundError(f"missing schema file: {schema_path}")
        loaded = _load_json(schema_path)
        if not isinstance(loaded, dict):
            raise ValueError(f"schema must be object: {schema_path}")
        schemas[name] = loaded

    for name in FIXTURE_FILES:
        fixture_path = FIXTURE_DIR / name
        if not fixture_path.exists():
            raise FileNotFoundError(f"missing fixture file: {fixture_path}")
        fixtures[name] = _load_json(fixture_path)

    return schemas, fixtures


def validate_case_judgment_bundle_mirror() -> list[str]:
    schemas, fixtures = load_bundle_mirror()
    errors: list[str] = []

    cluster_payload = fixtures["arb_016_2023_case_cluster_example.json"]
    errors.extend(
        validate_payload(
            schemas["case_cluster.schema.json"],
            cluster_payload,
            path="arb_016_2023_case_cluster_example",
        )
    )

    document_payload = fixtures["enf_269_2023_full_judgment_document_example.json"]
    errors.extend(
        validate_payload(
            schemas["full_judgment_case_document.schema.json"],
            document_payload,
            path="enf_269_2023_full_judgment_document_example",
        )
    )

    chunks_payload = fixtures["enf_269_2023_selected_chunks_example.json"]
    if not isinstance(chunks_payload, list):
        errors.append("enf_269_2023_selected_chunks_example: expected array payload")
    else:
        for idx, chunk in enumerate(chunks_payload):
            errors.extend(
                validate_payload(
                    schemas["full_judgment_case_chunk.schema.json"],
                    chunk,
                    path=f"enf_269_2023_selected_chunks_example[{idx}]",
                )
            )

    page_map = document_payload.get("page_map", [])
    if not isinstance(page_map, list):
        errors.append("enf_269_2023_full_judgment_document_example.page_map: expected array")
    else:
        for idx, page in enumerate(page_map):
            errors.extend(
                validate_payload(
                    schemas["full_judgment_case_page.schema.json"],
                    page,
                    path=f"enf_269_2023_full_judgment_document_example.page_map[{idx}]",
                )
            )

    section_map_payload = fixtures["enf_269_2023_section_map.json"]
    if section_map_payload != document_payload.get("section_map"):
        errors.append("enf_269_2023_section_map: fixture does not match document.section_map")

    return errors
