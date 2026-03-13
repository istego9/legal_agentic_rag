#!/usr/bin/env python3
"""Select a stratified 25-question pilot gold subset from Public100 baseline artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Tuple

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api.artifacts import artifact_path  # noqa: E402
from packages.router.heuristics import choose_route_decision  # noqa: E402


DEFAULT_BASELINE_ROOT = artifact_path("competition_runs") / "public100_baseline"
DEFAULT_QUESTIONS_PATH = ROOT / "datasets" / "official_fetch_2026-03-11" / "questions.json"
DEFAULT_OUTPUT_PATH = ROOT / "datasets" / "gold" / "pilot_gold_questions_v1.jsonl"
DEFAULT_REPORT_PATH = ROOT / "reports" / "gold" / "pilot_gold_selection_report.md"
SELECTION_VERSION = "pilot_gold_questions_v1"
TARGET_COUNTS = {
    "law_article_lookup": 8,
    "law_relation_or_history": 5,
    "cross_law_compare": 5,
    "case_family": 3,
    "negative_or_unanswerable": 4,
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        payload = json.loads(raw)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dict(row), ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _load_questions(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"questions payload must be a list: {path}")
    out: Dict[str, Dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        qid = str(row.get("id", "")).strip()
        if qid:
            out[qid] = row
    return out


def _selection_theme(question: str, answer_type: str) -> str:
    lower = question.lower()
    if any(token in lower for token in ("official law number", "title page", "cover page")):
        return "title_identity"
    if any(token in lower for token in ("effective date", "enacted", "published", "amended", "consolidated version")):
        return "history_or_version"
    if any(token in lower for token in ("administers", "responsible for administering", "who administers", "who made")):
        return "authority_or_administration"
    if any(token in lower for token in ("how many", "months", "days", "years", "business days", "hours")):
        return "numeric_requirement"
    if any(token in lower for token in ("void", "valid", "permitted", "can ", "does ")) and answer_type == "boolean":
        return "boolean_norm"
    if any(token in lower for token in ("who is", "who are", "claimant", "defendant", "judge", "party")):
        return "identity_lookup"
    if any(token in lower for token in ("earlier", "higher", "common", "both cases", "both")):
        return "compare_dimension"
    if any(token in lower for token in ("miranda", "jury", "plea bargain", "parole")):
        return "adversarial_no_answer"
    return answer_type or "general"


def _selection_reason(route_family: str, theme: str, risk_tier: str, *, substitute: bool = False) -> str:
    base = {
        "law_article_lookup": "Selected to cover high-risk single-document law/article retrieval and direct provision lookup.",
        "law_relation_or_history": "Selected to cover law amendment, enactment, publication, or effective-date history questions.",
        "cross_law_compare": "Selected to cover cross-law comparison behavior across multiple legal instruments.",
        "law_scope_or_definition": "Selected as a law-side substitute to preserve scope/definition/title-page coverage where target families are underrepresented.",
        "case_family": "Selected to cover case identity, outcome/value, and case-cross-compare review patterns.",
        "negative_or_unanswerable": "Selected to preserve adversarial/no-answer guardrail coverage.",
    }.get(route_family, "Selected as a representative pilot gold item.")
    detail = f" Theme: {theme}."
    risk = f" Risk tier: {risk_tier}."
    if substitute:
        return base + " This row fills an unavoidable route-composition gap." + detail + risk
    return base + detail + risk


def _current_route_profile(question_row: Mapping[str, Any]) -> Dict[str, Any]:
    decision = choose_route_decision(question_row)
    return {
        "raw_route": decision.raw_route,
        "normalized_taxonomy_route": decision.normalized_taxonomy_route,
        "document_scope_guess": decision.document_scope_guess,
        "target_doc_types_guess": list(decision.target_doc_types_guess or []),
    }


def _selection_family(question_row: Mapping[str, Any], triage_row: Mapping[str, Any]) -> str:
    question = str(question_row.get("question", ""))
    lower = question.lower()
    answer_type = str(question_row.get("answer_type", "")).strip()
    profile = triage_row.get("question_profile", {}) if isinstance(triage_row.get("question_profile"), Mapping) else {}
    normalized = str(profile.get("normalized_taxonomy_route", "") or "").strip()
    target_doc_types = set(profile.get("target_doc_types_guess", []) or [])

    if normalized == "negative_or_unanswerable":
        return "negative_or_unanswerable"
    if normalized == "cross_law_compare":
        return "cross_law_compare"
    if normalized in {"case_entity_lookup", "case_outcome_or_value", "case_cross_compare"}:
        return "case_family"
    if "case" in target_doc_types and normalized == "law_article_lookup":
        return "case_family"

    if re.search(r"article\s+\d+[^\n\r?]*\band article\s+\d+", lower) or re.search(
        r"between [^?]*law[^?]* and [^?]*law", lower
    ):
        return "cross_law_compare"
    if any(token in lower for token in ("which specific difc laws were amended", "effective date", "enacted", "published", "consolidated version")):
        return "law_relation_or_history"
    if normalized == "law_relation_or_history":
        return "law_relation_or_history"
    if normalized == "law_scope_or_definition":
        return "law_scope_or_definition"
    return "law_article_lookup"


def _risk_tier(triage_row: Mapping[str, Any], route_family: str, question: str) -> str:
    if route_family == "negative_or_unanswerable":
        return "high"
    severity_label = str(triage_row.get("severity_label", "")).strip()
    if severity_label in {"critical", "high"}:
        return "high"
    if any(token in question.lower() for token in ("effective date", "amended", "common party", "earlier", "higher", "void", "valid")):
        return "high"
    return "medium"


def _sort_key(item: Mapping[str, Any]) -> Tuple[int, int, str]:
    return (
        -int(item.get("severity_score", 0)),
        0 if str(item.get("answer_type", "")) in {"number", "boolean", "name", "date"} else 1,
        str(item.get("question_id", "")),
    )


def _select_diverse(pool: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if count <= 0:
        return []
    ordered = sorted(pool, key=_sort_key)
    selected: List[Dict[str, Any]] = []
    used_themes: set[str] = set()
    for row in ordered:
        theme = str(row.get("selection_theme", ""))
        if theme and theme not in used_themes:
            selected.append(row)
            used_themes.add(theme)
        if len(selected) >= count:
            return selected
    for row in ordered:
        if row in selected:
            continue
        selected.append(row)
        if len(selected) >= count:
            break
    return selected


def build_selection(
    *,
    questions_by_id: Mapping[str, Dict[str, Any]],
    triage_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    enriched_rows: List[Dict[str, Any]] = []
    for triage_row in triage_rows:
        question_id = str(triage_row.get("question_id", "")).strip()
        question_row = dict(questions_by_id.get(question_id, {}))
        if not question_row:
            continue
        route_family = _selection_family(question_row, triage_row)
        question = str(question_row.get("question", "")).strip()
        answer_type = str(question_row.get("answer_type", "")).strip()
        theme = _selection_theme(question, answer_type)
        risk_tier = _risk_tier(triage_row, route_family, question)
        enriched_rows.append(
            {
                **triage_row,
                "question": question,
                "answer_type": answer_type,
                "route_family": route_family,
                "selection_theme": theme,
                "risk_tier": risk_tier,
            }
        )

    pools: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in enriched_rows:
        pools[str(row["route_family"])].append(row)

    selected: List[Dict[str, Any]] = []
    composition: Counter[str] = Counter()
    deviations: List[str] = []

    for route_family in ("law_article_lookup", "law_relation_or_history", "cross_law_compare", "negative_or_unanswerable"):
        target = TARGET_COUNTS[route_family]
        pool = pools.get(route_family, [])
        picked = _select_diverse(pool, min(target, len(pool)))
        selected.extend(picked)
        composition[route_family] += len(picked)
        if len(picked) < target:
            deviations.append(
                f"{route_family}: selected {len(picked)} of target {target} because only {len(pool)} current candidates matched this family."
            )

    case_pool = sorted(pools.get("case_family", []), key=_sort_key)
    case_by_raw_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in case_pool:
        raw = str((row.get("question_profile", {}) or {}).get("normalized_taxonomy_route", "")).strip()
        case_by_raw_route[raw].append(row)
    case_selected: List[Dict[str, Any]] = []
    for route_name in ("case_entity_lookup", "case_outcome_or_value", "case_cross_compare"):
        if case_by_raw_route.get(route_name):
            case_selected.append(case_by_raw_route[route_name][0])
    for row in case_pool:
        if len(case_selected) >= TARGET_COUNTS["case_family"]:
            break
        if row not in case_selected:
            case_selected.append(row)
    selected.extend(case_selected[: TARGET_COUNTS["case_family"]])
    composition["case_family"] += len(case_selected[: TARGET_COUNTS["case_family"]])
    if len(case_selected) < TARGET_COUNTS["case_family"]:
        deviations.append(
            f"case_family: selected {len(case_selected)} of target {TARGET_COUNTS['case_family']} because the current baseline exposed fewer case-family candidates."
        )

    selected_ids = {str(row["question_id"]) for row in selected}
    deficit = 25 - len(selected)
    if deficit > 0:
        substitute_pool = [
            row
            for row in pools.get("law_scope_or_definition", [])
            if str(row["question_id"]) not in selected_ids
        ]
        substitutes = _select_diverse(substitute_pool, deficit)
        for row in substitutes:
            row["selection_reason_substitute"] = True
        selected.extend(substitutes)
        composition["law_scope_or_definition"] += len(substitutes)
        if len(substitutes) < deficit:
            deviations.append(
                f"law_scope_or_definition substitution: filled only {len(substitutes)} of {deficit} missing slots."
            )
        elif deficit > 0:
            deviations.append(
                f"law_scope_or_definition substitution: filled {len(substitutes)} missing slots because current baseline exposes too few law_relation_or_history/cross_law_compare candidates."
            )

    # Final deterministic order by planned family, then severity.
    family_order = {
        "law_article_lookup": 0,
        "law_relation_or_history": 1,
        "cross_law_compare": 2,
        "law_scope_or_definition": 3,
        "case_family": 4,
        "negative_or_unanswerable": 5,
    }
    selected = sorted(
        {str(row["question_id"]): row for row in selected}.values(),
        key=lambda row: (
            family_order.get(str(row.get("route_family", "")), 99),
            _sort_key(row),
        ),
    )

    if len(selected) != 25:
        raise RuntimeError(f"expected 25 selected questions, got {len(selected)}")

    output_rows: List[Dict[str, Any]] = []
    for row in selected:
        question_id = str(row["question_id"])
        question = str(row["question"])
        answer_type = str(row["answer_type"])
        route_family = str(row["route_family"])
        risk_tier = str(row["risk_tier"])
        reason = _selection_reason(
            route_family,
            str(row.get("selection_theme", "")),
            risk_tier,
            substitute=bool(row.get("selection_reason_substitute", False)),
        )
        output_rows.append(
            {
                "question_id": question_id,
                "question": question,
                "answer_type": answer_type,
                "route_family": route_family,
                "selection_reason": reason,
                "risk_tier": risk_tier,
            }
        )

    metadata = {
        "selection_version": SELECTION_VERSION,
        "composition": dict(composition),
        "deviations": deviations,
        "high_risk_count": sum(1 for row in output_rows if row["risk_tier"] == "high"),
        "selected_question_ids": [row["question_id"] for row in output_rows],
    }
    return output_rows, metadata


def render_report(
    rows: List[Dict[str, Any]],
    metadata: Mapping[str, Any],
    *,
    artifact_root: Path,
    questions_path: Path,
) -> str:
    composition = Counter(row["route_family"] for row in rows)
    high_risk_rows = [row for row in rows if row["risk_tier"] == "high"]
    lines = [
        "# Pilot Gold Subset Selection Report",
        "",
        f"- selection_version: `{metadata.get('selection_version', SELECTION_VERSION)}`",
        f"- source_questions: `{questions_path}`",
        f"- source_triage_queue: `{artifact_root / 'triage_queue.jsonl'}`",
        "",
        "## Final Route Composition",
        "",
    ]
    for key in (
        "law_article_lookup",
        "law_relation_or_history",
        "cross_law_compare",
        "law_scope_or_definition",
        "case_family",
        "negative_or_unanswerable",
    ):
        lines.append(f"- `{key}`: `{composition.get(key, 0)}`")
    lines.extend(["", "## Highest-Risk Selected Questions", ""])
    for row in high_risk_rows[:12]:
        lines.append(f"- `{row['question_id']}` `{row['route_family']}` `{row['answer_type']}` - {row['question']}")
    deviations = list(metadata.get("deviations", []) or [])
    lines.extend(["", "## Unavoidable Imbalances", ""])
    if deviations:
        for item in deviations:
            lines.append(f"- {item}")
    else:
        lines.append("- `none`")
    lines.extend(["", "## Selection Table", ""])
    for row in rows:
        lines.append(
            f"- `{row['question_id']}` `{row['route_family']}` `{row['answer_type']}` `{row['risk_tier']}`"
        )
        lines.append(f"  reason: {row['selection_reason']}")
        lines.append(f"  question: {row['question']}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select the committed 25-question pilot gold subset")
    parser.add_argument("--artifact-root", default=str(DEFAULT_BASELINE_ROOT))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact_root = Path(args.artifact_root).resolve()
    questions_path = Path(args.questions).resolve()
    questions_by_id = _load_questions(questions_path)
    triage_rows = _read_jsonl(artifact_root / "triage_queue.jsonl")
    selected_rows, metadata = build_selection(questions_by_id=questions_by_id, triage_rows=triage_rows)

    output_path = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    _write_jsonl(output_path, selected_rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(selected_rows, metadata, artifact_root=artifact_root, questions_path=questions_path),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "completed",
                "output_path": str(output_path),
                "report_path": str(report_path),
                "selected_count": len(selected_rows),
                "composition": metadata["composition"],
                "high_risk_count": metadata["high_risk_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
