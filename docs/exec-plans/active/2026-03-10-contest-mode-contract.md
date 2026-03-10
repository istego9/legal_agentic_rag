# Contest Mode Contract (2026-03-10)

## Scope
- API startup contract for competition runtime hardening.
- Runtime state bootstrap contract in `apps/api/src/legal_rag_api/state.py` and `apps/api/src/legal_rag_api/main.py`.

## Contract
1. `COMPETITION_MODE=1` is treated as strict runtime mode for contest path.
2. In strict mode, in-memory state (`InMemoryStore`) is forbidden.
3. In strict mode, startup is fail-closed when PostgreSQL persistence is unavailable:
   - runtime backing store (`runtime_pg`) must be enabled
   - corpus backing store (`corpus_pg`) must be enabled
4. In strict mode, startup asserts contest-safe state binding (`state.store` must not be `InMemoryStore`).
5. In strict mode, legacy state snapshot helpers (`load_persisted_state` / `persist_state`) are disabled and raise configuration errors.

## Non-Competition Behavior
- Local/test mode keeps bootstrap ergonomics:
  - `InMemoryStore` remains available
  - state snapshot helpers delegate to `state_pg` when configured

## Tests
- Contract tests:
  - `tests/contracts/test_contest_mode_contracts.py`
  - `tests/contracts/test_contest_store_guard_access.py`
- Integration tests:
  - `tests/integration/test_competition_mode_startup.py`
  - `tests/integration/test_competition_mode_lifecycle.py`
