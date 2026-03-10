"""Shared mutable state for API process."""

from __future__ import annotations

import os

from legal_rag_api import state_pg
from legal_rag_api.storage import InMemoryStore


def competition_mode_enabled() -> bool:
    raw = os.getenv("COMPETITION_MODE", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class _ContestStoreGuard:
    _ERROR = (
        "In-memory store is disabled when COMPETITION_MODE=1. "
        "Use PostgreSQL-backed adapters (runtime_pg/corpus_pg) instead."
    )

    def __getattr__(self, name: str) -> None:
        raise RuntimeError(self._ERROR)

    def __setattr__(self, name: str, value: object) -> None:
        raise RuntimeError(self._ERROR)


store = _ContestStoreGuard() if competition_mode_enabled() else InMemoryStore()


def is_contest_safe_store() -> bool:
    if not competition_mode_enabled():
        return True
    return not isinstance(store, InMemoryStore)


def load_persisted_state() -> bool:
    if competition_mode_enabled():
        raise RuntimeError(
            "State snapshot loading is disabled when COMPETITION_MODE=1. "
            "Contest runtime must use persistent PostgreSQL storage only."
        )
    return state_pg.load_store(store)


def persist_state() -> None:
    if competition_mode_enabled():
        raise RuntimeError(
            "State snapshot persistence is disabled when COMPETITION_MODE=1. "
            "Contest runtime must use persistent PostgreSQL storage only."
        )
    state_pg.save_store(store)
