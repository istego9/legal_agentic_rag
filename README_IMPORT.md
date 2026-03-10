# Import Guide

Copy these files into the repository root, preserving paths.

## Suggested destinations

- `docs/exec-plans/active/2026-03-10-detailed-next-steps-plan.md`
- `docs/exec-plans/active/2026-03-10-file-touch-map.md`
- `docs/exec-plans/active/2026-03-10-first-10-prs.md`
- `docs/exec-plans/active/codex-prompts/*.md`
- `.agents/skills/*/SKILL.md`

## Suggested commit order

### Commit 1
Add docs and Codex prompts only.

### Commit 2
Add `.agents/skills/` bundles.

### Commit 3+
Start implementing PR-01 using the prompt pack.

## Suggested issue creation order

1. PR-01 Contest mode hardening
2. PR-02 Scorer truth pack
3. PR-03 Public taxonomy + router benchmark
4. PR-04 Article vertical slice
5. PR-05 Single-case extraction vertical slice

## Suggested branch naming

- `hardening/contest-mode`
- `eval/scorer-truth-pack`
- `taxonomy/public-router-benchmark`
- `slice/article-lookup-v1`
- `slice/single-case-extraction-v1`

## Standard local checks

```bash
python scripts/agentfirst.py verify --strict
cd infra/docker && docker compose up --build -d
```