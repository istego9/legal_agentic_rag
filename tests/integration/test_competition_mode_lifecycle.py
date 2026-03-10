from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import main as main_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_competition_env() -> None:
    os.environ.pop("COMPETITION_MODE", None)
    try:
        yield
    finally:
        os.environ.pop("COMPETITION_MODE", None)


def test_app_lifecycle_fails_startup_without_runtime_store_in_competition_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "enabled", lambda: False)
    monkeypatch.setattr(main_module.corpus_pg, "enabled", lambda: True)

    with pytest.raises(RuntimeError, match="runtime PostgreSQL backing store"):
        with TestClient(main_module.app):
            _ = "unreachable"


def test_app_lifecycle_fails_startup_for_stale_inmemory_binding_in_competition_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: False)

    with pytest.raises(RuntimeError, match="non-in-memory state binding"):
        with TestClient(main_module.app):
            _ = "unreachable"


def test_app_lifecycle_starts_in_competition_mode_with_safe_store_and_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "enabled", lambda: True)
    monkeypatch.setattr(main_module.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "ensure_schema", lambda: None)
    monkeypatch.setattr(main_module.corpus_pg, "ensure_schema", lambda: None)

    with TestClient(main_module.app) as client:
        response = client.get("/v1/health")
    assert response.status_code == 200
