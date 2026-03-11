from __future__ import annotations

from typing import Any, Mapping

from packages.scorers.contracts import submission_contract_preflight

DEFAULT_ARCHITECTURE_SUMMARY = (
    "Legal Agentic RAG with deterministic, route-aware retrieval and page-grounded answering."
)
OFFICIAL_SUBMISSION_VALIDATOR_VERSION = "official_submission_validator.v1"


def submission_preflight_report(
    questions: Mapping[str, object],
    *,
    strict_contract_mode: bool | None = None,
) -> dict[str, Any]:
    predictions = list(questions.values())
    return submission_contract_preflight(predictions, strict_contract_mode=strict_contract_mode)


def official_submission_tpot_ms(pred: object) -> int:
    telemetry = getattr(pred, "telemetry", None)
    if telemetry is None:
        return 0
    explicit = getattr(telemetry, "time_per_output_token_ms", None)
    if explicit is not None:
        try:
            return max(0, int(round(float(explicit))))
        except (TypeError, ValueError):
            return 0
    try:
        output_tokens = int(getattr(telemetry, "output_tokens", 0) or 0)
        total_time_ms = int(getattr(telemetry, "total_response_ms", 0) or 0)
        ttft_ms = int(getattr(telemetry, "ttft_ms", 0) or 0)
    except (TypeError, ValueError):
        return 0
    if output_tokens <= 0:
        return 0
    generation_window_ms = max(0, total_time_ms - ttft_ms)
    return max(0, int(round(generation_window_ms / output_tokens)))


def source_page_to_retrieval_ref(source: object, default_page_index_base: int) -> dict[str, Any]:
    pdf_id = str(getattr(source, "pdf_id", "") or "").strip()
    page_num_raw = getattr(source, "page_num", 0)
    page_index_base_raw = getattr(source, "page_index_base", default_page_index_base)
    try:
        page_num = int(page_num_raw or 0)
    except (TypeError, ValueError):
        page_num = 0
    try:
        page_index_base = int(page_index_base_raw or default_page_index_base)
    except (TypeError, ValueError):
        page_index_base = int(default_page_index_base)
    physical_page_num = page_num if page_index_base == 1 else page_num + 1
    if physical_page_num < 1:
        physical_page_num = 1
    return {
        "doc_id": pdf_id or str(getattr(source, "source_page_id", "")).rsplit("_", 1)[0],
        "page_number": int(physical_page_num),
    }


def official_retrieval_chunk_pages(pred: object, *, default_page_index_base: int) -> list[dict[str, Any]]:
    grouped: dict[str, set[int]] = {}
    sources = getattr(pred, "sources", []) or []
    for source in sources:
        if not bool(getattr(source, "used", False)):
            continue
        ref = source_page_to_retrieval_ref(source, default_page_index_base)
        doc_id = str(ref.get("doc_id", "")).strip()
        page_number = int(ref.get("page_number", 1) or 1)
        if not doc_id:
            continue
        grouped.setdefault(doc_id, set()).add(page_number)
    out: list[dict[str, Any]] = []
    for doc_id in sorted(grouped.keys()):
        out.append(
            {
                "doc_id": doc_id,
                "page_numbers": sorted(grouped[doc_id]),
            }
        )
    return out


def build_official_submission_answers(
    questions: Mapping[str, object],
    *,
    default_page_index_base: int,
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for qid in sorted(questions.keys()):
        pred = questions[qid]
        telemetry = getattr(pred, "telemetry", None)
        ttft_ms = int(max(0, int(getattr(telemetry, "ttft_ms", 0) or 0))) if telemetry else 0
        total_time_ms = int(max(ttft_ms, int(getattr(telemetry, "total_response_ms", 0) or 0))) if telemetry else 0
        answer_payload = {
            "question_id": qid,
            "answer": getattr(pred, "answer", None),
            "telemetry": {
                "timing": {
                    "ttft_ms": ttft_ms,
                    "tpot_ms": official_submission_tpot_ms(pred),
                    "total_time_ms": total_time_ms,
                },
                "retrieval": {
                    "retrieved_chunk_pages": official_retrieval_chunk_pages(
                        pred,
                        default_page_index_base=default_page_index_base,
                    )
                },
                "usage": {
                    "input_tokens": int(max(0, int(getattr(telemetry, "input_tokens", 0) or 0))) if telemetry else 0,
                    "output_tokens": int(max(0, int(getattr(telemetry, "output_tokens", 0) or 0))) if telemetry else 0,
                },
                "model_name": str(getattr(telemetry, "model_name", "") or ""),
            },
        }
        answers.append(answer_payload)
    return answers


def build_official_submission_payload(
    questions: Mapping[str, object],
    *,
    default_page_index_base: int,
    architecture_summary: str | None = None,
) -> dict[str, Any]:
    summary = str(architecture_summary or "").strip() or DEFAULT_ARCHITECTURE_SUMMARY
    return {
        "architecture_summary": summary,
        "answers": build_official_submission_answers(
            questions,
            default_page_index_base=default_page_index_base,
        ),
    }


def _is_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def validate_official_submission_payload(payload: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    answer_count = 0

    if not isinstance(payload, dict):
        return {
            "validator_version": OFFICIAL_SUBMISSION_VALIDATOR_VERSION,
            "valid": False,
            "answer_count": 0,
            "error_count": 1,
            "errors": [{"path": "$", "error": "submission must be an object"}],
        }

    if not _is_non_empty_text(payload.get("architecture_summary")):
        errors.append(
            {
                "path": "$.architecture_summary",
                "error": "architecture_summary must be non-empty text",
            }
        )

    answers = payload.get("answers")
    if not isinstance(answers, list):
        errors.append({"path": "$.answers", "error": "answers must be an array"})
        answers = []
    answer_count = len(answers)

    seen_qids: set[str] = set()
    for idx, item in enumerate(answers):
        path = f"$.answers[{idx}]"
        if not isinstance(item, dict):
            errors.append({"path": path, "error": "answer item must be an object"})
            continue

        qid = str(item.get("question_id", "")).strip()
        if not qid:
            errors.append({"path": f"{path}.question_id", "error": "question_id is required"})
        elif qid in seen_qids:
            errors.append({"path": f"{path}.question_id", "error": "question_id must be unique"})
        else:
            seen_qids.add(qid)

        telemetry = item.get("telemetry")
        if not isinstance(telemetry, dict):
            errors.append({"path": f"{path}.telemetry", "error": "telemetry must be an object"})
            continue

        timing = telemetry.get("timing")
        if not isinstance(timing, dict):
            errors.append({"path": f"{path}.telemetry.timing", "error": "timing must be an object"})
        else:
            ttft_ms = timing.get("ttft_ms")
            tpot_ms = timing.get("tpot_ms")
            total_time_ms = timing.get("total_time_ms")
            if not _is_non_negative_int(ttft_ms):
                errors.append({"path": f"{path}.telemetry.timing.ttft_ms", "error": "ttft_ms must be >= 0 integer"})
            if not _is_non_negative_int(tpot_ms):
                errors.append({"path": f"{path}.telemetry.timing.tpot_ms", "error": "tpot_ms must be >= 0 integer"})
            if not _is_non_negative_int(total_time_ms):
                errors.append(
                    {"path": f"{path}.telemetry.timing.total_time_ms", "error": "total_time_ms must be >= 0 integer"}
                )
            if _is_non_negative_int(ttft_ms) and _is_non_negative_int(total_time_ms) and total_time_ms < ttft_ms:
                errors.append(
                    {
                        "path": f"{path}.telemetry.timing.total_time_ms",
                        "error": "total_time_ms must be >= ttft_ms",
                    }
                )

        retrieval = telemetry.get("retrieval")
        if not isinstance(retrieval, dict):
            errors.append({"path": f"{path}.telemetry.retrieval", "error": "retrieval must be an object"})
        else:
            grouped_pages = retrieval.get("retrieved_chunk_pages")
            if not isinstance(grouped_pages, list):
                errors.append(
                    {
                        "path": f"{path}.telemetry.retrieval.retrieved_chunk_pages",
                        "error": "retrieved_chunk_pages must be an array",
                    }
                )
            else:
                for ref_idx, ref in enumerate(grouped_pages):
                    ref_path = f"{path}.telemetry.retrieval.retrieved_chunk_pages[{ref_idx}]"
                    if not isinstance(ref, dict):
                        errors.append({"path": ref_path, "error": "retrieval entry must be an object"})
                        continue
                    doc_id = str(ref.get("doc_id", "")).strip()
                    page_numbers = ref.get("page_numbers")
                    if not doc_id:
                        errors.append({"path": f"{ref_path}.doc_id", "error": "doc_id is required"})
                    if not isinstance(page_numbers, list):
                        errors.append({"path": f"{ref_path}.page_numbers", "error": "page_numbers must be an array"})
                        continue
                    normalized_page_numbers: list[int] = []
                    page_number_error = False
                    for page_idx, page_number in enumerate(page_numbers):
                        if not isinstance(page_number, int) or page_number < 1:
                            errors.append(
                                {
                                    "path": f"{ref_path}.page_numbers[{page_idx}]",
                                    "error": "page number must be integer >= 1",
                                }
                            )
                            page_number_error = True
                        else:
                            normalized_page_numbers.append(page_number)
                    if page_number_error:
                        continue
                    if sorted(set(normalized_page_numbers)) != normalized_page_numbers:
                        errors.append(
                            {
                                "path": f"{ref_path}.page_numbers",
                                "error": "page_numbers must be unique and sorted ascending",
                            }
                        )

        usage = telemetry.get("usage")
        if not isinstance(usage, dict):
            errors.append({"path": f"{path}.telemetry.usage", "error": "usage must be an object"})
        else:
            if not _is_non_negative_int(usage.get("input_tokens")):
                errors.append(
                    {
                        "path": f"{path}.telemetry.usage.input_tokens",
                        "error": "input_tokens must be >= 0 integer",
                    }
                )
            if not _is_non_negative_int(usage.get("output_tokens")):
                errors.append(
                    {
                        "path": f"{path}.telemetry.usage.output_tokens",
                        "error": "output_tokens must be >= 0 integer",
                    }
                )

        if not isinstance(telemetry.get("model_name"), str):
            errors.append({"path": f"{path}.telemetry.model_name", "error": "model_name must be text"})

    return {
        "validator_version": OFFICIAL_SUBMISSION_VALIDATOR_VERSION,
        "valid": not errors,
        "answer_count": answer_count,
        "error_count": len(errors),
        "errors": errors,
    }
