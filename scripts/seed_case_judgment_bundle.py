#!/usr/bin/env python3
"""Seed case-judgment extraction tables from bundle fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import case_extraction_pg  # noqa: E402
from packages.contracts.case_judgment_bundle_validation import (  # noqa: E402
    FIXTURE_DIR,
    validate_case_judgment_bundle_mirror,
)


SCHEMA_VERSION = "case_judgment_bundle.v1"
PIPELINE_NAME = "pipeline_2_case_judgment_extractor"
PIPELINE_VERSION = "v1"
PROMPT_VERSION = "seed_reference_bundle_v1"
SEED_SOURCE = "reference_bundle"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_fixtures() -> Dict[str, Any]:
    return {
        "cluster": _load_json(FIXTURE_DIR / "arb_016_2023_case_cluster_example.json"),
        "document": _load_json(FIXTURE_DIR / "enf_269_2023_full_judgment_document_example.json"),
        "chunks": _load_json(FIXTURE_DIR / "enf_269_2023_selected_chunks_example.json"),
        "section_map": _load_json(FIXTURE_DIR / "enf_269_2023_section_map.json"),
    }


def _seed_payloads(fixtures: Dict[str, Any]) -> Dict[str, Any]:
    document = fixtures["document"]
    chunks = fixtures["chunks"]
    cluster = fixtures["cluster"]

    document_id = str(document.get("document_id", "")).strip()
    run_id = f"seed_case_judgment_{document_id}"
    document_extraction_id = f"seed_doc_extraction_{document_id}"

    run_row = {
        "run_id": run_id,
        "document_id": document_id,
        "pipeline_name": PIPELINE_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model_name": "reference_bundle",
        "model_reasoning_effort": "none",
        "parser_version": "bundle_fixture",
        "source": SEED_SOURCE,
        "status": "completed",
        "route_status": "routed",
        "token_input": 0,
        "token_output": 0,
        "llm_calls": 0,
        "source_document_revision": "bundle_fixture_v1",
        "metadata": {
            "seed_source": SEED_SOURCE,
            "cluster_case_id": cluster.get("case_cluster_id"),
            "issue_tags": cluster.get("issue_tags", []),
        },
    }

    document_row = {
        "document_extraction_id": document_extraction_id,
        "run_id": run_id,
        "document_id": document_id,
        "schema_version": SCHEMA_VERSION,
        "artifact_version": 1,
        "is_active": True,
        "supersedes_document_extraction_id": None,
        "document_subtype": document.get("document_subtype"),
        "proceeding_no": document.get("proceeding_no"),
        "case_cluster_id": document.get("case_cluster_id"),
        "court_name": document.get("court_name"),
        "court_level": document.get("court_level"),
        "decision_date": document.get("decision_date"),
        "page_count": document.get("page_count"),
        "confidence_score": 1.0,
        "validation_status": "passed",
        "payload": document,
    }

    chunk_rows: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_id = str(chunk.get("chunk_id", "")).strip() or f"seed_chunk_{idx:04d}"
        chunk_rows.append(
            {
                "chunk_extraction_id": f"seed_chunk_extraction_{chunk_id}",
                "run_id": run_id,
                "document_extraction_id": document_extraction_id,
                "paragraph_id": chunk_id,
                "page_id": str(chunk.get("page_id_internal", "")),
                "document_id": document_id,
                "schema_version": SCHEMA_VERSION,
                "artifact_version": 1,
                "chunk_external_id": chunk_id,
                "chunk_type": chunk.get("chunk_type"),
                "section_kind_case": chunk.get("section_kind_case"),
                "paragraph_no": chunk.get("paragraph_no"),
                "page_number_1": chunk.get("page_number_1"),
                "order_effect_label": chunk.get("order_effect_label"),
                "ground_owner": chunk.get("ground_owner"),
                "ground_no": chunk.get("ground_no"),
                "confidence_score": 1.0,
                "validation_status": "passed",
                "payload": chunk,
            }
        )

    qc_rows = [
        {
            "qc_result_id": f"seed_qc_{run_id}_schema",
            "run_id": run_id,
            "document_id": document_id,
            "qc_stage": "seed_validation",
            "status": "passed",
            "severity": "info",
            "message": "bundle fixtures validated and seeded",
            "details": {
                "seed_source": SEED_SOURCE,
                "document_extraction_id": document_extraction_id,
                "chunk_count": len(chunk_rows),
            },
        }
    ]

    return {
        "run": run_row,
        "document": document_row,
        "chunks": chunk_rows,
        "qc": qc_rows,
        "document_extraction_id": document_extraction_id,
    }


def validate_only() -> int:
    errors = validate_case_judgment_bundle_mirror()
    if errors:
        print("Validation failed:")
        for item in errors:
            print(f"- {item}")
        return 1
    print("Validation passed")
    return 0


def seed(*, reseed: bool = False) -> int:
    errors = validate_case_judgment_bundle_mirror()
    if errors:
        print("Validation failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    if not case_extraction_pg.enabled():
        print("Postgres is not enabled (DATABASE_URL or psycopg missing)")
        return 2

    fixtures = _load_fixtures()
    payloads = _seed_payloads(fixtures)

    if reseed:
        deleted = case_extraction_pg.delete_case_runs_by_source(source=SEED_SOURCE, pipeline_name=PIPELINE_NAME)
        print(f"Deleted runs: {deleted}")

    run_row = case_extraction_pg.create_case_extraction_run(payloads["run"])
    doc_row = case_extraction_pg.upsert_case_document_extraction(payloads["document"])
    chunk_rows = case_extraction_pg.upsert_case_chunk_extractions(payloads["chunks"])
    qc_rows = case_extraction_pg.upsert_case_qc_results(payloads["qc"])
    case_extraction_pg.activate_case_document_extraction(payloads["document_extraction_id"])

    print("Seed completed")
    print(json.dumps(
        {
            "run_id": run_row.get("run_id"),
            "document_extraction_id": doc_row.get("document_extraction_id"),
            "chunk_rows": len(chunk_rows),
            "qc_rows": len(qc_rows),
        },
        ensure_ascii=False,
    ))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed case judgment bundle fixtures")
    parser.add_argument("--validate-only", action="store_true", default=False)
    parser.add_argument("--seed-only", action="store_true", default=False)
    parser.add_argument("--reseed", action="store_true", default=False)
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.validate_only and args.seed_only:
        parser.error("use only one mode: --validate-only or --seed-only")

    if args.validate_only:
        return validate_only()

    if args.seed_only:
        return seed(reseed=args.reseed)

    # default behavior: validate then seed
    rc = validate_only()
    if rc != 0:
        return rc
    return seed(reseed=args.reseed)


if __name__ == "__main__":
    raise SystemExit(main())
