#!/usr/bin/env python3
"""Run a manifest-driven shadow comparison for rules-only vs LLM-assisted chunk semantics."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.artifacts import artifact_path  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from legal_rag_api.state import store  # noqa: E402
from scripts.run_chunk_processing_pilot import (  # noqa: E402
    FIXTURE_PATH,
    _apply_enrichment_result,
    _build_subset_zip_from_pdf_ids,
    _load_json,
    _markdown_from_mapping,
    _prepare_env,
    _project_snapshot,
    _query_map,
    _response_action_matches,
    _run_query_batch,
    _sha256,
    _top3_contains_expected,
    _used_source_page_ids,
    _write_json,
    _write_md,
)
from services.ingest.agentic_enrichment import (  # noqa: E402
    _chunk_assertions,
    _chunk_interpreter_step,
    _chunk_validator_step,
    _merge_existing_registry,
    _projection_agent_step,
    _seed_registry,
)
from services.ingest.chunk_semantics import build_chunk_semantics_client, extract_chunk_semantics  # noqa: E402


DEFAULT_OUTPUT_DIR = artifact_path("competition_runs", "pilots", "chunk_processing_shadow_subset_v2")
DEFAULT_PROJECT_ID = "competition_chunk_processing_shadow_subset_v2"
MANIFEST_PATH = ROOT / "reports" / "corpus_investigation" / "2026-03-12-version-lineage-rca" / "chunk_semantics_shadow_subset_v1.json"
REPO_SUMMARY_DIR = ROOT / "reports" / "corpus_investigation" / "2026-03-12-version-lineage-rca"
REPO_DELIVERABLE_DIR = ROOT / "reports" / "chunk_semantics"


@contextmanager
def _chunk_semantics_enabled(value: bool) -> Iterable[None]:
    import os

    previous = os.environ.get("AGENTIC_ENRICHMENT_LLM_ENABLED")
    os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = "1" if value else "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENTIC_ENRICHMENT_LLM_ENABLED", None)
        else:
            os.environ["AGENTIC_ENRICHMENT_LLM_ENABLED"] = previous


def _load_manifest(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _real_pdf_ids_from_manifest(manifest: Dict[str, Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("source_kind", "")) != "real_chunk":
            continue
        pdf_id = str(item.get("pdf_id", "")).strip()
        if not pdf_id or pdf_id in seen:
            continue
        seen.add(pdf_id)
        out.append(pdf_id)
    return out


def _question_spec_map(fixture: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for field in ("queries", "expanded_queries"):
        out.update(_query_map(fixture, field=field))
    for item in fixture.get("real_corpus_checks", []):
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("check_id", "")).strip()
        if not check_id:
            continue
        out[check_id] = {
            "question_id": check_id,
            "source_reference": item.get("source_reference", {}),
            "category": item.get("coverage_kind", "real_corpus_check"),
            "question": item.get("question"),
            "answer_type": item.get("answer_type"),
            "route_hint": item.get("route_hint"),
            "expected_action": item.get("expected_action", "answer"),
            "expected_answer": item.get("expected_answer"),
            "expected_source_family": item.get("expected_source_family"),
            "expected_pdf_ids": item.get("expected_pdf_ids", []),
        }
    return out


def _query_specs_for_manifest(manifest: Dict[str, Any], fixture: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_map = _question_spec_map(fixture)
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        ids = [str(value).strip() for value in item.get("query_ids", []) if str(value).strip()]
        ids.extend(str(value).strip() for value in item.get("real_corpus_check_ids", []) if str(value).strip())
        for query_id in ids:
            if query_id in seen:
                continue
            seen.add(query_id)
            spec = query_map.get(query_id)
            if spec:
                out.append(spec)
    return out


def _synthetic_fixture_map(fixture: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("fixture_id", "")): item
        for item in fixture.get("semantic_gate_fixtures", [])
        if isinstance(item, dict) and str(item.get("fixture_id", "")).strip()
    }


def _snapshot_indexes(snapshot: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        "documents": {str(item.get("document_id", "")): item for item in snapshot.get("documents", [])},
        "pages": {str(item.get("page_id", "")): item for item in snapshot.get("pages", [])},
        "paragraphs": {str(item.get("paragraph_id", "")): item for item in snapshot.get("paragraphs", [])},
        "projections": {str(item.get("chunk_id", "")): item for item in snapshot.get("chunk_search_documents", [])},
    }


def _projection_assertions(indexes: Dict[str, Dict[str, Dict[str, Any]]], chunk_id: str) -> List[Dict[str, Any]]:
    projection = indexes["projections"].get(chunk_id, {})
    assertions = projection.get("semantic_assertions", [])
    return [item for item in assertions if isinstance(item, dict)] if isinstance(assertions, list) else []


def _assertion_summary(assertions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    relations = [str(item.get("relation_type", "")).strip() for item in assertions if str(item.get("relation_type", "")).strip()]
    has_conditions = any(bool(item.get("conditions")) or bool(str(item.get("condition_text", "")).strip()) for item in assertions)
    has_exceptions = any(bool(item.get("exceptions")) or bool(str(item.get("exception_text", "")).strip()) for item in assertions)
    has_money = any(any(token in json.dumps(item, ensure_ascii=False) for token in ("AED", "USD", "EUR", "GBP", "dirham")) for item in assertions)
    has_deadline = any(
        (
            "within" in json.dumps(item, ensure_ascii=False).lower()
            and "day" in json.dumps(item, ensure_ascii=False).lower()
        )
        or str(item.get("object_type", "")).strip().lower() == "deadline"
        for item in assertions
    )
    has_interest = any("interest" in json.dumps(item, ensure_ascii=False).lower() or "%" in json.dumps(item, ensure_ascii=False) for item in assertions)
    polarity_values = sorted(
        {
            str(item.get("polarity", "")).strip().lower() or "affirmative"
            for item in assertions
        }
    )
    provenance_complete = True
    for item in assertions:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        if not evidence and isinstance(item.get("properties"), dict):
            nested = item.get("properties", {}).get("evidence")
            if isinstance(nested, dict):
                evidence = nested
        if not isinstance(evidence.get("source_page_ids"), list) or not any(str(value).strip() for value in evidence.get("source_page_ids", [])):
            provenance_complete = False
            break
    return {
        "assertion_count": len(assertions),
        "relations": sorted(set(relations)),
        "has_conditions": has_conditions,
        "has_exceptions": has_exceptions,
        "has_conditions_or_exceptions": has_conditions or has_exceptions,
        "has_money": has_money,
        "has_deadline": has_deadline,
        "has_interest": has_interest,
        "polarity_values": polarity_values,
        "provenance_complete": provenance_complete,
    }


def _shadow_query_results(query_specs: Sequence[Dict[str, Any]], responses: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    response_map = {str(item.get("question_id", "")): item for item in responses}
    out: Dict[str, Dict[str, Any]] = {}
    for spec in query_specs:
        qid = str(spec.get("question_id", ""))
        response = response_map.get(qid, {})
        out[qid] = {
            "question_id": qid,
            "expected_action": spec.get("expected_action", "answer"),
            "action_match": _response_action_matches(spec, response) if response else False,
            "answer": response.get("answer"),
            "abstained": response.get("abstained"),
            "route_name": response.get("route_name"),
            "top3_contains_expected": _top3_contains_expected(response, spec) if response else None,
            "used_source_page_ids": _used_source_page_ids(response) if response else [],
        }
    return out


def _query_results_for_item(
    item: Dict[str, Any],
    *,
    before: Dict[str, Dict[str, Any]],
    after: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ids = [str(value).strip() for value in item.get("query_ids", []) if str(value).strip()]
    ids.extend(str(value).strip() for value in item.get("real_corpus_check_ids", []) if str(value).strip())
    return (
        [before[qid] for qid in ids if qid in before],
        [after[qid] for qid in ids if qid in after],
    )


def _negative_polarity(summary: Dict[str, Any]) -> bool:
    values = summary.get("polarity_values", [])
    return isinstance(values, list) and "negative" in values


def _compare_item(
    *,
    item: Dict[str, Any],
    rules_first: Dict[str, Any],
    llm_assisted: Dict[str, Any],
    query_before: List[Dict[str, Any]],
    query_after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    expected = item.get("expected", {}) if isinstance(item.get("expected"), dict) else {}
    rules_unsupported = all(entry.get("action_match") for entry in query_before) if query_before else None
    llm_unsupported = all(entry.get("action_match") for entry in query_after) if query_after else None
    expects_condition = bool(expected.get("condition_or_exception"))
    expects_negative_polarity = bool(expected.get("negative_polarity"))
    expects_money = bool(expected.get("money_amount"))
    expects_deadline = bool(expected.get("deadline"))
    expects_interest = bool(expected.get("interest"))
    expects_unsupported = bool(expected.get("unsupported_or_abstain"))
    return {
        "item_id": item.get("item_id"),
        "evaluation_bucket": item.get("evaluation_bucket"),
        "source_kind": item.get("source_kind"),
        "assertion_count_delta": int(llm_assisted.get("assertion_count", 0) or 0) - int(rules_first.get("assertion_count", 0) or 0),
        "rules_only_condition_present": bool(rules_first.get("has_conditions")),
        "llm_assisted_condition_present": bool(llm_assisted.get("has_conditions")),
        "condition_preserved": bool(llm_assisted.get("has_conditions")) if expects_condition else None,
        "rules_only_exception_present": bool(rules_first.get("has_exceptions")),
        "llm_assisted_exception_present": bool(llm_assisted.get("has_exceptions")),
        "exception_preserved": bool(llm_assisted.get("has_exceptions")) if expects_condition else None,
        "rules_only_negative_polarity": _negative_polarity(rules_first),
        "llm_assisted_negative_polarity": _negative_polarity(llm_assisted),
        "polarity_preserved": _negative_polarity(llm_assisted) if expects_negative_polarity else None,
        "rules_only_money_amount_extracted": bool(rules_first.get("has_money")),
        "llm_assisted_money_amount_extracted": bool(llm_assisted.get("has_money")),
        "money_amount_extracted": bool(llm_assisted.get("has_money")) if expects_money else None,
        "rules_only_deadline_extracted": bool(rules_first.get("has_deadline")),
        "llm_assisted_deadline_extracted": bool(llm_assisted.get("has_deadline")),
        "deadline_extracted": bool(llm_assisted.get("has_deadline")) if expects_deadline else None,
        "rules_only_interest_extracted": bool(rules_first.get("has_interest")),
        "llm_assisted_interest_extracted": bool(llm_assisted.get("has_interest")),
        "interest_extracted": bool(llm_assisted.get("has_interest")) if expects_interest else None,
        "rules_only_unsupported_or_abstain_behavior": rules_unsupported,
        "llm_assisted_unsupported_or_abstain_behavior": llm_unsupported,
        "unsupported_or_abstain_behavior": llm_unsupported if expects_unsupported else None,
        "rules_only_provenance_complete": bool(rules_first.get("provenance_complete")),
        "llm_assisted_provenance_complete": bool(llm_assisted.get("provenance_complete")),
        "provenance_complete": bool(rules_first.get("provenance_complete")) and bool(llm_assisted.get("provenance_complete")),
    }


def _run_synthetic_fixture_shadow(*, manifest_item: Dict[str, Any], fixture_item: Dict[str, Any]) -> Dict[str, Any]:
    client = build_chunk_semantics_client()
    paragraph_payload = fixture_item.get("paragraph", {}) if isinstance(fixture_item.get("paragraph"), dict) else {}
    projection_payload = fixture_item.get("projection", {}) if isinstance(fixture_item.get("projection"), dict) else {}
    paragraph = {
        "paragraph_id": f"{fixture_item['fixture_id']}_paragraph",
        "document_id": f"{fixture_item['fixture_id']}_document",
        "page_id": f"{fixture_item['fixture_id']}_page",
        "text": str(paragraph_payload.get("text", "")),
        "section_kind": paragraph_payload.get("section_kind"),
        "paragraph_class": paragraph_payload.get("paragraph_class"),
        "article_refs": list(paragraph_payload.get("article_refs", [])) if isinstance(paragraph_payload.get("article_refs"), list) else [],
    }
    page = {
        "page_id": f"{fixture_item['fixture_id']}_page",
        "document_id": f"{fixture_item['fixture_id']}_document",
        "source_page_id": f"{fixture_item['fixture_id']}_0",
        "page_num": 0,
    }
    document = {
        "document_id": f"{fixture_item['fixture_id']}_document",
        "pdf_id": str((fixture_item.get("source_reference") or {}).get("label") or fixture_item["fixture_id"]),
        "doc_type": str(fixture_item.get("doc_type", "law")),
        "title": str((fixture_item.get("source_reference") or {}).get("label") or fixture_item["fixture_id"]),
    }
    projection = {
        "chunk_id": paragraph["paragraph_id"],
        "doc_type": str(fixture_item.get("doc_type", "law")),
        "heading_path": list(projection_payload.get("heading_path", [])) if isinstance(projection_payload.get("heading_path"), list) else [],
        "article_number": projection_payload.get("article_number"),
        "article_title": projection_payload.get("article_title"),
        "part_ref": projection_payload.get("part_ref"),
        "section_ref": projection_payload.get("section_ref"),
        "section_kind_case": projection_payload.get("section_kind_case"),
        "case_number": projection_payload.get("case_number"),
        "court_name": projection_payload.get("court_name"),
    }
    with _chunk_semantics_enabled(False):
        rules = extract_chunk_semantics(client=client, paragraph=paragraph, page=page, document=document, projection=projection)
    with _chunk_semantics_enabled(True):
        llm = extract_chunk_semantics(client=client, paragraph=paragraph, page=page, document=document, projection=projection)
    rules_summary = _assertion_summary(rules.payload.get("propositions", []) if isinstance(rules.payload.get("propositions"), list) else [])
    llm_summary = _assertion_summary(llm.payload.get("propositions", []) if isinstance(llm.payload.get("propositions"), list) else [])
    return {
        "item_id": str(manifest_item.get("item_id", "")),
        "shadow_kind": "synthetic_fixture",
        "fixture_classification": "synthetic_guardrail_fixture",
        "source_reference": {
            "kind": "synthetic_fixture",
            "fixture_id": fixture_item.get("fixture_id"),
            "label": (fixture_item.get("source_reference") or {}).get("label"),
        },
        "manifest": manifest_item,
        "rules_first": rules_summary,
        "llm_assisted": llm_summary,
        "query_results_before": [],
        "query_results_after": [],
        "rules_first_prompt_version": rules.prompt_version,
        "llm_prompt_version": llm.prompt_version,
        "comparison": _compare_item(item=manifest_item, rules_first=rules_summary, llm_assisted=llm_summary, query_before=[], query_after=[]),
    }


def _build_shadow_subset_report(
    *,
    manifest: Dict[str, Any],
    fixture: Dict[str, Any],
    snapshot_rules: Dict[str, List[Dict[str, Any]]],
    snapshot_llm: Dict[str, List[Dict[str, Any]]],
    shadow_query_before: Dict[str, Dict[str, Any]],
    shadow_query_after: Dict[str, Dict[str, Any]],
    precomputed_real_rows: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    synthetic_fixture_lookup = _synthetic_fixture_map(fixture)
    rules_indexes = _snapshot_indexes(snapshot_rules)
    llm_indexes = _snapshot_indexes(snapshot_llm)
    rows: List[Dict[str, Any]] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        source_kind = str(item.get("source_kind", "")).strip()
        query_before, query_after = _query_results_for_item(item, before=shadow_query_before, after=shadow_query_after)
        if source_kind == "synthetic_fixture":
            fixture_id = str(item.get("fixture_id", "")).strip()
            rows.append(_run_synthetic_fixture_shadow(manifest_item=item, fixture_item=synthetic_fixture_lookup[fixture_id]))
            continue
        if precomputed_real_rows and str(item.get("item_id", "")).strip() in precomputed_real_rows:
            row = dict(precomputed_real_rows[str(item.get("item_id", "")).strip()])
            row["rules_first"] = {**row.get("rules_first", {}), "query_results": query_before}
            row["llm_assisted"] = {**row.get("llm_assisted", {}), "query_results": query_after}
            row["comparison"] = _compare_item(
                item=item,
                rules_first=row.get("rules_first", {}),
                llm_assisted=row.get("llm_assisted", {}),
                query_before=query_before,
                query_after=query_after,
            )
            rows.append(row)
            continue

        chunk_id = str(item.get("chunk_id", "")).strip()
        paragraph = rules_indexes["paragraphs"].get(chunk_id)
        page = rules_indexes["pages"].get(str(item.get("page_id", "")).strip())
        document = rules_indexes["documents"].get(str(item.get("doc_id", "")).strip())
        if paragraph is None or page is None or document is None:
            raise RuntimeError(f"manifest item {item.get('item_id')} could not be resolved in imported subset")
        rules_projection = rules_indexes["projections"].get(chunk_id, {})
        rules_summary = _assertion_summary(_projection_assertions(rules_indexes, chunk_id))
        llm_summary = _assertion_summary(_projection_assertions(llm_indexes, chunk_id))
        rows.append(
            {
                "item_id": str(item.get("item_id", "")),
                "shadow_kind": source_kind,
                "fixture_classification": "real_corpus_fixture",
                "source_reference": {
                    "kind": "real_chunk",
                    "pdf_id": item.get("pdf_id"),
                    "doc_id": item.get("doc_id"),
                    "page_id": item.get("page_id"),
                    "chunk_id": item.get("chunk_id"),
                    "heading_path": rules_projection.get("heading_path", []),
                },
                "manifest": item,
                "rules_first": {
                    **rules_summary,
                    "query_results": query_before,
                },
                "llm_assisted": {
                    **llm_summary,
                    "query_results": query_after,
                },
                "comparison": _compare_item(
                    item=item,
                    rules_first=rules_summary,
                    llm_assisted=llm_summary,
                    query_before=query_before,
                    query_after=query_after,
                ),
            }
        )
    return {
        "report_version": "chunk_processing_shadow_subset_report_v2",
        "item_count": len(rows),
        "items": rows,
    }


def _run_real_chunk_shadow_items(
    *,
    manifest: Dict[str, Any],
    snapshot_rules: Dict[str, List[Dict[str, Any]]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    rules_indexes = _snapshot_indexes(snapshot_rules)
    client = build_chunk_semantics_client()
    registry = _merge_existing_registry(_seed_registry(), list(store.ontology_registry_entries.values()))
    updated_paragraphs: Dict[str, Dict[str, Any]] = {}
    updated_projections: Dict[str, Dict[str, Any]] = {}
    projected_relation_edges: List[Dict[str, Any]] = []
    chunk_assertions: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    for item in manifest.get("items", []):
        if not isinstance(item, dict) or str(item.get("source_kind", "")).strip() != "real_chunk":
            continue
        chunk_id = str(item.get("chunk_id", "")).strip()
        paragraph = rules_indexes["paragraphs"].get(chunk_id)
        page = rules_indexes["pages"].get(str(item.get("page_id", "")).strip())
        document = rules_indexes["documents"].get(str(item.get("doc_id", "")).strip())
        projection = rules_indexes["projections"].get(chunk_id, {})
        if paragraph is None or page is None or document is None:
            raise RuntimeError(f"manifest item {item.get('item_id')} could not be resolved in imported subset")

        with _chunk_semantics_enabled(False):
            rules_payload, rules_stage = _chunk_interpreter_step(client, paragraph, page, document, projection)
        rules_assertions, _ = _chunk_validator_step(
            _chunk_assertions(
                paragraph=paragraph,
                page=page,
                document=document,
                chunk_projection=projection,
                llm_payload=rules_payload,
            )
        )
        rules_summary = _assertion_summary(rules_assertions)

        with _chunk_semantics_enabled(True):
            llm_payload, llm_stage = _chunk_interpreter_step(client, paragraph, page, document, projection)
        llm_assertions, _ = _chunk_validator_step(
            _chunk_assertions(
                paragraph=paragraph,
                page=page,
                document=document,
                chunk_projection=projection,
                llm_payload=llm_payload,
            )
        )
        llm_summary = _assertion_summary(llm_assertions)
        (paragraph_update, projection_update, edges), _ = _projection_agent_step(
            assertions=llm_assertions,
            semantic_payload=llm_payload,
            paragraph=paragraph,
            chunk_projection=projection,
            registry=registry,
        )
        updated_paragraphs[str(paragraph_update.get("paragraph_id", ""))] = paragraph_update
        updated_projections[str(projection_update.get("chunk_id", ""))] = projection_update
        projected_relation_edges.extend(edges)
        chunk_assertions.extend(llm_assertions)
        rows.append(
            {
                "item_id": str(item.get("item_id", "")),
                "shadow_kind": "real_chunk",
                "fixture_classification": "real_corpus_fixture",
                "source_reference": {
                    "kind": "real_chunk",
                    "pdf_id": item.get("pdf_id"),
                    "doc_id": item.get("doc_id"),
                    "page_id": item.get("page_id"),
                    "chunk_id": item.get("chunk_id"),
                    "heading_path": projection.get("heading_path", []),
                },
                "manifest": item,
                "rules_first": rules_summary,
                "llm_assisted": llm_summary,
                "rules_first_prompt_version": rules_stage.get("payload", {}).get("llm_prompt_version"),
                "llm_prompt_version": llm_stage.get("payload", {}).get("llm_prompt_version"),
            }
        )
    enrichment_overlay = {
        "updated_paragraphs": updated_paragraphs,
        "updated_chunk_projections": updated_projections,
        "projected_relation_edges": projected_relation_edges,
        "chunk_assertions": chunk_assertions,
        "registry_entries": list(registry.values()),
        "updated_documents": {},
        "document_views": [],
    }
    return enrichment_overlay, rows


def _build_shadow_delta_report(shadow_subset: Dict[str, Any]) -> Dict[str, Any]:
    rows = [item.get("comparison", {}) for item in shadow_subset.get("items", []) if isinstance(item.get("comparison"), dict)]
    bucket_counts: Dict[str, int] = {}
    bucket_improved_counts: Dict[str, int] = {}
    improved_assertions = 0
    condition_preserved_count = 0
    exception_preserved_count = 0
    polarity_preserved_count = 0
    money_amount_extracted_count = 0
    deadline_extracted_count = 0
    interest_extracted_count = 0
    unsupported_or_abstain_behavior_count = 0
    provenance_complete_count = 0
    condition_expected_count = 0
    exception_expected_count = 0
    polarity_expected_count = 0
    money_expected_count = 0
    deadline_expected_count = 0
    interest_expected_count = 0
    unsupported_expected_count = 0
    for item in rows:
        bucket = str(item.get("evaluation_bucket", "unknown"))
        bucket_counts[bucket] = int(bucket_counts.get(bucket, 0)) + 1
        if int(item.get("assertion_count_delta", 0) or 0) >= 0:
            improved_assertions += 1
            bucket_improved_counts[bucket] = int(bucket_improved_counts.get(bucket, 0)) + 1
        if item.get("condition_preserved") is not None:
            condition_expected_count += 1
        if item.get("condition_preserved") is True:
            condition_preserved_count += 1
        if item.get("exception_preserved") is not None:
            exception_expected_count += 1
        if item.get("exception_preserved") is True:
            exception_preserved_count += 1
        if item.get("polarity_preserved") is not None:
            polarity_expected_count += 1
        if item.get("polarity_preserved") is True:
            polarity_preserved_count += 1
        if item.get("money_amount_extracted") is not None:
            money_expected_count += 1
        if item.get("money_amount_extracted") is True:
            money_amount_extracted_count += 1
        if item.get("deadline_extracted") is not None:
            deadline_expected_count += 1
        if item.get("deadline_extracted") is True:
            deadline_extracted_count += 1
        if item.get("interest_extracted") is not None:
            interest_expected_count += 1
        if item.get("interest_extracted") is True:
            interest_extracted_count += 1
        if item.get("unsupported_or_abstain_behavior") is not None:
            unsupported_expected_count += 1
        if item.get("unsupported_or_abstain_behavior") is True:
            unsupported_or_abstain_behavior_count += 1
        if item.get("provenance_complete"):
            provenance_complete_count += 1
    return {
        "report_version": "chunk_processing_shadow_delta_report_v2",
        "item_count": len(rows),
        "improved_assertion_count": improved_assertions,
        "condition_preserved_count": condition_preserved_count,
        "condition_expected_count": condition_expected_count,
        "exception_preserved_count": exception_preserved_count,
        "exception_expected_count": exception_expected_count,
        "polarity_preserved_count": polarity_preserved_count,
        "polarity_expected_count": polarity_expected_count,
        "money_amount_extracted_count": money_amount_extracted_count,
        "money_expected_count": money_expected_count,
        "deadline_extracted_count": deadline_extracted_count,
        "deadline_expected_count": deadline_expected_count,
        "interest_extracted_count": interest_extracted_count,
        "interest_expected_count": interest_expected_count,
        "unsupported_or_abstain_behavior_count": unsupported_or_abstain_behavior_count,
        "unsupported_expected_count": unsupported_expected_count,
        "provenance_complete_count": provenance_complete_count,
        "bucket_counts": bucket_counts,
        "bucket_improved_counts": bucket_improved_counts,
        "items": rows,
    }


def _summary_results_payload(shadow_delta: Dict[str, Any]) -> Dict[str, Any]:
    covered_buckets = sorted(shadow_delta.get("bucket_counts", {}).keys())
    recommendation = "remain_experimental"
    if (
        shadow_delta.get("item_count", 0) >= 10
        and shadow_delta.get("provenance_complete_count", 0) == shadow_delta.get("item_count", 0)
        and shadow_delta.get("improved_assertion_count", 0) >= max(1, shadow_delta.get("item_count", 0) // 2)
    ):
        recommendation = "proceed_to_next_gated_expansion"
    return {
        "summary_version": "chunk_processing_shadow_subset_summary_v1",
        "item_count": shadow_delta.get("item_count", 0),
        "covered_buckets": covered_buckets,
        "improved_assertion_count": shadow_delta.get("improved_assertion_count", 0),
        "condition_preserved_count": shadow_delta.get("condition_preserved_count", 0),
        "condition_expected_count": shadow_delta.get("condition_expected_count", 0),
        "exception_preserved_count": shadow_delta.get("exception_preserved_count", 0),
        "exception_expected_count": shadow_delta.get("exception_expected_count", 0),
        "polarity_preserved_count": shadow_delta.get("polarity_preserved_count", 0),
        "polarity_expected_count": shadow_delta.get("polarity_expected_count", 0),
        "money_amount_extracted_count": shadow_delta.get("money_amount_extracted_count", 0),
        "money_expected_count": shadow_delta.get("money_expected_count", 0),
        "deadline_extracted_count": shadow_delta.get("deadline_extracted_count", 0),
        "deadline_expected_count": shadow_delta.get("deadline_expected_count", 0),
        "interest_extracted_count": shadow_delta.get("interest_extracted_count", 0),
        "interest_expected_count": shadow_delta.get("interest_expected_count", 0),
        "unsupported_or_abstain_behavior_count": shadow_delta.get("unsupported_or_abstain_behavior_count", 0),
        "unsupported_expected_count": shadow_delta.get("unsupported_expected_count", 0),
        "provenance_complete_count": shadow_delta.get("provenance_complete_count", 0),
        "recommendation": recommendation,
    }


def _summary_markdown(summary: Dict[str, Any], artifact_root: Path) -> str:
    lines = [
        "# Shadow Subset Summary",
        "",
        f"- Item count: `{summary['item_count']}`",
        f"- Covered buckets: `{', '.join(summary['covered_buckets'])}`",
        f"- Improved assertion count: `{summary['improved_assertion_count']}`",
        f"- Condition preserved: `{summary['condition_preserved_count']}/{summary['condition_expected_count']}`",
        f"- Exception preserved: `{summary['exception_preserved_count']}/{summary['exception_expected_count']}`",
        f"- Polarity preserved: `{summary['polarity_preserved_count']}/{summary['polarity_expected_count']}`",
        f"- Money extracted: `{summary['money_amount_extracted_count']}/{summary['money_expected_count']}`",
        f"- Deadline extracted: `{summary['deadline_extracted_count']}/{summary['deadline_expected_count']}`",
        f"- Interest extracted: `{summary['interest_extracted_count']}/{summary['interest_expected_count']}`",
        f"- Unsupported/abstain behavior: `{summary['unsupported_or_abstain_behavior_count']}/{summary['unsupported_expected_count']}`",
        f"- Provenance complete count: `{summary['provenance_complete_count']}`",
        f"- Recommendation: `{summary['recommendation']}`",
        "",
        "Canonical heavy artifacts:",
        "",
        f"- [shadow_subset_report.json]({artifact_root / 'shadow_subset_report.json'})",
        f"- [shadow_delta_report.json]({artifact_root / 'shadow_delta_report.json'})",
    ]
    return "\n".join(lines) + "\n"


def _delta_markdown(shadow_delta: Dict[str, Any]) -> str:
    lines = [
        "# Shadow Subset Delta",
        "",
        "| Item | Bucket | Delta | Conditions | Exceptions | Polarity | Money | Deadline | Interest | Abstain | Provenance |",
        "|---|---|---:|---|---|---|---|---|---|---|---|",
    ]
    for item in shadow_delta.get("items", []):
        lines.append(
            "| {item_id} | {evaluation_bucket} | {assertion_count_delta} | {condition_preserved} | {exception_preserved} | {polarity_preserved} | {money_amount_extracted} | {deadline_extracted} | {interest_extracted} | {unsupported_or_abstain_behavior} | {provenance_complete} |".format(
                item_id=item.get("item_id"),
                evaluation_bucket=item.get("evaluation_bucket"),
                assertion_count_delta=item.get("assertion_count_delta"),
                condition_preserved="yes" if item.get("condition_preserved") else "no",
                exception_preserved="yes" if item.get("exception_preserved") else "no",
                polarity_preserved="yes" if item.get("polarity_preserved") else "no",
                money_amount_extracted="yes" if item.get("money_amount_extracted") else "no",
                deadline_extracted="yes" if item.get("deadline_extracted") else "no",
                interest_extracted="yes" if item.get("interest_extracted") else "no",
                unsupported_or_abstain_behavior="yes" if item.get("unsupported_or_abstain_behavior") is True else ("n/a" if item.get("unsupported_or_abstain_behavior") is None else "no"),
                provenance_complete="yes" if item.get("provenance_complete") else "no",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chunk semantic shadow subset evaluation")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--repo-summary-dir", default=str(REPO_SUMMARY_DIR))
    parser.add_argument("--repo-deliverable-dir", default=str(REPO_DELIVERABLE_DIR))
    args = parser.parse_args()

    _prepare_env()
    # This shadow run compares chunk semantics only; title-page metadata normalization
    # would just burn time and tokens without changing the evaluation surface.
    import os

    os.environ["CORPUS_METADATA_NORMALIZER_PROVIDER"] = "openai"
    os.environ["CORPUS_METADATA_NORMALIZER_MODEL"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    fixture = _load_json(FIXTURE_PATH)
    manifest = _load_manifest(Path(args.manifest).resolve())
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_summary_dir = Path(args.repo_summary_dir).resolve()
    repo_summary_dir.mkdir(parents=True, exist_ok=True)
    repo_deliverable_dir = Path(args.repo_deliverable_dir).resolve()
    repo_deliverable_dir.mkdir(parents=True, exist_ok=True)

    subset_zip_path = output_dir / "chunk_processing_shadow_subset_documents.zip"
    _build_subset_zip_from_pdf_ids(pdf_ids=_real_pdf_ids_from_manifest(manifest), output_path=subset_zip_path)

    print("[shadow_subset] import_start", flush=True)
    corpus_router.import_zip(
        {
            "project_id": str(args.project_id),
            "blob_url": str(subset_zip_path.resolve()),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        }
    )
    print("[shadow_subset] import_complete", flush=True)
    fixture_scope = {"documents": [{"pdf_id": pdf_id} for pdf_id in _real_pdf_ids_from_manifest(manifest)]}
    snapshot_rules = _project_snapshot(str(args.project_id), fixture_scope)
    shadow_queries = _query_specs_for_manifest(manifest, fixture)
    print("[shadow_subset] rules_queries_start", flush=True)
    shadow_query_before = _shadow_query_results(
        shadow_queries,
        asyncio.run(_run_query_batch(str(args.project_id), shadow_queries, dataset_id="chunk_processing_shadow_subset_rules_v2")),
    )
    print("[shadow_subset] rules_queries_complete", flush=True)

    print("[shadow_subset] llm_enrichment_start", flush=True)
    enrichment, precomputed_real_rows = _run_real_chunk_shadow_items(
        manifest=manifest,
        snapshot_rules=snapshot_rules,
    )
    _apply_enrichment_result(str(args.project_id), enrichment)
    print("[shadow_subset] llm_enrichment_complete", flush=True)
    snapshot_llm = _project_snapshot(str(args.project_id), fixture_scope)
    print("[shadow_subset] llm_queries_start", flush=True)
    shadow_query_after = _shadow_query_results(
        shadow_queries,
        asyncio.run(_run_query_batch(str(args.project_id), shadow_queries, dataset_id="chunk_processing_shadow_subset_llm_v2")),
    )
    print("[shadow_subset] llm_queries_complete", flush=True)

    shadow_subset = _build_shadow_subset_report(
        manifest=manifest,
        fixture=fixture,
        snapshot_rules=snapshot_rules,
        snapshot_llm=snapshot_llm,
        shadow_query_before=shadow_query_before,
        shadow_query_after=shadow_query_after,
        precomputed_real_rows={str(row.get("item_id", "")): row for row in precomputed_real_rows},
    )
    shadow_delta = _build_shadow_delta_report(shadow_subset)
    summary_payload = _summary_results_payload(shadow_delta)

    _write_json(output_dir / "shadow_subset_report.json", shadow_subset)
    _write_md(output_dir / "shadow_subset_report.md", _markdown_from_mapping("Shadow Subset Report", shadow_subset))
    _write_json(output_dir / "shadow_delta_report.json", shadow_delta)
    _write_md(output_dir / "shadow_delta_report.md", _markdown_from_mapping("Shadow Delta Report", shadow_delta))
    _write_json(output_dir / "shadow_subset_manifest_resolved.json", manifest)
    _write_json(
        output_dir / "shadow_bundle_manifest.json",
        {
            "report_version": "chunk_processing_shadow_bundle_manifest_v2",
            "files": [
                {"path": "shadow_subset_report.json", "sha256": _sha256(output_dir / "shadow_subset_report.json")},
                {"path": "shadow_delta_report.json", "sha256": _sha256(output_dir / "shadow_delta_report.json")},
                {"path": "shadow_subset_manifest_resolved.json", "sha256": _sha256(output_dir / "shadow_subset_manifest_resolved.json")},
            ],
        },
    )

    _write_json(repo_summary_dir / "shadow_subset_results.json", {"summary": summary_payload, "items": shadow_delta.get("items", [])})
    _write_md(repo_summary_dir / "shadow_subset_summary.md", _summary_markdown(summary_payload, output_dir))
    _write_md(repo_summary_dir / "shadow_subset_delta.md", _delta_markdown(shadow_delta))
    _write_json(repo_deliverable_dir / "shadow_subset_manifest_v1.json", manifest)
    _write_json(
        repo_deliverable_dir / "shadow_subset_results_v1.json",
        {"summary": summary_payload, "items": shadow_delta.get("items", [])},
    )
    _write_md(repo_deliverable_dir / "shadow_subset_summary_v1.md", _summary_markdown(summary_payload, output_dir))
    print("[shadow_subset] completed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
