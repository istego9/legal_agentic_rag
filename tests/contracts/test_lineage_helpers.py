from __future__ import annotations

import io
import sys
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest import ingest as ingest_module  # noqa: E402
from services.runtime.lineage import (  # noqa: E402
    filter_relation_edges,
    find_commencement_notices,
    resolve_current_document_version,
    supersession_chain,
)


def _lineage_fixture_pack() -> dict[str, dict[str, object]]:
    return {
        "law-v1": {
            "document_id": "law-v1",
            "version_group_id": "law-10",
            "version_sequence": 1,
            "is_current_version": False,
            "effective_start_date": "2019-01-01",
            "superseded_by_doc_id": "law-v2-a",
        },
        "law-v2-a": {
            "document_id": "law-v2-a",
            "version_group_id": "law-10",
            "version_sequence": 2,
            "is_current_version": True,
            "effective_start_date": "2021-01-01",
            "superseded_by_doc_id": "law-v2-b",
        },
        "law-v2-b": {
            "document_id": "law-v2-b",
            "version_group_id": "law-10",
            "version_sequence": 2,
            "is_current_version": True,
            "effective_start_date": "2021-06-01",
            "superseded_by_doc_id": None,
            "duplicate_group_id": "law-v2-a",
        },
    }


def _build_duplicate_version_zip(path: Path) -> Path:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("law_no_10_effective_from_2019-01-01_until_2020-12-31.pdf", b"LAW_V1")
        zf.writestr("law_no_10_effective_from_2021-01-01.pdf", b"LAW_V2")
        zf.writestr("law_no_10_effective_from_2021-01-01_duplicate.pdf", b"LAW_V2")
        zf.writestr("law_no_11_low_quality_scan.pdf", b"LOW_SCAN")
    path.write_bytes(payload.getvalue())
    return path


def test_resolve_current_document_version_prefers_current_flag_with_deterministic_tiebreak() -> None:
    docs = _lineage_fixture_pack()
    resolved = resolve_current_document_version("law-v1", docs)
    assert resolved is not None
    assert resolved["document_id"] == "law-v2-b"


def test_resolve_current_document_version_falls_back_to_latest_sequence_when_flags_missing() -> None:
    docs = _lineage_fixture_pack()
    docs["law-v2-a"]["is_current_version"] = False
    docs["law-v2-b"]["is_current_version"] = False
    docs["law-v3"] = {
        "document_id": "law-v3",
        "version_group_id": "law-10",
        "version_sequence": 3,
        "is_current_version": False,
        "effective_start_date": "2022-01-01",
    }
    resolved = resolve_current_document_version("law-v1", docs)
    assert resolved is not None
    assert resolved["document_id"] == "law-v3"


def test_resolve_current_document_version_without_group_returns_base_document() -> None:
    docs = {"doc": {"document_id": "doc", "version_sequence": 7, "is_current_version": False}}
    resolved = resolve_current_document_version("doc", docs)
    assert resolved is not None
    assert resolved["document_id"] == "doc"


def test_supersession_chain_walks_to_latest() -> None:
    docs = _lineage_fixture_pack()
    assert supersession_chain("law-v1", docs) == ["law-v1", "law-v2-a", "law-v2-b"]


def test_supersession_chain_stops_on_cycle() -> None:
    docs = {
        "doc-a": {"document_id": "doc-a", "superseded_by_doc_id": "doc-b"},
        "doc-b": {"document_id": "doc-b", "superseded_by_doc_id": "doc-a"},
    }
    assert supersession_chain("doc-a", docs) == ["doc-a", "doc-b"]


def test_find_commencement_notices_orders_by_date() -> None:
    notices = [
        {"document_id": "n2", "target_doc_id": "law-1", "commencement_date": "2020-01-10"},
        {"document_id": "n1", "target_doc_id": "law-1", "commencement_date": "2019-01-10"},
        {"document_id": "n3", "target_doc_id": "law-2", "commencement_date": "2018-01-10"},
    ]
    matched = find_commencement_notices("law-1", notices)
    assert [row["document_id"] for row in matched] == ["n1", "n2"]


def test_filter_relation_edges_by_source_target_and_type() -> None:
    edges = [
        {"source_object_id": "a", "target_object_id": "b", "edge_type": "refers_to"},
        {"source_object_id": "a", "target_object_id": "c", "edge_type": "cites"},
        {"source_object_id": "x", "target_object_id": "b", "edge_type": "refers_to"},
    ]
    filtered = filter_relation_edges(edges, source_object_id="a", edge_type="refers_to")
    assert len(filtered) == 1
    assert filtered[0]["target_object_id"] == "b"


def test_sanitize_preview_text_repairs_split_caps_words_and_dedupes_heading_lines() -> None:
    raw_text = (
        "THE DU BAI INTERNATIONAL FINANCIAL CENTRE COU RTS\n"
        "THE DU BAI INTERNATIONAL FINANCIAL CENTRE COU RTS\n"
        "COU RT OF APPEAL\n"
        "ORDER W ITH REAS ONS OF H.E. CHIEF J U S TICE W AYNE M ARTIN U PON\n"
        "Case No: ENF 269/2023"
    )

    cleaned = ingest_module._sanitize_preview_text(raw_text)

    assert cleaned.count("DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS") == 1
    assert "COURT OF APPEAL" in cleaned
    assert "ORDER WITH REASONS" in cleaned
    assert "CHIEF JUSTICE WAYNE MARTIN UPON" in cleaned
    assert "Case No: ENF 269/2023" in cleaned
    assert "DU BAI" not in cleaned
    assert "COU RTS" not in cleaned
    assert "W ITH" not in cleaned
    assert "J U S TICE" not in cleaned


def test_extract_law_number_prefers_explicit_instrument_number_over_jurisdiction_token() -> None:
    sample = "FOUNDATIONS LAW DIFC LAW NO.3 OF 2018 Consolidated Version No. 3 (March 2024)"
    assert ingest_module._extract_law_number(sample) == "3"


def test_extract_law_number_does_not_treat_generic_claim_no_as_law_number() -> None:
    sample = "Claim No. DEC 001/2025 IN THE DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS"
    assert ingest_module._extract_law_number(sample) is None


def test_extract_case_id_handles_colon_claim_and_hyphenated_identifiers() -> None:
    assert ingest_module._extract_case_id("Case No: CA 004/2025 THE DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS") == "CA 004/2025"
    assert ingest_module._extract_case_id("Claim No. DEC 001/2025 IN THE DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS") == "DEC 001/2025"
    assert ingest_module._extract_case_id("Permission application in CFI-016-2025/3 before the court") == "CFI-016-2025/3"


def test_resolve_version_group_id_uses_legislative_title_anchor_when_available() -> None:
    assert ingest_module._resolve_version_group_id(
        doc_type="law",
        law_number="2",
        case_id=None,
        pdf_id="doc-a",
        summary_text="EMPLOYMENT LAW DIFC LAW NO. 2 of 2019 Consolidated Version No. 5",
    ) == "law:employment:2"
    assert ingest_module._resolve_version_group_id(
        doc_type="law",
        law_number="2",
        case_id=None,
        pdf_id="doc-b",
        summary_text="COMMON REPORTING STANDARD LAW DIFC LAW NO. 2 OF 2018 Consolidated Version No.2",
    ) == "law:common_reporting_standard:2"


def test_case_ingest_uses_strong_case_ids_and_skips_legislative_temporal_semantics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_extract_pdf_page_texts(raw: bytes) -> tuple[list[str], int, str | None]:
        marker = raw.decode("utf-8")
        if marker == "CASE_ORDER":
            return (
                [
                    (
                        "DEC 001/2025 COURT OF APPEAL - ORDERS Claim No. DEC 001/2025 "
                        "IN THE DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS. "
                        "The shareholder relationship lasted until 2022."
                    )
                ],
                1,
                None,
            )
        return (
            [
                (
                    "DEC 001/2025 DIGITAL ECONOMY COURT - JUDGMENTS Claim No. DEC 001/2025 "
                    "IN THE DUBAI INTERNATIONAL FINANCIAL CENTRE COURTS. "
                    "Article 13 of the Court Law 2004 has been superseded by the Court Law 2025."
                )
            ],
            1,
            None,
        )

    monkeypatch.setattr(ingest_module, "_extract_pdf_page_texts", fake_extract_pdf_page_texts)

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("dec_case_order.pdf", b"CASE_ORDER")
        zf.writestr("dec_case_judgment.pdf", b"CASE_JUDGMENT")
    zip_path = tmp_path / "case-fixture-pack.zip"
    zip_path.write_bytes(payload.getvalue())

    result = ingest_module.ingest_zip_stub(
        blob_url=str(zip_path),
        project_id="wb-in-002",
        parse_policy="balanced",
        dedupe_enabled=True,
    )
    docs_by_pdf = {row["pdf_id"]: row for row in result["documents"]}

    order_doc = docs_by_pdf["dec_case_order"]
    judgment_doc = docs_by_pdf["dec_case_judgment"]

    assert order_doc["case_id"] == "DEC 001/2025"
    assert judgment_doc["case_id"] == "DEC 001/2025"
    assert order_doc["version_group_id"] == "case:dec_001_2025"
    assert judgment_doc["version_group_id"] == "case:dec_001_2025"
    assert order_doc["version_sequence"] == 0
    assert judgment_doc["version_sequence"] == 0
    assert order_doc["effective_end_date"] is None
    assert judgment_doc["effective_end_date"] is None
    assert order_doc["is_current_version"] is True
    assert judgment_doc["is_current_version"] is True


def test_ingest_fixture_pack_covers_duplicate_grouping_and_parse_quality_expectations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_extract_pdf_page_texts(raw: bytes) -> tuple[list[str], int, str | None]:
        marker = raw.decode("utf-8")
        if marker == "LAW_V1":
            return (
                [
                    (
                        "Law no 10 effective from 2019-01-01 until 2020-12-31 "
                        "article 1 employer obligations in force until repeal."
                    )
                ],
                1,
                None,
            )
        if marker == "LAW_V2":
            return (
                [
                    (
                        "Law no 10 effective from 2021-01-01 article 1 employer obligations "
                        "and legal duties currently in force."
                    )
                ],
                1,
                None,
            )
        return (["low quality marker scanned text"], 1, "pdf_parse_failed")

    def fake_is_low_quality_text(text: str) -> bool:
        return "low quality marker" in text.lower()

    monkeypatch.setattr(ingest_module, "_extract_pdf_page_texts", fake_extract_pdf_page_texts)
    monkeypatch.setattr(ingest_module, "_is_low_quality_text", fake_is_low_quality_text)

    zip_path = _build_duplicate_version_zip(tmp_path / "duplicate-version-fixture-pack.zip")
    result = ingest_module.ingest_zip_stub(
        blob_url=str(zip_path),
        project_id="wb-in-002",
        parse_policy="balanced",
        dedupe_enabled=True,
    )
    diagnostics = ingest_module.build_ingest_diagnostics(result)

    docs_by_pdf = {row["pdf_id"]: row for row in result["documents"]}

    duplicate_anchor = docs_by_pdf["law_no_10_effective_from_2021-01-01"]["canonical_doc_id"]
    duplicate_copy = docs_by_pdf["law_no_10_effective_from_2021-01-01_duplicate"]
    low_quality_doc = docs_by_pdf["law_no_11_low_quality_scan"]

    assert duplicate_copy["duplicate_group_id"] == duplicate_anchor
    assert docs_by_pdf["law_no_10_effective_from_2021-01-01"]["duplicate_group_id"] is None
    assert low_quality_doc["processing"]["parse_warning"] == "low_text_quality"
    assert low_quality_doc["processing"]["parse_error"] == "pdf_parse_failed"
    assert docs_by_pdf["law_no_10_effective_from_2019-01-01_until_2020-12-31"]["processing"]["parse_warning"] is None

    assert diagnostics["summary"]["duplicate_documents"] == 1
    assert diagnostics["summary"]["parse_warnings"] == 1
    assert diagnostics["summary"]["parse_errors"] == 1
    assert docs_by_pdf["law_no_10_effective_from_2019-01-01_until_2020-12-31"]["version_group_id"] == "law:10"
    assert docs_by_pdf["law_no_10_effective_from_2021-01-01"]["version_group_id"] == "law:10"
    assert docs_by_pdf["law_no_10_effective_from_2021-01-01"]["version_sequence"] == 2
    assert docs_by_pdf["law_no_11_low_quality_scan"]["version_group_id"] == "law:11"
    assert docs_by_pdf["law_no_10_effective_from_2021-01-01"]["processing"]["processing_profile_version"] == "parser_only_v1"
    assert Path(docs_by_pdf["law_no_10_effective_from_2021-01-01"]["processing"]["source_pdf_path"]).exists()
