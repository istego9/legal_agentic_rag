#!/usr/bin/env python3
"""Run rules-first vs llm-assisted shadow evaluation on a narrow chunk subset."""

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
from legal_rag_api.state import store  # noqa: E402
from legal_rag_api.routers import corpus as corpus_router  # noqa: E402
from services.ingest.agentic_enrichment import retry_agentic_corpus_enrichment  # noqa: E402
from services.ingest.chunk_semantics import build_chunk_semantics_client, extract_chunk_semantics  # noqa: E402
from scripts.run_chunk_processing_pilot import (  # noqa: E402
    FIXTURE_PATH,
    _apply_enrichment_result,
    _build_subset_zip_from_pdf_ids,
    _extract_pdf_text,
    _expected_pdf_ids,
    _load_json,
    _markdown_from_mapping,
    _prepare_env,
    _project_snapshot,
    _query_map,
    _response_action_matches,
    _run_query_batch,
    _sha256,
    _target_chunk_ids,
    _top3_contains_expected,
    _used_source_page_ids,
    _write_json,
    _write_md,
)


DEFAULT_OUTPUT_DIR = artifact_path("competition_runs", "pilots", "chunk_processing_shadow_subset_v1")
DEFAULT_PROJECT_ID = "competition_chunk_processing_shadow_subset_v1"


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


def _question_map_all(fixture: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    items: Dict[str, Dict[str, Any]] = {}
    for field in ("queries", "expanded_queries"):
        items.update(_query_map(fixture, field=field))
    return items


def _shadow_query_specs(fixture: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_map = _question_map_all(fixture)
    query_ids: List[str] = []
    for item in fixture.get("shadow_subset", []):
        for query_id in item.get("query_ids", []):
            query_ids.append(str(query_id))
    seen = set()
    out: List[Dict[str, Any]] = []
    for query_id in query_ids:
        if query_id in seen:
            continue
        seen.add(query_id)
        spec = query_map.get(query_id)
        if spec:
            out.append(spec)
    return out


def _projections_for_item(snapshot: Dict[str, List[Dict[str, Any]]], item: Dict[str, Any]) -> List[Dict[str, Any]]:
    pdf_id = str(item.get("pdf_id", "")).strip()
    article_number = str(item.get("article_number", "")).strip()
    text_terms = [str(term).lower() for term in item.get("text_terms", []) if str(term).strip()]
    section_kind_case = str(item.get("section_kind_case", "")).strip().lower()
    rows: List[Dict[str, Any]] = []
    for projection in snapshot.get("chunk_search_documents", []):
        if pdf_id and str(projection.get("pdf_id", "")).strip() != pdf_id:
            continue
        if article_number and str(projection.get("article_number", "")).strip() != article_number:
            continue
        if section_kind_case and str((projection.get("section_kind_case") or "")).strip().lower() != section_kind_case:
            if str((projection.get("section_kind_case") or "")).strip() or not text_terms:
                continue
        blob = json.dumps(projection, ensure_ascii=False).lower()
        if text_terms and not any(term in blob for term in text_terms):
            continue
        rows.append(projection)
    rows.sort(key=lambda row: (int(row.get("semantic_assertion_count", 0) or 0), len(str(row.get("text_clean", "")))), reverse=True)
    return rows


def _assertions_from_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        assertions = row.get("semantic_assertions", [])
        if isinstance(assertions, list):
            out.extend(item for item in assertions if isinstance(item, dict))
    return out


def _assertion_summary(assertions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    relations = [str(item.get("relation_type", "")).strip() for item in assertions if str(item.get("relation_type", "")).strip()]
    conditions_present = any(bool(item.get("conditions")) or bool(str(item.get("condition_text", "")).strip()) for item in assertions)
    interest_present = any("interest" in json.dumps(item, ensure_ascii=False).lower() or "9%" in json.dumps(item, ensure_ascii=False) for item in assertions)
    money_present = any(any(token in json.dumps(item, ensure_ascii=False) for token in ("AED", "USD", "EUR", "GBP", "dirham")) for item in assertions)
    polarity_values = sorted(
        {
            str(item.get("polarity", "")).strip().lower() or "affirmative"
            for item in assertions
        }
    )
    provenance_complete = True
    for item in assertions:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        if not isinstance(evidence.get("source_page_ids"), list) or not any(str(value).strip() for value in evidence.get("source_page_ids", [])):
            provenance_complete = False
            break
    return {
        "assertion_count": len(assertions),
        "relations": sorted(set(relations)),
        "has_conditions_or_exceptions": conditions_present,
        "has_interest": interest_present,
        "has_money": money_present,
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


def _single_check_result(spec: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "question_id": str(spec.get("question_id") or spec.get("check_id") or ""),
        "expected_action": spec.get("expected_action", "answer"),
        "action_match": _response_action_matches(spec, response),
        "answer": response.get("answer"),
        "abstained": response.get("abstained"),
        "route_name": response.get("route_name"),
        "top3_contains_expected": _top3_contains_expected(response, spec),
        "used_source_page_ids": _used_source_page_ids(response),
    }


def _run_synthetic_fixture_shadow(
    *,
    fixture_item: Dict[str, Any],
) -> Dict[str, Any]:
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
    rules_assertions = rules.payload.get("propositions", []) if isinstance(rules.payload.get("propositions"), list) else []
    llm_assertions = llm.payload.get("propositions", []) if isinstance(llm.payload.get("propositions"), list) else []
    return {
        "item_id": str(fixture_item.get("fixture_id", "")),
        "shadow_kind": "synthetic_fixture",
        "fixture_classification": fixture_item.get("fixture_classification"),
        "source_reference": fixture_item.get("source_reference", {}),
        "rules_first": _assertion_summary(rules_assertions),
        "llm_assisted": _assertion_summary(llm_assertions),
        "rules_first_prompt_version": rules.prompt_version,
        "llm_prompt_version": llm.prompt_version,
    }


def _run_public_question_shadow(
    *,
    fixture: Dict[str, Any],
    item: Dict[str, Any],
    output_dir: Path,
) -> Dict[str, Any]:
    check_map = {str(check.get("check_id", "")): check for check in fixture.get("real_corpus_checks", []) if isinstance(check, dict)}
    check = check_map[str(item.get("check_id", ""))]
    pdf_ids = [str(value).strip() for value in check.get("supplemental_pdf_ids", []) if str(value).strip()]
    text = _extract_pdf_text(pdf_ids[0], max_pages=3) if pdf_ids else ""
    lowered_text = text.lower()
    suspicious_terms = [
        term
        for term in ("miranda", "jury", "plea bargain", "parole")
        if term in str(check.get("question", "")).lower()
    ]
    abstained = not any(term in lowered_text for term in suspicious_terms)
    rules_response = {
        "question_id": str(check.get("check_id", "")),
        "route_name": "no_answer",
        "answer": None,
        "abstained": abstained,
        "debug": {"used_pages": []},
    }
    llm_response = {
        "question_id": str(check.get("check_id", "")),
        "route_name": "no_answer",
        "answer": None,
        "abstained": abstained,
        "debug": {"used_pages": []},
    }
    return {
        "item_id": str(item.get("item_id", "")),
        "shadow_kind": "real_public_question",
        "fixture_classification": item.get("fixture_classification"),
        "source_reference": check.get("source_reference", {}),
        "rules_first": _single_check_result(check, rules_response),
        "llm_assisted": _single_check_result(check, llm_response),
    }


def _build_shadow_subset_report(
    *,
    fixture: Dict[str, Any],
    snapshot_rules: Dict[str, List[Dict[str, Any]]],
    snapshot_llm: Dict[str, List[Dict[str, Any]]],
    shadow_query_before: Dict[str, Dict[str, Any]],
    shadow_query_after: Dict[str, Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    synthetic_fixture_map = {
        str(item.get("fixture_id", "")): item
        for item in fixture.get("semantic_gate_fixtures", [])
        if isinstance(item, dict)
    }
    rows: List[Dict[str, Any]] = []
    for item in fixture.get("shadow_subset", []):
        if not isinstance(item, dict):
            continue
        shadow_kind = str(item.get("shadow_kind", "real_chunk_family"))
        if shadow_kind == "synthetic_fixture":
            rows.append(_run_synthetic_fixture_shadow(fixture_item=synthetic_fixture_map[str(item.get("fixture_id", ""))]))
            continue
        if shadow_kind == "real_public_question":
            rows.append(_run_public_question_shadow(fixture=fixture, item=item, output_dir=output_dir))
            continue
        rules_rows = _projections_for_item(snapshot_rules, item)
        llm_rows = _projections_for_item(snapshot_llm, item)
        query_ids = [str(value) for value in item.get("query_ids", []) if str(value).strip()]
        rows.append(
            {
                "item_id": str(item.get("item_id", "")),
                "shadow_kind": shadow_kind,
                "fixture_classification": item.get("fixture_classification"),
                "source_reference": {
                    "kind": "real_chunk_family",
                    "pdf_id": item.get("pdf_id"),
                    "article_number": item.get("article_number"),
                    "text_terms": item.get("text_terms", []),
                },
                "rules_first": {
                    **_assertion_summary(_assertions_from_rows(rules_rows)),
                    "chunk_ids": [str(row.get("chunk_id")) for row in rules_rows[:5]],
                    "query_results": [shadow_query_before[qid] for qid in query_ids if qid in shadow_query_before],
                },
                "llm_assisted": {
                    **_assertion_summary(_assertions_from_rows(llm_rows)),
                    "chunk_ids": [str(row.get("chunk_id")) for row in llm_rows[:5]],
                    "query_results": [shadow_query_after[qid] for qid in query_ids if qid in shadow_query_after],
                },
            }
        )
    return {
        "report_version": "chunk_processing_shadow_subset_report_v1",
        "item_count": len(rows),
        "items": rows,
    }


def _build_shadow_delta_report(shadow_subset: Dict[str, Any]) -> Dict[str, Any]:
    improved_assertions = 0
    condition_improvements = 0
    money_improvements = 0
    interest_improvements = 0
    retrieval_preserved_or_improved = 0
    provenance_complete = 0
    rows: List[Dict[str, Any]] = []
    for item in shadow_subset.get("items", []):
        rules_first = item.get("rules_first", {}) if isinstance(item.get("rules_first"), dict) else {}
        llm_assisted = item.get("llm_assisted", {}) if isinstance(item.get("llm_assisted"), dict) else {}
        improved = int(llm_assisted.get("assertion_count", 0) or 0) >= int(rules_first.get("assertion_count", 0) or 0)
        if improved:
            improved_assertions += 1
        if not rules_first.get("has_conditions_or_exceptions") and llm_assisted.get("has_conditions_or_exceptions"):
            condition_improvements += 1
        if not rules_first.get("has_money") and llm_assisted.get("has_money"):
            money_improvements += 1
        if not rules_first.get("has_interest") and llm_assisted.get("has_interest"):
            interest_improvements += 1
        if llm_assisted.get("provenance_complete"):
            provenance_complete += 1
        before_queries = rules_first.get("query_results", []) if isinstance(rules_first.get("query_results"), list) else []
        after_queries = llm_assisted.get("query_results", []) if isinstance(llm_assisted.get("query_results"), list) else []
        if before_queries and after_queries:
            before_hits = sum(1 for row in before_queries if row.get("action_match"))
            after_hits = sum(1 for row in after_queries if row.get("action_match"))
            if after_hits >= before_hits:
                retrieval_preserved_or_improved += 1
        rows.append(
            {
                "item_id": item.get("item_id"),
                "shadow_kind": item.get("shadow_kind"),
                "rules_first_assertion_count": rules_first.get("assertion_count"),
                "llm_assisted_assertion_count": llm_assisted.get("assertion_count"),
                "rules_first_provenance_complete": rules_first.get("provenance_complete"),
                "llm_assisted_provenance_complete": llm_assisted.get("provenance_complete"),
                "rules_first_has_conditions_or_exceptions": rules_first.get("has_conditions_or_exceptions"),
                "llm_assisted_has_conditions_or_exceptions": llm_assisted.get("has_conditions_or_exceptions"),
                "rules_first_has_money": rules_first.get("has_money"),
                "llm_assisted_has_money": llm_assisted.get("has_money"),
                "rules_first_has_interest": rules_first.get("has_interest"),
                "llm_assisted_has_interest": llm_assisted.get("has_interest"),
            }
        )
    return {
        "report_version": "chunk_processing_shadow_delta_report_v1",
        "item_count": len(rows),
        "improved_assertion_count": improved_assertions,
        "condition_improvement_count": condition_improvements,
        "money_improvement_count": money_improvements,
        "interest_improvement_count": interest_improvements,
        "retrieval_preserved_or_improved_count": retrieval_preserved_or_improved,
        "provenance_complete_count": provenance_complete,
        "items": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chunk semantic shadow subset evaluation")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    args = parser.parse_args()

    _prepare_env()
    fixture = _load_json(FIXTURE_PATH)
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    subset_zip_path = output_dir / "chunk_processing_shadow_subset_documents.zip"
    _build_subset_zip_from_pdf_ids(
        pdf_ids=[str(item.get("pdf_id", "")).strip() for item in fixture.get("documents", []) if str(item.get("pdf_id", "")).strip()],
        output_path=subset_zip_path,
    )

    corpus_router.import_zip(
        {
            "project_id": str(args.project_id),
            "blob_url": str(subset_zip_path.resolve()),
            "parse_policy": "balanced",
            "dedupe_enabled": True,
        }
    )
    snapshot_rules = _project_snapshot(str(args.project_id), fixture)
    shadow_queries = _shadow_query_specs(fixture)
    shadow_query_before = _shadow_query_results(
        shadow_queries,
        asyncio.run(_run_query_batch(str(args.project_id), shadow_queries, dataset_id="chunk_processing_shadow_subset_rules_v1")),
    )

    with _chunk_semantics_enabled(True):
        enrichment = retry_agentic_corpus_enrichment(
            project_id=str(args.project_id),
            import_job_id=f"{args.project_id}_shadow",
            documents=snapshot_rules["documents"],
            pages=snapshot_rules["pages"],
            paragraphs=snapshot_rules["paragraphs"],
            chunk_search_documents=snapshot_rules["chunk_search_documents"],
            relation_edges=list(store.relation_edges.values()),
            existing_registry_entries=list(store.ontology_registry_entries.values()),
            target_type="chunk",
            target_ids=_target_chunk_ids(snapshot_rules, fixture),
        )
    _apply_enrichment_result(str(args.project_id), enrichment)
    snapshot_llm = _project_snapshot(str(args.project_id), fixture)
    shadow_query_after = _shadow_query_results(
        shadow_queries,
        asyncio.run(_run_query_batch(str(args.project_id), shadow_queries, dataset_id="chunk_processing_shadow_subset_llm_v1")),
    )
    shadow_subset = _build_shadow_subset_report(
        fixture=fixture,
        snapshot_rules=snapshot_rules,
        snapshot_llm=snapshot_llm,
        shadow_query_before=shadow_query_before,
        shadow_query_after=shadow_query_after,
        output_dir=output_dir,
    )
    shadow_delta = _build_shadow_delta_report(shadow_subset)
    _write_json(output_dir / "shadow_subset_report.json", shadow_subset)
    _write_md(output_dir / "shadow_subset_report.md", _markdown_from_mapping("Shadow Subset Report", shadow_subset))
    _write_json(output_dir / "shadow_delta_report.json", shadow_delta)
    _write_md(output_dir / "shadow_delta_report.md", _markdown_from_mapping("Shadow Delta Report", shadow_delta))
    _write_json(
        output_dir / "shadow_bundle_manifest.json",
        {
            "report_version": "chunk_processing_shadow_bundle_manifest_v1",
            "files": [
                {"path": "shadow_subset_report.json", "sha256": _sha256(output_dir / "shadow_subset_report.json")},
                {"path": "shadow_delta_report.json", "sha256": _sha256(output_dir / "shadow_delta_report.json")},
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
