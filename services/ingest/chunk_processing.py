"""Deterministic structural chunk processing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional


_WS = re.compile(r"\s+")
_HEADING_REF_TOKEN = r"(?:\d{1,3}|[IVXLCM]{1,8}|[A-Z])"
_PART_PATTERN = re.compile(
    rf"\b(PART\s+{_HEADING_REF_TOKEN}(?::\s*[A-Z][A-Za-z0-9 ,&()'/-]{{2,120}}?)?)(?=\s+(?:\d{{1,3}}\.\s+[A-Z]|ARTICLE\s+\d{{1,3}}|CHAPTER\s+{_HEADING_REF_TOKEN}|SECTION\s+{_HEADING_REF_TOKEN}|SCHEDULE\s+{_HEADING_REF_TOKEN}|$))",
    re.IGNORECASE,
)
_CHAPTER_PATTERN = re.compile(
    rf"\b(CHAPTER\s+{_HEADING_REF_TOKEN}(?::\s*[A-Z][A-Za-z0-9 ,&()'/-]{{2,120}}?)?)(?=\s+(?:\d{{1,3}}\.\s+[A-Z]|ARTICLE\s+\d{{1,3}}|SECTION\s+{_HEADING_REF_TOKEN}|SCHEDULE\s+{_HEADING_REF_TOKEN}|$))",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    rf"\b(SECTION\s+{_HEADING_REF_TOKEN}(?::\s*[A-Z][A-Za-z0-9 ,&()'/-]{{2,120}}?)?)(?=\s+(?:\d{{1,3}}\.\s+[A-Z]|ARTICLE\s+\d{{1,3}}|SCHEDULE\s+{_HEADING_REF_TOKEN}|$))",
    re.IGNORECASE,
)
_SCHEDULE_PATTERN = re.compile(
    rf"\b(SCHEDULE\s+{_HEADING_REF_TOKEN}(?::\s*[A-Z][A-Za-z0-9 ,&()'/-]{{2,120}}?)?)(?=\s+(?:\d{{1,3}}\.\s+[A-Z]|ARTICLE\s+\d{{1,3}}|$))",
    re.IGNORECASE,
)
_LAW_ARTICLE_START_PATTERN = re.compile(r"(?<!\()(?<!\.)\b(\d{1,3})\.\s+[A-Z]")
_ORDER_ITEM_PATTERN = re.compile(r"(?<!Article )(?<!Part )(?<!Schedule )\b(\d{1,3})\.\s+")
_CASE_NUMBER_MARKER = re.compile(r"\b(?:Claim|Case|Appeal)\s+No[:.]?\s*", re.IGNORECASE)
_ORDER_HEADING_PATTERN = re.compile(r"\b(?:ORDER WITH REASONS|JUDGMENT|ORDER)\b", re.IGNORECASE)
_ORDER_MARKER_PATTERN = re.compile(r"\bIT IS HEREBY ORDERED THAT[: ]", re.IGNORECASE)
_REASONS_HEADING_PATTERN = re.compile(r"\bSCHEDULE OF REASONS\b", re.IGNORECASE)
_LEADING_LIST_ITEM_PATTERN = re.compile(r"^\s*(\d{1,3})\.\s+")


def _compact(value: str) -> str:
    return _WS.sub(" ", value or "").strip()


def _lineage_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _compact(value).lower()).strip("_") or "root"


@dataclass
class StructuralChunk:
    text: str
    chunk_type: str
    section_kind: str
    char_start: int
    char_end: int
    heading_path: List[str] = field(default_factory=list)
    structural_level: int = 1
    local_key: Optional[str] = None
    parent_local_key: Optional[str] = None
    part_ref: Optional[str] = None
    chapter_ref: Optional[str] = None
    section_ref: Optional[str] = None
    article_number: Optional[str] = None
    article_title: Optional[str] = None
    schedule_number: Optional[str] = None
    schedule_title: Optional[str] = None
    section_kind_case: Optional[str] = None
    paragraph_class: Optional[str] = None
    parent_section_id: Optional[str] = None
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None


def _match_title_from_heading(chunk_text: str) -> str | None:
    match = re.match(r"(?:Article\s+)?(\d{1,3}(?:\([A-Za-z0-9]+\))?)\.\s+(.+)", chunk_text, re.IGNORECASE)
    if not match:
        return None
    title = match.group(2)
    title = re.split(r"\s+\(\d+\)\s+|\s+An?\s+[A-Z][a-z]+ shall\b|\s+The\s+[A-Z][a-z]+\s+is\b", title, maxsplit=1)[0]
    title = re.split(r"\s{2,}", title, maxsplit=1)[0]
    title = _compact(title).strip(" .;:")
    return title[:120] if title else None


def _section_kind_for_law_chunk(text: str, article_title: str | None) -> str:
    lowered = text.lower()
    title_lower = (article_title or "").lower()
    if "means" in lowered or "definition" in title_lower:
        return "definition"
    if any(token in lowered for token in ("unless", "except", "provided that")):
        return "exception"
    if any(token in lowered for token in ("fine", "penalty", "liable to")):
        return "penalty"
    if any(token in lowered for token in ("apply", "file", "submit", "procedure")):
        return "procedure"
    if "schedule" in title_lower:
        return "schedule_item"
    return "operative_provision"


def _case_section_kind_for_text(text: str, *, default: str = "reasoning") -> str:
    lowered = text.lower()
    if "between" in lowered and "claimant" in lowered and "defendant" in lowered:
        return "parties"
    if "it is hereby ordered" in lowered or "shall pay" in lowered or "is hereby ordered" in lowered:
        return "order"
    if "interest will accrue" in lowered or "interest shall accrue" in lowered or "costs are not paid" in lowered:
        return "order"
    if "schedule of reasons" in lowered or lowered.startswith("1. ") or "for these reasons" in lowered:
        return "reasoning"
    if any(token in lowered for token in ("dismissed", "granted", "stayed", "disposed of")):
        return "disposition"
    if lowered.startswith("upon ") or "application" in lowered:
        return "procedural_history"
    return default


def _fallback_segments(page_text: str, *, default_kind: str, paragraph_class: str) -> List[StructuralChunk]:
    normalized = _compact(page_text)
    if not normalized:
        return []
    current = normalized
    segments: List[StructuralChunk] = []
    offset = 0
    while current:
        if len(current) <= 900:
            end = offset + len(current)
            segments.append(
                StructuralChunk(
                    text=current,
                    chunk_type="paragraph",
                    section_kind=default_kind,
                    char_start=offset,
                    char_end=end,
                    structural_level=1,
                    paragraph_class=paragraph_class,
                )
            )
            break
        cut = current.rfind(" ", 0, 900)
        if cut < 200:
            cut = 900
        segment = current[:cut].strip()
        if segment:
            end = offset + len(segment)
            segments.append(
                StructuralChunk(
                    text=segment,
                    chunk_type="paragraph",
                    section_kind=default_kind,
                    char_start=offset,
                    char_end=end,
                    structural_level=1,
                    paragraph_class=paragraph_class,
                )
            )
        current = current[cut:].strip()
        offset = len(normalized) - len(current)
    return segments


def _heading_ref(match_text: str, prefix: str) -> str | None:
    match = re.search(rf"{prefix}\s+([A-Z0-9]+)", match_text, re.IGNORECASE)
    return match.group(1) if match else None


def _heading_chunks(text: str, pattern: re.Pattern[str], section_kind: str, level: int) -> List[StructuralChunk]:
    out: List[StructuralChunk] = []
    for match in pattern.finditer(text):
        heading = _compact(match.group(1))
        if not heading:
            continue
        ref_prefix = heading.split(":", 1)[0]
        out.append(
            StructuralChunk(
                text=heading,
                chunk_type="heading",
                section_kind=section_kind,
                char_start=match.start(1),
                char_end=match.start(1) + len(heading),
                heading_path=[heading],
                structural_level=level,
                local_key=f"{section_kind}:{_lineage_key(ref_prefix)}",
                paragraph_class="heading",
            )
        )
    return out


def _article_chunks_for_law_like(page_text: str) -> List[StructuralChunk]:
    text = _compact(page_text)
    if not text:
        return []

    chunks: List[StructuralChunk] = []
    chunks.extend(_heading_chunks(text, _PART_PATTERN, "heading", 1))
    chunks.extend(_heading_chunks(text, _CHAPTER_PATTERN, "heading", 2))
    chunks.extend(_heading_chunks(text, _SECTION_PATTERN, "heading", 3))
    chunks.extend(_heading_chunks(text, _SCHEDULE_PATTERN, "schedule_item", 2))

    article_matches = list(_LAW_ARTICLE_START_PATTERN.finditer(text))
    if not article_matches:
        return chunks + _fallback_segments(text, default_kind="operative_provision", paragraph_class="body")

    part_headings = [item for item in chunks if str(item.local_key or "").startswith("heading:part")]
    chapter_headings = [item for item in chunks if str(item.local_key or "").startswith("heading:chapter")]
    section_headings = [item for item in chunks if str(item.local_key or "").startswith("heading:section")]
    schedule_headings = [item for item in chunks if str(item.local_key or "").startswith("schedule_item:schedule")]

    for index, match in enumerate(article_matches):
        start = match.start(1)
        end = article_matches[index + 1].start(1) if index + 1 < len(article_matches) else len(text)
        article_text = _compact(text[start:end])
        if not article_text:
            continue
        article_number = match.group(1)
        article_title = _match_title_from_heading(article_text)
        active_part = next((item for item in reversed(part_headings) if item.char_start <= start), None)
        active_chapter = next((item for item in reversed(chapter_headings) if item.char_start <= start), None)
        active_section = next((item for item in reversed(section_headings) if item.char_start <= start), None)
        active_schedule = next((item for item in reversed(schedule_headings) if item.char_start <= start), None)
        heading_path = [
            item.text
            for item in (active_part, active_chapter, active_section, active_schedule)
            if item is not None and item.text
        ]
        heading_path.append(f"Article {article_number}" + (f" {article_title}" if article_title else ""))
        parent = active_section or active_chapter or active_part or active_schedule
        chunks.append(
            StructuralChunk(
                text=article_text,
                chunk_type="paragraph",
                section_kind=_section_kind_for_law_chunk(article_text, article_title),
                char_start=start,
                char_end=min(len(text), start + len(article_text)),
                heading_path=heading_path,
                structural_level=2 if parent else 1,
                local_key=f"article:{article_number}",
                parent_local_key=parent.local_key if parent else None,
                part_ref=_heading_ref(active_part.text, "PART") if active_part else None,
                chapter_ref=_heading_ref(active_chapter.text, "CHAPTER") if active_chapter else None,
                section_ref=_heading_ref(active_section.text, "SECTION") if active_section else None,
                article_number=article_number,
                article_title=article_title,
                schedule_number=_heading_ref(active_schedule.text, "SCHEDULE") if active_schedule else None,
                schedule_title=active_schedule.text if active_schedule else None,
                paragraph_class="article_clause",
            )
        )

    chunks.sort(key=lambda item: (item.char_start, item.structural_level, item.chunk_type != "heading"))
    return chunks


def _extract_case_chunks(page_text: str) -> List[StructuralChunk]:
    text = _compact(page_text)
    if not text:
        return []

    chunks: List[StructuralChunk] = []
    leading_window = text[:450]
    has_caption_signals = bool(
        _CASE_NUMBER_MARKER.search(leading_window)
        or " BETWEEN " in f" {leading_window.upper()} "
        or " IN THE " in f" {leading_window.upper()} "
    )
    caption_end_candidates = [m.start() for m in (_CASE_NUMBER_MARKER.search(text), _ORDER_HEADING_PATTERN.search(text)) if m] if has_caption_signals else []
    caption_end = min(caption_end_candidates) if caption_end_candidates else 0
    if caption_end > 20:
        caption_text = _compact(text[:caption_end])
        chunks.append(
            StructuralChunk(
                text=caption_text,
                chunk_type="heading",
                section_kind="parties",
                char_start=0,
                char_end=len(caption_text),
                heading_path=[caption_text[:120]],
                structural_level=1,
                local_key="case:caption",
                section_kind_case="parties",
                paragraph_class="case_excerpt",
            )
        )

    order_heading_match = _ORDER_HEADING_PATTERN.search(text) if has_caption_signals else None
    order_marker_match = _ORDER_MARKER_PATTERN.search(text)
    reasons_heading_match = _REASONS_HEADING_PATTERN.search(text)

    if not has_caption_signals:
        leading_list_match = _LEADING_LIST_ITEM_PATTERN.search(text)
        if leading_list_match:
            pre_reasons_text = text[: reasons_heading_match.start()] if reasons_heading_match else text
            pre_reason_items = list(_ORDER_ITEM_PATTERN.finditer(pre_reasons_text))
            if pre_reason_items:
                continuation_section = _case_section_kind_for_text(pre_reasons_text, default="reasoning")
                continuation_key = (
                    "case:continuation_order"
                    if continuation_section in {"order", "disposition"}
                    else "case:continuation_reasoning"
                )
                continuation_section_kind = "order" if continuation_section == "order" else "reasoning"
                chunks.append(
                    StructuralChunk(
                        text="Continuation",
                        chunk_type="heading",
                        section_kind=continuation_section_kind,
                        char_start=0,
                        char_end=len("Continuation"),
                        heading_path=["Continuation"],
                        structural_level=1,
                        local_key=continuation_key,
                        section_kind_case=continuation_section,
                        paragraph_class="case_excerpt",
                    )
                )
                for idx, item_match in enumerate(pre_reason_items):
                    start = item_match.start()
                    end = pre_reason_items[idx + 1].start() if idx + 1 < len(pre_reason_items) else len(pre_reasons_text)
                    item_text = _compact(text[start:end])
                    if not item_text:
                        continue
                    item_kind_case = _case_section_kind_for_text(item_text, default=continuation_section)
                    item_section_kind = "order" if item_kind_case == "order" else "reasoning"
                    chunks.append(
                        StructuralChunk(
                            text=item_text,
                            chunk_type="list_item",
                            section_kind=item_section_kind,
                            char_start=start,
                            char_end=min(len(text), start + len(item_text)),
                            heading_path=["Continuation", item_text[:80]],
                            structural_level=2,
                            parent_local_key=continuation_key,
                            section_kind_case=item_kind_case,
                            paragraph_class="case_excerpt",
                        )
                    )

    if order_heading_match:
        heading_text = _compact(order_heading_match.group(0))
        chunks.append(
            StructuralChunk(
                text=heading_text,
                chunk_type="heading",
                section_kind="order",
                char_start=order_heading_match.start(),
                char_end=order_heading_match.start() + len(heading_text),
                heading_path=[heading_text],
                structural_level=1,
                local_key="case:order_heading",
                section_kind_case="order",
                paragraph_class="case_excerpt",
            )
        )

    body_start = order_heading_match.end() if order_heading_match else 0
    order_body_end = reasons_heading_match.start() if reasons_heading_match else len(text)
    if order_marker_match:
        recital_text = _compact(text[body_start:order_marker_match.start()])
        if recital_text:
            chunks.append(
                StructuralChunk(
                    text=recital_text,
                    chunk_type="paragraph",
                    section_kind="procedural_history",
                    char_start=body_start,
                    char_end=body_start + len(recital_text),
                    heading_path=["Order context"],
                    structural_level=2,
                    parent_local_key="case:order_heading" if order_heading_match else None,
                    section_kind_case="procedural_history",
                    paragraph_class="case_excerpt",
                )
            )
        order_items_text = text[order_marker_match.end():order_body_end]
        item_matches = list(_ORDER_ITEM_PATTERN.finditer(order_items_text))
        if item_matches:
            order_heading_key = "case:operative_order"
            chunks.append(
                StructuralChunk(
                    text="IT IS HEREBY ORDERED THAT",
                    chunk_type="heading",
                    section_kind="order",
                    char_start=order_marker_match.start(),
                    char_end=order_marker_match.start() + len("IT IS HEREBY ORDERED THAT"),
                    heading_path=["IT IS HEREBY ORDERED THAT"],
                    structural_level=1,
                    local_key=order_heading_key,
                    parent_local_key="case:order_heading" if order_heading_match else None,
                    section_kind_case="order",
                    paragraph_class="case_excerpt",
                )
            )
            for idx, item_match in enumerate(item_matches):
                start = order_marker_match.end() + item_match.start()
                end = order_marker_match.end() + (
                    item_matches[idx + 1].start() if idx + 1 < len(item_matches) else len(order_items_text)
                )
                item_text = _compact(text[start:end])
                if not item_text:
                    continue
                chunks.append(
                    StructuralChunk(
                        text=item_text,
                        chunk_type="list_item",
                        section_kind="order",
                        char_start=start,
                        char_end=min(len(text), start + len(item_text)),
                        heading_path=["IT IS HEREBY ORDERED THAT", item_text[:80]],
                        structural_level=2,
                        parent_local_key=order_heading_key,
                        section_kind_case="order",
                        paragraph_class="case_excerpt",
                    )
                )

    if reasons_heading_match:
        heading_text = _compact(reasons_heading_match.group(0))
        reasons_key = "case:reasons_heading"
        chunks.append(
            StructuralChunk(
                text=heading_text,
                chunk_type="heading",
                section_kind="reasoning",
                char_start=reasons_heading_match.start(),
                char_end=reasons_heading_match.start() + len(heading_text),
                heading_path=[heading_text],
                structural_level=1,
                local_key=reasons_key,
                section_kind_case="reasoning",
                paragraph_class="case_excerpt",
            )
        )
        reasoning_text = text[reasons_heading_match.end():]
        reasoning_matches = list(_ORDER_ITEM_PATTERN.finditer(reasoning_text))
        if reasoning_matches:
            for idx, item_match in enumerate(reasoning_matches):
                start = reasons_heading_match.end() + item_match.start()
                end = reasons_heading_match.end() + (
                    reasoning_matches[idx + 1].start() if idx + 1 < len(reasoning_matches) else len(reasoning_text)
                )
                item_text = _compact(text[start:end])
                if not item_text:
                    continue
                section_kind_case = _case_section_kind_for_text(item_text)
                section_kind = "disposition" if section_kind_case == "disposition" else "reasoning"
                chunks.append(
                    StructuralChunk(
                        text=item_text,
                        chunk_type="list_item",
                        section_kind=section_kind,
                        char_start=start,
                        char_end=min(len(text), start + len(item_text)),
                        heading_path=[heading_text, item_text[:80]],
                        structural_level=2,
                        parent_local_key=reasons_key,
                        section_kind_case=section_kind_case,
                        paragraph_class="case_excerpt",
                    )
                )

    if chunks:
        chunks.sort(key=lambda item: (item.char_start, item.structural_level, item.chunk_type != "heading"))
        return chunks
    return _fallback_segments(text, default_kind="reasoning", paragraph_class="case_excerpt")


def finalize_structural_chunks(chunks: List[StructuralChunk], chunk_ids_by_local_key: Dict[str, str]) -> List[StructuralChunk]:
    for idx, chunk in enumerate(chunks):
        if chunk.parent_local_key:
            chunk.parent_section_id = chunk_ids_by_local_key.get(chunk.parent_local_key)
        if idx > 0:
            chunk.prev_chunk_id = chunk_ids_by_local_key.get(f"__index__:{idx - 1}")
        if idx + 1 < len(chunks):
            chunk.next_chunk_id = chunk_ids_by_local_key.get(f"__index__:{idx + 1}")
    return chunks


def build_structural_chunks(
    *,
    doc_type: str,
    page_text: str,
) -> List[StructuralChunk]:
    normalized_doc_type = str(doc_type or "").strip().lower()
    if normalized_doc_type in {"law", "regulation", "enactment_notice"}:
        return _article_chunks_for_law_like(page_text)
    if normalized_doc_type == "case":
        return _extract_case_chunks(page_text)
    return _fallback_segments(_compact(page_text), default_kind="heading", paragraph_class="body")
