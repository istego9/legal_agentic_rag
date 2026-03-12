from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest.chunk_processing import build_structural_chunks, finalize_structural_chunks  # noqa: E402


def _finalize(chunks):
    mapping = {}
    ids = []
    for idx, chunk in enumerate(chunks):
        chunk_id = f"chunk-{idx}"
        ids.append(chunk_id)
        mapping[f"__index__:{idx}"] = chunk_id
        if chunk.local_key:
            mapping[chunk.local_key] = chunk_id
    return finalize_structural_chunks(chunks, mapping), ids


def test_law_chunker_splits_part_and_articles() -> None:
    text = (
        "EMPLOYMENT LAW 4 PART 2: HIRING EMPLOYEES "
        "11. No waiver (1) The requirements of this Law are minimum requirements. "
        "(2) Nothing in this Law precludes an Employer from providing more favourable terms. "
        "12. No false representations An Employer shall not induce a person by misrepresenting the position."
    )

    chunks = build_structural_chunks(doc_type="law", page_text=text)
    chunks, ids = _finalize(chunks)

    assert len(chunks) >= 3
    assert chunks[0].chunk_type == "heading"
    assert chunks[0].text.startswith("PART 2")
    article_chunks = [chunk for chunk in chunks if chunk.article_number]
    assert [chunk.article_number for chunk in article_chunks[:2]] == ["11", "12"]
    assert article_chunks[0].article_title == "No waiver"
    assert article_chunks[0].part_ref == "2"
    assert article_chunks[0].parent_section_id == ids[0]
    assert article_chunks[0].next_chunk_id is not None
    assert article_chunks[1].prev_chunk_id is not None


def test_law_chunker_does_not_turn_body_phrase_into_fake_part_heading() -> None:
    text = (
        "PART 2: HIRING EMPLOYEES 11. No waiver "
        "Nothing in this Law precludes an Employee from waiving rights by written agreement "
        "as part in a settlement agreement with the Employer. "
        "12. No false representations An Employer shall not induce a person by misrepresenting the position."
    )

    chunks = build_structural_chunks(doc_type="law", page_text=text)
    heading_texts = [chunk.text for chunk in chunks if chunk.chunk_type == "heading"]

    assert "PART 2: HIRING EMPLOYEES" in heading_texts
    assert all(text.lower() != "part in" for text in heading_texts)
    article_chunks = [chunk for chunk in chunks if chunk.article_number]
    assert [chunk.article_number for chunk in article_chunks[:2]] == ["11", "12"]


def test_case_chunker_splits_order_and_reasons() -> None:
    text = (
        "CFI 067/2025 Coinmena B.S.C. (C) v Foloosi Technologies Ltd "
        "Claim No: CFI 067/2025 BETWEEN COINMENA Claimant and FOLOOSI Defendant "
        "ORDER WITH REASONS OF H.E. JUSTICE X UPON the Defendant's Application "
        "IT IS HEREBY ORDERED THAT: 1. The Applicant shall pay USD 155,879.50. "
        "2. The Applicant shall pay within 14 days. "
        "SCHEDULE OF REASONS 1. This Order concerns costs. 2. Interest shall accrue at 9% per annum."
    )

    chunks = build_structural_chunks(doc_type="case", page_text=text)
    chunks, _ = _finalize(chunks)

    assert any(chunk.section_kind_case == "parties" for chunk in chunks)
    assert any(chunk.section_kind_case == "order" and chunk.chunk_type == "list_item" for chunk in chunks)
    assert any(chunk.section_kind_case == "reasoning" and chunk.chunk_type == "list_item" for chunk in chunks)
    assert all(chunk.char_end >= chunk.char_start for chunk in chunks)
