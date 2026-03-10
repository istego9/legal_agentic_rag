from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.case_judgment_bundle_validation import (  # noqa: E402
    FIXTURE_DIR,
    SCHEMA_DIR,
    SCHEMA_FILES,
    load_bundle_mirror,
    validate_case_judgment_bundle_mirror,
)


def test_bundle_mirror_files_exist() -> None:
    assert SCHEMA_DIR.exists()
    assert FIXTURE_DIR.exists()
    for name in SCHEMA_FILES:
        assert (SCHEMA_DIR / name).exists()


def test_bundle_mirror_is_valid_against_source_schemas() -> None:
    errors = validate_case_judgment_bundle_mirror()
    assert not errors


def test_section_map_fixture_matches_document_section_map() -> None:
    _, fixtures = load_bundle_mirror()
    document = fixtures["enf_269_2023_full_judgment_document_example.json"]
    section_map = fixtures["enf_269_2023_section_map.json"]
    assert section_map == document.get("section_map")

