"""Shared mutable state for API process."""

from __future__ import annotations

from legal_rag_api.storage import InMemoryStore

store = InMemoryStore()


def load_persisted_state() -> bool:
    return False


def persist_state() -> None:
    return None
