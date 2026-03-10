from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "db" / "migrations"
UP = MIGRATIONS_DIR / "20260309_211000_case_judgment_extraction_v1.up.sql"
DOWN = MIGRATIONS_DIR / "20260309_211000_case_judgment_extraction_v1.down.sql"


def test_case_judgment_migration_files_exist() -> None:
    assert UP.exists(), f"missing migration file: {UP}"
    assert DOWN.exists(), f"missing migration file: {DOWN}"


def test_case_judgment_migration_has_required_tables_and_indexes() -> None:
    sql = UP.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS case_extraction_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS case_document_extractions" in sql
    assert "CREATE TABLE IF NOT EXISTS case_chunk_extractions" in sql
    assert "CREATE TABLE IF NOT EXISTS case_extraction_qc_results" in sql

    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_case_document_active_by_schema" in sql
    assert "USING GIN (payload)" in sql
    assert "USING GIN (metadata)" in sql

    assert "REFERENCES case_extraction_runs(run_id)" in sql
    assert "REFERENCES case_document_extractions(document_extraction_id)" in sql


def test_case_judgment_migration_down_reverses_tables() -> None:
    sql = DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS case_extraction_qc_results" in sql
    assert "DROP TABLE IF EXISTS case_chunk_extractions" in sql
    assert "DROP TABLE IF EXISTS case_document_extractions" in sql
    assert "DROP TABLE IF EXISTS case_extraction_runs" in sql
