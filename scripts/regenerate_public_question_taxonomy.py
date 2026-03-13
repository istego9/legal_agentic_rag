#!/usr/bin/env python3
"""Regenerate the public question taxonomy from the canonical official questions dataset."""

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

from packages.contracts.public_question_taxonomy import DEFAULT_TAXONOMY_PATH  # noqa: E402
from packages.router.heuristics import choose_route_decision  # noqa: E402


DEFAULT_QUESTIONS_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "questions.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _target_doc_types(route: str, guessed: List[str]) -> List[str]:
    if guessed:
        seen = set()
        out: List[str] = []
        for item in guessed:
            token = str(item).strip()
            if token and token not in seen:
                seen.add(token)
                out.append(token)
        if out:
            return out
    if route.startswith("case_"):
        return ["case"]
    if route == "cross_law_compare":
        return ["law", "regulation", "enactment_notice"]
    if route == "negative_or_unanswerable":
        return ["case", "law", "regulation", "enactment_notice"]
    return ["law"]


def _evidence_topology(question: str, route: str, document_scope: str, answer_type: str) -> str:
    lower = question.lower()
    if document_scope == "cross_doc":
        if "commencement" in lower or "enactment notice" in lower:
            return "notice_mediated"
        return "multi_doc"
    if any(token in lower for token in ("title page", "cover page", "header", "caption", "first page", "last page", "page 2")):
        return "single_page"
    if route in {"law_relation_or_history"} and any(token in lower for token in ("commencement", "effective date", "enactment notice")):
        return "notice_mediated"
    if answer_type in {"name", "number", "date", "boolean"} and route in {"law_article_lookup", "law_scope_or_definition", "case_entity_lookup"}:
        return "single_page"
    return "multi_page"


def _answerability_risk(route: str, document_scope: str, answer_type: str) -> str:
    if route == "negative_or_unanswerable":
        return "high"
    if document_scope == "cross_doc":
        return "high"
    if route == "law_relation_or_history":
        return "high"
    if answer_type == "free_text":
        return "medium"
    return "low"


def _route_notes(route: str) -> str:
    return {
        "case_entity_lookup": "Single-case entity extraction covering parties, judges, or case identity fields.",
        "case_outcome_or_value": "Single-case outcome, order, or value extraction from case materials.",
        "case_cross_compare": "Cross-case compare question over case identity, dates, values, or shared parties.",
        "law_article_lookup": "Single-instrument law or regulation article/provision lookup.",
        "law_relation_or_history": "Law amendment, enactment, commencement, or version-history question.",
        "law_scope_or_definition": "Law scope, title-page identity, administration, or definition question.",
        "cross_law_compare": "Cross-law compare question spanning multiple legal instruments.",
        "negative_or_unanswerable": "Adversarial or unsupported question expected to remain unanswerable.",
    }.get(route, "Public question taxonomy row.")


def build_rows(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for question in questions:
        decision = choose_route_decision(question)
        route = str(decision.normalized_taxonomy_route or "").strip()
        document_scope = str(decision.document_scope_guess or ("cross_doc" if "compare" in route else "single_doc"))
        answer_type = str(question.get("answer_type") or "").strip()
        rows.append(
            {
                "question_id": str(question["id"]),
                "question": str(question["question"]),
                "answer_type_expected": answer_type,
                "primary_route": route,
                "document_scope": document_scope,
                "target_doc_types": _target_doc_types(route, list(decision.target_doc_types_guess or [])),
                "evidence_topology": _evidence_topology(str(question["question"]), route, document_scope, answer_type),
                "temporal_sensitivity": str(decision.temporal_sensitivity_guess or "none"),
                "answerability_risk": _answerability_risk(route, document_scope, answer_type),
                "notes": _route_notes(route),
            }
        )
    return rows


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate public question taxonomy from official questions dataset")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--output", default=str(DEFAULT_TAXONOMY_PATH))
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    questions_path = Path(args.questions).resolve()
    output_path = Path(args.output).resolve()
    payload = _read_json(questions_path)
    if not isinstance(payload, list):
        raise SystemExit("questions dataset must be a JSON array")
    rows = build_rows(payload)
    _write_jsonl(output_path, rows)
    print(
        json.dumps(
            {
                "status": "completed",
                "questions_path": str(questions_path),
                "output_path": str(output_path),
                "row_count": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
