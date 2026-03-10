# 2026-03-10 Issue Seed List

## Issue 1 — Harden contest mode
**Title**
Contest mode must fail closed without persistent state

**Body**
- block in-memory state on contest path
- add startup/config failure when persistent backing store is unavailable
- add tests
- update active plan note

## Issue 2 — Make scorer the truth
**Title**
Add scorer truth pack and response contract regression

**Body**
- validate answer schema
- validate page source ids
- validate telemetry completeness
- validate no-answer contract
- add regression tests and readable summary

## Issue 3 — Label the public dataset
**Title**
Create public dataset taxonomy v1 and router benchmark

**Body**
- label all public questions
- add benchmark script
- write confusion report
- add validation test for full coverage

## Issue 4 — Harden article route
**Title**
Build article-lookup vertical slice with score-backed tests

**Body**
- choose 5–10 public article questions
- make route/retrieval/sources/normalization measurable
- add debug runbook

## Issue 5 — Harden single-case extraction
**Title**
Build single-case extraction vertical slice with case bundle fixtures

**Body**
- cover judges/parties/dates/outcomes/amounts
- use case judgment fixture bundle
- keep deterministic behavior where possible