#!/usr/bin/env python3
"""Prepare baseline artifacts for the first meaningful QA compare slice."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.runtime.solvers import normalize_answer  # noqa: E402


SLICE_ARTIFACT_VERSION = "first_meaningful_qa_slice.v1"
RESULT_FORMAT_VERSION = "qa_baseline_compare_results.v1"
RESULT_SCHEMA_VERSION = "qa_baseline_compare_results.schema.v1"
PROMPT_PACK_VERSION = "qa_baseline_prompt_pack.v1"
NAIVE_CONTEXT_STRATEGY_VERSION = "naive_context_search_default.v1"
SLICE_ID = "first-meaningful-qa-2026-03-08"
PUBLIC_DATASET_PATH = ROOT / "public_dataset.json"
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "exec-plans" / "active" / "artifacts" / "first_meaningful_qa"

BASELINES: Dict[str, Dict[str, str]] = {
    "B0": {
        "baseline_name": "gpt54-question-only",
        "source_strategy": "none",
        "prompt_label": "question_only",
    },
    "B1": {
        "baseline_name": "gpt54-naive-context",
        "source_strategy": "naive_context",
        "prompt_label": "naive_context",
    },
    "B2": {
        "baseline_name": "current-runtime-baseline",
        "source_strategy": "runtime_reference",
        "prompt_label": "runtime_reference",
    },
}

PUBLIC_SLICE_SPEC: List[Dict[str, str]] = [
    {
        "id": "bd8d0befc731315ee2a477221feb950b44e68d9596823a90c47f78fc04870870",
        "answer_type": "boolean",
        "inferred_route": "article_lookup",
    },
    {
        "id": "96bccc8b15e2795578584484ea3533e71d6e044d13420cf77a32393b7502fc1c",
        "answer_type": "boolean",
        "inferred_route": "article_lookup",
    },
    {
        "id": "dd97e6cdec41ef77576ed86e037565fc88ff891edcdd39018e2d062e28f9605f",
        "answer_type": "date",
        "inferred_route": "history_lineage",
    },
    {
        "id": "7700103c51940db23ba51a0efefbef679201af5b0a60935853d10bf81a260466",
        "answer_type": "number",
        "inferred_route": "history_lineage",
    },
    {
        "id": "d204a13070fd2f18eb3e9e939fdc80855a915dfafd7f49f8fc8e80d6a3d7637b",
        "answer_type": "number",
        "inferred_route": "single_case_extraction",
    },
    {
        "id": "b9dc2dae206c155bc5936c971272e8154d22b4f9e3fa65795eb8b49a80d26b6f",
        "answer_type": "name",
        "inferred_route": "single_case_extraction",
    },
    {
        "id": "cdddeb6a063f29cbea5f10b3dccbd83aa16849e1f3124e223d141d1578efeb0a",
        "answer_type": "names",
        "inferred_route": "single_case_extraction",
    },
    {
        "id": "d64868661e961ce09219969e101edd52b26c8f70a2f6325209f34372e95baf44",
        "answer_type": "names",
        "inferred_route": "single_case_extraction",
    },
    {
        "id": "6618184ee84fbebc360162dc3825868eec4e5e81aae1901eb18a8e741fd323f3",
        "answer_type": "free_text",
        "inferred_route": "single_case_extraction",
    },
    {
        "id": "c595f1180b440f4e6ea5e130563fb4c2e9705557d3abf10e401948c0eb73b268",
        "answer_type": "free_text",
        "inferred_route": "history_lineage",
    },
    {
        "id": "fcabd6aa14e2df4b7ca00fa516a70eba6de58b74dfde30270e3fe3eec6d1da7a",
        "answer_type": "free_text",
        "inferred_route": "history_lineage",
    },
    {
        "id": "fb1de34d3ebe58b03c5e9898c2e29d1d8c6297fa570f0021967986e43b62da62",
        "answer_type": "free_text",
        "inferred_route": "article_lookup",
    },
]

MANUAL_NO_ANSWER_SPEC: List[Dict[str, str]] = [
    {
        "id": "manual-no-answer-001",
        "answer_type": "boolean",
        "purpose": "out-of-corpus false positive suppression",
        "question": "Did the DIFC Criminal Procedure Code authorize arrests without warrant in 2025 outside the DIFC courts?",
    },
    {
        "id": "manual-no-answer-002",
        "answer_type": "number",
        "purpose": "unsupported numeric extraction",
        "question": "What was the total fine amount imposed in case CFI 999/2030?",
    },
    {
        "id": "manual-no-answer-003",
        "answer_type": "date",
        "purpose": "nonexistent enactment event",
        "question": "On what date was the DIFC Space Mining Law enacted?",
    },
    {
        "id": "manual-no-answer-004",
        "answer_type": "name",
        "purpose": "ambiguous/nonexistent entity resolution",
        "question": "Which judge authored the decision in case ARB 999/2031?",
    },
    {
        "id": "manual-no-answer-005",
        "answer_type": "names",
        "purpose": "unsupported party list",
        "question": "List all respondents in case SCT 999/2032.",
    },
    {
        "id": "manual-no-answer-006",
        "answer_type": "free_text",
        "purpose": "abstain on fabricated legal topic",
        "question": "Summarize the DIFC regulation on offshore asteroid mining concessions.",
    },
]

RESULT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "QABaselineCompareResults",
    "description": "Unified per-item compare artifact for B0/B1/B2 on the fixed QA slice.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "artifact_version": {"type": "string"},
        "slice_id": {"type": "string"},
        "baseline_id": {"type": "string", "enum": ["B0", "B1", "B2"]},
        "baseline_name": {"type": "string"},
        "item_count": {"type": "integer", "minimum": 0},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "baseline_id": {"type": "string", "enum": ["B0", "B1", "B2"]},
                    "answer": {
                        "type": ["string", "number", "boolean", "null", "array"],
                    },
                    "answer_normalized": {"type": ["string", "null"]},
                    "abstained": {"type": "boolean"},
                    "sources_summary": {"type": "string"},
                    "short_failure_note": {"type": "string"},
                },
                "required": [
                    "id",
                    "baseline_id",
                    "answer",
                    "answer_normalized",
                    "abstained",
                    "sources_summary",
                    "short_failure_note",
                ],
            },
        },
    },
    "required": [
        "artifact_version",
        "slice_id",
        "baseline_id",
        "baseline_name",
        "item_count",
        "items",
    ],
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_preserve(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        label = _as_text(value)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_public_question_map(path: Path = PUBLIC_DATASET_PATH) -> Dict[str, Dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise ValueError("public dataset must be a JSON list")
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        question_id = _as_text(item.get("id"))
        if question_id:
            mapping[question_id] = dict(item)
    return mapping


def build_fixed_slice_artifact(
    public_question_map: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for spec in PUBLIC_SLICE_SPEC:
        question_id = spec["id"]
        payload = public_question_map.get(question_id)
        if not payload:
            raise ValueError(f"public slice question not found: {question_id}")
        answer_type = _as_text(payload.get("answer_type"))
        if answer_type != spec["answer_type"]:
            raise ValueError(
                f"answer_type mismatch for {question_id}: expected {spec['answer_type']}, got {answer_type}"
            )
        question = _as_text(payload.get("question"))
        if not question:
            raise ValueError(f"question text missing for {question_id}")
        items.append(
            {
                "id": question_id,
                "source_kind": "public_dataset",
                "question": question,
                "answer_type": answer_type,
                "inferred_route": spec["inferred_route"],
                "expected_behavior": "answer_from_corpus",
            }
        )

    for spec in MANUAL_NO_ANSWER_SPEC:
        items.append(
            {
                "id": spec["id"],
                "source_kind": "manual_no_answer",
                "question": spec["question"],
                "answer_type": spec["answer_type"],
                "inferred_route": "manual_adversarial",
                "expected_behavior": "abstain_or_explicit_no_answer",
                "purpose": spec["purpose"],
            }
        )

    return {
        "artifact_version": SLICE_ARTIFACT_VERSION,
        "slice_id": SLICE_ID,
        "source_docs": [
            "docs/exec-plans/active/first-meaningful-qa-baselines-2026-03-08.md",
            "docs/exec-plans/active/first-qa-slice-2026-03-08.md",
        ],
        "public_item_count": len(PUBLIC_SLICE_SPEC),
        "manual_no_answer_count": len(MANUAL_NO_ANSWER_SPEC),
        "item_count": len(items),
        "items": items,
    }


def build_dataset_import_payload(slice_artifact: Mapping[str, Any]) -> Dict[str, Any]:
    items = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        items.append(
            {
                "id": _as_text(item.get("id")),
                "question": _as_text(item.get("question")),
                "answer_type": _as_text(item.get("answer_type")),
            }
        )
    return {
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "source": "fixed_qa_slice",
        "questions": items,
    }


def _answer_shape_hint(answer_type: str) -> str:
    hints = {
        "boolean": "Return `true`, `false`, or `null` if abstaining.",
        "number": "Return a JSON number, or `null` if abstaining.",
        "date": "Return a JSON string in `YYYY-MM-DD` form, or `null` if abstaining.",
        "name": "Return one JSON string, or `null` if abstaining.",
        "names": "Return a JSON array of strings, or an empty array / `null` if abstaining.",
        "free_text": "Return one short JSON string, or `null` if abstaining.",
    }
    return hints.get(answer_type, "Return JSON only.")


def _baseline_system_prompt(baseline_id: str) -> str:
    if baseline_id == "B0":
        return (
            "You are executing Legal RAG baseline B0 (gpt54-question-only). "
            "Use no external context, citations, or tools. "
            "If you are not confident, abstain instead of fabricating. "
            "Return strict JSON only."
        )
    if baseline_id == "B1":
        return (
            "You are executing Legal RAG baseline B1 (gpt54-naive-context). "
            "Use only the provided raw context snippets. "
            "Do not rely on outside knowledge. "
            "If the snippets are insufficient, abstain. "
            "Return strict JSON only."
        )
    raise ValueError(f"unsupported baseline for prompt pack: {baseline_id}")


def _response_contract() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["answer", "abstained", "sources_summary", "short_failure_note"],
        "properties": {
            "answer": {"type": ["string", "number", "boolean", "null", "array"]},
            "abstained": {"type": "boolean"},
            "sources_summary": {"type": "string"},
            "short_failure_note": {"type": "string"},
        },
    }


def _format_user_prompt(
    *,
    item: Mapping[str, Any],
    baseline_id: str,
    sources_summary_token: str,
    context_text: str = "",
) -> str:
    lines = [
        f"Baseline ID: {baseline_id}",
        f"Item ID: {_as_text(item.get('id'))}",
        f"Answer type: {_as_text(item.get('answer_type'))}",
        _answer_shape_hint(_as_text(item.get("answer_type"))),
        f"Question: {_as_text(item.get('question'))}",
        (
            "Return JSON with exactly these keys: "
            "`answer`, `abstained`, `sources_summary`, `short_failure_note`."
        ),
        f"`sources_summary` must be exactly `{sources_summary_token}`.",
        "`short_failure_note` should be an empty string unless there is a specific issue to flag.",
    ]
    if baseline_id == "B1":
        lines.extend(
            [
                "Use only the context below.",
                "Context:",
                context_text or "(no context snippets retrieved)",
            ]
        )
    return "\n".join(lines)


def _naive_context_sources_summary(search_items: Iterable[Mapping[str, Any]]) -> str:
    page_ids = _dedupe_preserve(_as_text(item.get("source_page_id")) for item in search_items)
    if not page_ids:
        return "naive_context:none"
    return f"naive_context:{', '.join(page_ids)}"


def _build_context_text(search_items: Iterable[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for index, item in enumerate(search_items, start=1):
        source_page_id = _as_text(item.get("source_page_id")) or "unknown_0"
        snippet = _as_text(item.get("snippet"))
        score = item.get("score")
        lines.append(f"[{index}] source_page_id={source_page_id} score={score} snippet={snippet}")
    return "\n".join(lines)


def build_b0_request_pack(slice_artifact: Mapping[str, Any]) -> Dict[str, Any]:
    items = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        sources_summary_token = "none"
        items.append(
            {
                "id": _as_text(item.get("id")),
                "baseline_id": "B0",
                "baseline_name": BASELINES["B0"]["baseline_name"],
                "source_strategy": BASELINES["B0"]["source_strategy"],
                "answer_type": _as_text(item.get("answer_type")),
                "system_prompt": _baseline_system_prompt("B0"),
                "user_prompt": _format_user_prompt(
                    item=item,
                    baseline_id="B0",
                    sources_summary_token=sources_summary_token,
                ),
                "sources_summary_token": sources_summary_token,
                "response_contract": _response_contract(),
            }
        )
    return {
        "artifact_version": PROMPT_PACK_VERSION,
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "baseline_id": "B0",
        "baseline_name": BASELINES["B0"]["baseline_name"],
        "item_count": len(items),
        "items": items,
    }


def _request_json(
    base_url: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    method: str = "POST",
) -> Dict[str, Any]:
    body = None
    if payload is not None and method.upper() in {"POST", "PUT", "PATCH"}:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=f"{base_url.rstrip('/')}{path}",
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        data=body,
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"request failed: {exc.code} {raw}") from exc
    except Exception as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def _search_naive_context(
    *,
    base_url: str,
    project_id: str,
    question: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    payload = {
        "project_id": project_id,
        "query": question,
        "search_profile": "default",
        "top_k": top_k,
    }
    response = _request_json(base_url, "/v1/corpus/search", payload, method="POST")
    items = response.get("items")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            out.append(dict(item))
    return out


def build_b1_request_pack(
    slice_artifact: Mapping[str, Any],
    *,
    base_url: str,
    project_id: str,
    top_k: int,
) -> Dict[str, Any]:
    items = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        search_items = _search_naive_context(
            base_url=base_url,
            project_id=project_id,
            question=_as_text(item.get("question")),
            top_k=top_k,
        )
        sources_summary_token = _naive_context_sources_summary(search_items)
        context_text = _build_context_text(search_items)
        items.append(
            {
                "id": _as_text(item.get("id")),
                "baseline_id": "B1",
                "baseline_name": BASELINES["B1"]["baseline_name"],
                "source_strategy": BASELINES["B1"]["source_strategy"],
                "answer_type": _as_text(item.get("answer_type")),
                "naive_context": {
                    "strategy_version": NAIVE_CONTEXT_STRATEGY_VERSION,
                    "project_id": project_id,
                    "top_k": top_k,
                    "search_profile": "default",
                    "items": search_items,
                    "text": context_text,
                },
                "system_prompt": _baseline_system_prompt("B1"),
                "user_prompt": _format_user_prompt(
                    item=item,
                    baseline_id="B1",
                    sources_summary_token=sources_summary_token,
                    context_text=context_text,
                ),
                "sources_summary_token": sources_summary_token,
                "response_contract": _response_contract(),
            }
        )
    return {
        "artifact_version": PROMPT_PACK_VERSION,
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "baseline_id": "B1",
        "baseline_name": BASELINES["B1"]["baseline_name"],
        "item_count": len(items),
        "items": items,
    }


def build_b1_request_pack_template(slice_artifact: Mapping[str, Any], *, top_k: int) -> Dict[str, Any]:
    items = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        sources_summary_token = "naive_context:pending"
        items.append(
            {
                "id": _as_text(item.get("id")),
                "baseline_id": "B1",
                "baseline_name": BASELINES["B1"]["baseline_name"],
                "source_strategy": BASELINES["B1"]["source_strategy"],
                "answer_type": _as_text(item.get("answer_type")),
                "naive_context": {
                    "strategy_version": NAIVE_CONTEXT_STRATEGY_VERSION,
                    "project_id": "",
                    "top_k": top_k,
                    "search_profile": "default",
                    "items": [],
                    "text": "",
                    "status": "build_with_live_api",
                },
                "system_prompt": _baseline_system_prompt("B1"),
                "user_prompt": _format_user_prompt(
                    item=item,
                    baseline_id="B1",
                    sources_summary_token=sources_summary_token,
                    context_text="(populate with `build-b1-request-pack` against a live API + corpus)",
                ),
                "sources_summary_token": sources_summary_token,
                "response_contract": _response_contract(),
            }
        )
    return {
        "artifact_version": PROMPT_PACK_VERSION,
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "baseline_id": "B1",
        "baseline_name": BASELINES["B1"]["baseline_name"],
        "item_count": len(items),
        "items": items,
    }


def _coerce_model_answer(answer: Any, answer_type: str) -> Any:
    if answer is None:
        return None
    if answer_type == "boolean":
        if isinstance(answer, bool):
            return answer
        label = _as_text(answer).lower()
        if label in {"true", "yes"}:
            return True
        if label in {"false", "no"}:
            return False
        return answer
    if answer_type == "number":
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            return answer
        label = _as_text(answer).replace(",", "")
        if not label:
            return None
        try:
            return int(label) if "." not in label else float(label)
        except ValueError:
            return answer
    if answer_type == "names":
        if isinstance(answer, list):
            return [_as_text(item) for item in answer if _as_text(item)]
        label = _as_text(answer)
        if not label:
            return []
        return [part.strip() for part in label.replace("\n", ",").split(",") if part.strip()]
    if isinstance(answer, str):
        return answer.strip()
    return answer


def _normalize_answer_value(answer: Any, answer_type: str, *, abstained: bool) -> str | None:
    if abstained:
        return None
    _, normalized = normalize_answer(answer, answer_type)
    return normalized


def _sources_summary_from_runtime_sources(sources: Any) -> str:
    if not isinstance(sources, list) or not sources:
        return "none"
    used_ids = _dedupe_preserve(
        _as_text(item.get("source_page_id"))
        for item in sources
        if isinstance(item, Mapping) and bool(item.get("used"))
    )
    if used_ids:
        return f"runtime_used:{', '.join(used_ids)}"
    all_ids = _dedupe_preserve(
        _as_text(item.get("source_page_id"))
        for item in sources
        if isinstance(item, Mapping)
    )
    if not all_ids:
        return "none"
    return f"runtime_returned:{', '.join(all_ids)}"


def _derive_failure_note(
    *,
    item: Mapping[str, Any],
    baseline_id: str,
    abstained: bool,
    sources_summary: str,
    existing_note: str,
) -> str:
    if existing_note:
        return existing_note
    expected_behavior = _as_text(item.get("expected_behavior"))
    if baseline_id == "B0" and sources_summary != "none":
        return "b0_sources_must_be_none"
    if expected_behavior == "abstain_or_explicit_no_answer" and not abstained:
        return "manual_no_answer_should_abstain"
    if expected_behavior == "answer_from_corpus" and abstained:
        return "unexpected_abstain_on_public_slice"
    return ""


def _slice_item_map(slice_artifact: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in slice_artifact.get("items", []):
        if isinstance(item, Mapping):
            out[_as_text(item.get("id"))] = dict(item)
    return out


def _extract_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        items = payload.get("items")
        if isinstance(items, list):
            return [dict(item) for item in items if isinstance(item, Mapping)]
    raise ValueError("input payload must be a list or an object with an items array")


def normalize_model_result_artifact(
    slice_artifact: Mapping[str, Any],
    *,
    baseline_id: str,
    raw_payload: Any,
) -> Dict[str, Any]:
    item_by_id = _slice_item_map(slice_artifact)
    raw_items = { _as_text(item.get("id")): item for item in _extract_items(raw_payload) }
    rows: List[Dict[str, Any]] = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        item_id = _as_text(item.get("id"))
        raw_item = raw_items.get(item_id)
        if raw_item is None:
            raise ValueError(f"missing result row for item: {item_id}")
        answer_type = _as_text(item.get("answer_type"))
        abstained = bool(raw_item.get("abstained"))
        answer = _coerce_model_answer(raw_item.get("answer"), answer_type)
        sources_summary = _as_text(raw_item.get("sources_summary"))
        if not sources_summary:
            sources_summary = "none" if baseline_id == "B0" else "naive_context:none"
        rows.append(
            {
                "id": item_id,
                "baseline_id": baseline_id,
                "answer": answer,
                "answer_normalized": _normalize_answer_value(answer, answer_type, abstained=abstained),
                "abstained": abstained,
                "sources_summary": sources_summary,
                "short_failure_note": _derive_failure_note(
                    item=item_by_id[item_id],
                    baseline_id=baseline_id,
                    abstained=abstained,
                    sources_summary=sources_summary,
                    existing_note=_as_text(raw_item.get("short_failure_note")),
                ),
            }
        )
    return {
        "artifact_version": RESULT_FORMAT_VERSION,
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "baseline_id": baseline_id,
        "baseline_name": BASELINES[baseline_id]["baseline_name"],
        "item_count": len(rows),
        "items": rows,
    }


def normalize_b2_response_artifact(
    slice_artifact: Mapping[str, Any],
    *,
    responses_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    item_by_id = _slice_item_map(slice_artifact)
    rows: List[Dict[str, Any]] = []
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        item_id = _as_text(item.get("id"))
        response = responses_by_id.get(item_id)
        if response is None:
            raise ValueError(f"missing B2 response for item: {item_id}")
        answer_type = _as_text(item.get("answer_type"))
        abstained = bool(response.get("abstained"))
        answer = response.get("answer")
        answer_normalized = _as_text(response.get("answer_normalized")) or _normalize_answer_value(
            answer,
            answer_type,
            abstained=abstained,
        )
        sources_summary = _sources_summary_from_runtime_sources(response.get("sources"))
        rows.append(
            {
                "id": item_id,
                "baseline_id": "B2",
                "answer": answer,
                "answer_normalized": answer_normalized,
                "abstained": abstained,
                "sources_summary": sources_summary,
                "short_failure_note": _derive_failure_note(
                    item=item_by_id[item_id],
                    baseline_id="B2",
                    abstained=abstained,
                    sources_summary=sources_summary,
                    existing_note="",
                ),
            }
        )
    return {
        "artifact_version": RESULT_FORMAT_VERSION,
        "slice_id": _as_text(slice_artifact.get("slice_id")),
        "baseline_id": "B2",
        "baseline_name": BASELINES["B2"]["baseline_name"],
        "item_count": len(rows),
        "items": rows,
    }


def _fetch_b2_run_responses(
    *,
    base_url: str,
    run_id: str,
    slice_artifact: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    responses: Dict[str, Dict[str, Any]] = {}
    for item in slice_artifact.get("items", []):
        if not isinstance(item, Mapping):
            continue
        item_id = _as_text(item.get("id"))
        response = _request_json(
            base_url,
            f"/v1/runs/{run_id}/questions/{item_id}",
            method="GET",
        )
        responses[item_id] = response
    return responses


def build_bundle_readme(output_dir: Path) -> str:
    return "\n".join(
        [
            "# First Meaningful QA Baseline Bundle",
            "",
            "Machine-readable artifacts for comparing B0/B1/B2 on the fixed product QA slice.",
            "",
            "Files written here:",
            "- `fixed_slice.json`: canonical item list for the fixed slice.",
            "- `fixed_slice_dataset_import.json`: dataset import payload for running B2 on the same ids, including manual no-answer items.",
            "- `baseline_result_schema.json`: unified per-item compare schema.",
            "- `B0_request_pack.json`: question-only prompt pack.",
            "- `B1_request_pack.template.json`: naive-context prompt template; hydrate with `build-b1-request-pack` against a live API + corpus.",
            "",
            "Typical next commands:",
            f"- `./.venv/bin/python scripts/qa_baseline_prep.py build-b1-request-pack --base-url http://127.0.0.1:8000 --project-id <PROJECT_ID> --output {output_dir / 'B1_request_pack.json'}`",
            f"- `./.venv/bin/python scripts/qa_baseline_prep.py normalize-b2-run --base-url http://127.0.0.1:8000 --run-id <RUN_ID> --output {output_dir / 'B2_results.json'}`",
            "",
            "Notes:",
            "- B0 is a hallucination floor and not a merge gate.",
            "- B1 is the primary LLM-only baseline.",
            "- B2 is normalized from current runtime `QueryResponse` rows.",
        ]
    ) + "\n"


def bootstrap(output_dir: Path, *, top_k: int) -> None:
    public_question_map = _load_public_question_map()
    slice_artifact = build_fixed_slice_artifact(public_question_map)
    _write_json(output_dir / "fixed_slice.json", slice_artifact)
    _write_json(output_dir / "fixed_slice_dataset_import.json", build_dataset_import_payload(slice_artifact))
    _write_json(
        output_dir / "baseline_result_schema.json",
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "slice_id": SLICE_ID,
            "schema": RESULT_SCHEMA,
        },
    )
    _write_json(output_dir / "B0_request_pack.json", build_b0_request_pack(slice_artifact))
    _write_json(
        output_dir / "B1_request_pack.template.json",
        build_b1_request_pack_template(slice_artifact, top_k=top_k),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(build_bundle_readme(output_dir), encoding="utf-8")


def _load_slice_artifact(path: Path) -> Dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise ValueError("slice artifact must be a JSON object")
    return dict(payload)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="Write the fixed slice bundle and request pack templates.")
    p_bootstrap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p_bootstrap.add_argument("--top-k", type=int, default=5)

    p_b1 = sub.add_parser("build-b1-request-pack", help="Build live B1 request pack from corpus search snippets.")
    p_b1.add_argument("--slice-file", default=str(DEFAULT_OUTPUT_DIR / "fixed_slice.json"))
    p_b1.add_argument("--base-url", required=True)
    p_b1.add_argument("--project-id", required=True)
    p_b1.add_argument("--top-k", type=int, default=5)
    p_b1.add_argument("--output", required=True)

    p_norm_model = sub.add_parser(
        "normalize-model-results",
        help="Normalize B0/B1 raw result rows into the unified compare artifact.",
    )
    p_norm_model.add_argument("--slice-file", default=str(DEFAULT_OUTPUT_DIR / "fixed_slice.json"))
    p_norm_model.add_argument("--baseline-id", choices=["B0", "B1"], required=True)
    p_norm_model.add_argument("--input", required=True)
    p_norm_model.add_argument("--output", required=True)

    p_norm_b2 = sub.add_parser(
        "normalize-b2-run",
        help="Fetch B2 run question rows and normalize them into the unified compare artifact.",
    )
    p_norm_b2.add_argument("--slice-file", default=str(DEFAULT_OUTPUT_DIR / "fixed_slice.json"))
    p_norm_b2.add_argument("--base-url", required=True)
    p_norm_b2.add_argument("--run-id", required=True)
    p_norm_b2.add_argument("--output", required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "bootstrap":
            bootstrap(Path(args.output_dir), top_k=args.top_k)
            return 0

        if args.command == "build-b1-request-pack":
            slice_artifact = _load_slice_artifact(Path(args.slice_file))
            payload = build_b1_request_pack(
                slice_artifact,
                base_url=args.base_url,
                project_id=args.project_id,
                top_k=args.top_k,
            )
            _write_json(Path(args.output), payload)
            return 0

        if args.command == "normalize-model-results":
            slice_artifact = _load_slice_artifact(Path(args.slice_file))
            raw_payload = _read_json(Path(args.input))
            payload = normalize_model_result_artifact(
                slice_artifact,
                baseline_id=args.baseline_id,
                raw_payload=raw_payload,
            )
            _write_json(Path(args.output), payload)
            return 0

        if args.command == "normalize-b2-run":
            slice_artifact = _load_slice_artifact(Path(args.slice_file))
            responses = _fetch_b2_run_responses(
                base_url=args.base_url,
                run_id=args.run_id,
                slice_artifact=slice_artifact,
            )
            payload = normalize_b2_response_artifact(slice_artifact, responses_by_id=responses)
            _write_json(Path(args.output), payload)
            return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
