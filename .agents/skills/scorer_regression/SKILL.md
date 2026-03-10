---
name: scorer_regression
description: Use when changing scoring, telemetry validation, page-source selection, or output contract enforcement.
---

# Scorer Regression

## Goal
Make scoring the system-of-truth for all optimizations.

## Use this skill when
- touching `packages/scorers/`
- touching runtime output schemas
- touching telemetry, runs, eval endpoints

## Required rules
1. Every scoring change needs a regression fixture.
2. Validate answer schema, telemetry completeness, and page-source contract.
3. No scorer change ships without before/after notes.
4. No-answer behavior must be separately tested.

## Required checks
```bash
python scripts/agentfirst.py verify --strict
```

## Artifacts to update
- scorer regression tests
- `docs/exec-plans/active/score-deltas.md`
