---
name: contest_mode_hardening
description: Use when changing runtime persistence, startup behavior, stub paths, or local-vs-contest execution semantics.
---

# Contest Mode Hardening

## Goal
Keep local bootstrap convenience paths out of the competition runtime.

## Use this skill when
- touching `state.py`, `state_pg.py`, `storage.py`, `runtime_pg.py`
- changing startup config
- changing ingest behavior in contest mode

## Required rules
1. `COMPETITION_MODE=1` must fail closed when persistence is unavailable.
2. `InMemoryStore` may stay for tests/local dev only.
3. Stub ingest or synthetic bootstrap may not be reachable from contest endpoints.
4. Add or update tests for startup and persistence behavior.
5. Do not add fallback answers or fallback storage.

## Required checks
```bash
python scripts/agentfirst.py verify --strict
```

## Output checklist
- changed files listed
- acceptance tests listed
- failure modes documented
