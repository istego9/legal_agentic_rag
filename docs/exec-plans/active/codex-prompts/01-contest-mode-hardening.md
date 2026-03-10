# Codex Prompt 01 — Contest Mode Hardening

You are working inside the `legal_agentic_rag` repository.

## Objective
Harden the contest runtime so that local bootstrap conveniences cannot leak into the competition path.

## Repository context
- The repo already contains FastAPI wiring under `apps/api/src/legal_rag_api/`.
- Current risk: `state.py` still defaults to an in-memory store and does not load persisted state.
- The competition path must fail closed, not silently degrade.

## Scope
Touch only the minimum files needed to:
1. introduce or honor `COMPETITION_MODE=1`
2. forbid `InMemoryStore` on contest path
3. make missing persistent backing store a startup/config error on contest path
4. add tests that prove the behavior

## Files to inspect first
- `AGENTS.md`
- `apps/api/src/legal_rag_api/state.py`
- `apps/api/src/legal_rag_api/state_pg.py`
- `apps/api/src/legal_rag_api/storage.py`
- `apps/api/src/legal_rag_api/main.py`
- `tests/contracts/`
- `tests/integration/`

## Constraints
- Do not redesign architecture.
- Do not add generic fallback behavior.
- Keep local/test mode working.
- If a persistent adapter already exists, wire it instead of inventing a new one.
- Update docs only if behavior changes.

## Deliverables
- code changes
- tests
- short note in `docs/exec-plans/active/` describing the new contest-mode contract

## Acceptance criteria
- Starting with `COMPETITION_MODE=1` and no persistent backing store fails fast.
- Verify command passes.
- No changed path contains TODO/pass/NotImplemented.

## Commands
```bash
python scripts/agentfirst.py verify --strict
```