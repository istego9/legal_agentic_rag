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
def _reset_competition_env() -> None:
    os.environ.pop("COMPETITION_MODE", None)
    _reload_state_module()
    try:
        yield
    finally:
        os.environ.pop("COMPETITION_MODE", None)
        _reload_state_module()


def test_contest_store_guard_blocks_direct_read_and_write() -> None:
    os.environ["COMPETITION_MODE"] = "1"
    state_module = _reload_state_module()

    with pytest.raises(RuntimeError, match="In-memory store is disabled"):
        _ = state_module.store.documents  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="In-memory store is disabled"):
        state_module.store.documents = {}  # type: ignore[attr-defined]


def test_contest_safe_store_check_rejects_stale_inmemory_binding() -> None:
    os.environ["COMPETITION_MODE"] = "1"
    state_module = _reload_state_module()

    assert state_module.is_contest_safe_store() is True
    state_module.store = InMemoryStore()
    assert state_module.is_contest_safe_store() is False
