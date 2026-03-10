from __future__ import annotations

import importlib
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

from legal_rag_api.storage import InMemoryStore  # noqa: E402


def _reload_state_module() -> object:
    import legal_rag_api.state as state_module  # noqa: E402

    return importlib.reload(state_module)


@pytest.fixture(autouse=True)
def _reset_competition_mode_env() -> None:
    os.environ.pop("COMPETITION_MODE", None)
    _reload_state_module()
    try:
        yield
    finally:
        os.environ.pop("COMPETITION_MODE", None)
        _reload_state_module()


def test_state_defaults_to_inmemory_store_outside_competition_mode() -> None:
    state_module = _reload_state_module()
    assert state_module.competition_mode_enabled() is False
    assert isinstance(state_module.store, InMemoryStore)


def test_competition_mode_disables_inmemory_store_and_state_snapshot_api() -> None:
    os.environ["COMPETITION_MODE"] = "1"
    state_module = _reload_state_module()

    assert state_module.competition_mode_enabled() is True
    assert not isinstance(state_module.store, InMemoryStore)

    with pytest.raises(RuntimeError, match="COMPETITION_MODE=1"):
        _ = state_module.store.documents  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="COMPETITION_MODE=1"):
        state_module.load_persisted_state()
    with pytest.raises(RuntimeError, match="COMPETITION_MODE=1"):
        state_module.persist_state()


def test_state_snapshot_functions_delegate_to_state_pg_when_not_competition_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    state_module = _reload_state_module()

    captured: dict[str, object] = {}

    def _fake_load(store: object) -> bool:
        captured["load_store"] = store
        return True

    def _fake_save(store: object) -> None:
        captured["save_store"] = store

    monkeypatch.setattr(state_module.state_pg, "load_store", _fake_load)
    monkeypatch.setattr(state_module.state_pg, "save_store", _fake_save)

    assert state_module.load_persisted_state() is True
    state_module.persist_state()

    assert captured["load_store"] is state_module.store
    assert captured["save_store"] is state_module.store
