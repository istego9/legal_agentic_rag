from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal_rag_api import main as main_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_competition_mode_env() -> None:
    os.environ.pop("COMPETITION_MODE", None)
    try:
        yield
    finally:
        os.environ.pop("COMPETITION_MODE", None)


def test_startup_fails_closed_without_runtime_store_in_competition_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "enabled", lambda: False)
    monkeypatch.setattr(main_module.corpus_pg, "enabled", lambda: True)

    with pytest.raises(RuntimeError, match="runtime PostgreSQL backing store"):
        asyncio.run(main_module.startup_load_runtime_state())


def test_startup_fails_closed_without_corpus_store_in_competition_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "enabled", lambda: True)
    monkeypatch.setattr(main_module.corpus_pg, "enabled", lambda: False)

    with pytest.raises(RuntimeError, match="corpus PostgreSQL backing store"):
        asyncio.run(main_module.startup_load_runtime_state())


def test_startup_requires_postgres_schema_bootstrap_in_competition_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPETITION_MODE", "1")
    events: list[str] = []

    monkeypatch.setattr(main_module, "is_contest_safe_store", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "enabled", lambda: True)
    monkeypatch.setattr(main_module.corpus_pg, "enabled", lambda: True)
    monkeypatch.setattr(main_module.runtime_pg, "ensure_schema", lambda: events.append("runtime"))
    monkeypatch.setattr(main_module.corpus_pg, "ensure_schema", lambda: events.append("corpus"))
    monkeypatch.setattr(main_module, "load_persisted_state", lambda: (_ for _ in ()).throw(AssertionError("unexpected")))

    asyncio.run(main_module.startup_load_runtime_state())
    assert events == ["runtime", "corpus"]
