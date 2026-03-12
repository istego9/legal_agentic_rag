from __future__ import annotations

import sys
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ingest import ingest as ingest_module  # noqa: E402


def test_ingest_zip_stub_does_not_create_placeholder_titles(tmp_path: Path, monkeypatch) -> None:
    zip_path = tmp_path / "pilot.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("c98c1475692bc22f4abab6a7a7d7969467c94e46a7e68919aaf127179ebf3f54.pdf", b"%PDF-1.4 fake")

    monkeypatch.setattr(
        ingest_module,
        "_extract_pdf_page_texts",
        lambda raw: (["TCD 001/2024 Claim No: TCD 001/2024 COURT OF FIRST INSTANCE - ORDERS"], 1, None),
    )
    monkeypatch.setattr(ingest_module, "_extract_preview_text", lambda raw: "")
    monkeypatch.setattr(ingest_module, "_materialize_source_pdf", lambda **kwargs: str(tmp_path / "source.pdf"))

    result = ingest_module.ingest_zip_stub(str(zip_path), "proj-1", "parser_only_v1", False)

    assert len(result["documents"]) == 1
    document = result["documents"][0]
    base = result["document_bases"][0]
    chunk_projection = result["chunk_search_documents"][0]
    assert document["title"] is None
    assert document["title_raw"] is None
    assert document["title_normalized"] is None
    assert base["title_raw"] is None
    assert base["short_title"] is None
    assert chunk_projection["title_normalized"] is None
    assert chunk_projection["short_title"] is None
