# AGENTS.md

## Mission
This repository contains the extracted Legal RAG backend and supporting artifacts.

Primary mission:

- operationally assemble and improve a competition-grade Legal Agentic RAG system for `agentic-challenge.ai`
- maximize contest score through fast iteration on ingest, retrieval, grounded runtime QA, eval, and experiments
- keep that iteration safe through explicit contracts, versioned policies, and reproducible validation

The target shape is explicit:

- ingest and canonical corpus
- retrieval and runtime QA
- evaluation and experiments
- gold and synthetic data workflows
- product web console
- shared contracts, schemas, and migrations

This repository excludes only the separate control-panel/workflow layer.

## Non-Negotiables
1. Start with the map:
   - `AGENTS.md`
   - `docs/ARCHITECTURE.md`
   - `docs/product-specs/`
   - `docs/design-docs/`
2. Do not guess boundary shapes.
   - validate inputs and outputs
   - keep shared contracts explicit
3. Do not change architecture casually.
   - preserve the main product scope
   - do not reintroduce workboard or wave-runner orchestration
4. Behavior changes require validation.
   - run `python scripts/agentfirst.py verify`
   - update docs when the source-of-truth changes

## System Of Record
- Architecture: `docs/ARCHITECTURE.md`
- Product specs: `docs/product-specs/`
- Active execution plans: `docs/exec-plans/active/`
- ADRs: `docs/design-docs/`
- Shared contracts: `apps/api/src/legal_rag_api/contracts.py`
- Public dataset contract anchor: `public_dataset.json`

## Repository Map
- `apps/api/`: FastAPI surface for corpus, QA, eval, experiments, gold, synth
- `apps/web/`: Vite + React + Mantine product console
- `services/`: ingest/runtime/eval/experiments/gold/synth logic
- `packages/`: retrieval, router, scorer, prompt helpers
- `db/`: migrations for canonical corpus and experiment data
- `schemas/`: JSON schemas mirrored by API/storage contracts
- `tests/`: contract, integration, and scorer regression coverage

## Explicitly Out Of Scope
- `apps/ops`
- `docs/workboard`
- wave-runner bridge / workboard orchestration
- separate control-panel workflow surface

## Validation
- Main entrypoint: `python scripts/agentfirst.py verify`
- API run: `PYTHONPATH=apps/api/src:. .venv/bin/uvicorn legal_rag_api.main:app --host 0.0.0.0 --port 8000`
- Docs-only changes may stop at the relevant docs/spec validation.
- Any completed task that changes runtime application behavior, UI, API, DB/migrations, prompts used by the running system, or deployment wiring must also rebuild the local Docker stack before reporting done:
  - `cd infra/docker && docker compose up --build -d`
  - verify direct API on `http://127.0.0.1:18000/docs`
  - verify direct web on `http://127.0.0.1:15188/`
  - verify merged local ingress on `http://127.0.0.1:18080/` and `http://127.0.0.1:18080/docs`
- Any deploy task must include rebuild of the target deployment runtime as part of deploy (use `--build` for Docker-based targets, or equivalent full rebuild for non-Docker targets) before reporting done.

## Deployment Surface
- Public host: `https://legal.build`
- Public API: `https://legal.build/v1/...`
- Public API docs: `https://legal.build/docs`
- Canonical public deployment address is always `https://legal.build`.
- Any other host/domain is local-only, temporary, or invalid and must not be reported as the deployed project.
- External reverse proxy source of truth: `infra/caddy/Caddyfile.legal.build`
- External Caddy target ports are fixed to:
  - API: `127.0.0.1:8000`
  - Web: `127.0.0.1:5173`
- Local Docker Caddy source of truth: `infra/docker/Caddyfile.local`
  - Container ingress: `:8080`
  - Host-published preview: `http://127.0.0.1:18080`
- Local Docker published ports from `infra/docker/docker-compose.yml`:
  - API canonical host binding for external/local-edge Caddy: `http://127.0.0.1:8000`
  - Web canonical host binding for external/local-edge Caddy: `http://127.0.0.1:5173`
  - API: `http://127.0.0.1:18000`
  - Web dev server: `http://127.0.0.1:15188`
- If the app is running on `8010` and `5176`, that is a local runtime mismatch, not a valid `legal.build` deployment.
- Do not report the project as deployed from local process checks alone; verify the public host separately.
- Deploy to `https://legal.build` is not complete without rebuild + public verification:
  - rebuild deployment target during deploy
  - verify `https://legal.build/`
  - verify `https://legal.build/docs`
- Caddy rollout prerequisites:
  - `legal.build` DNS must resolve to the Caddy host
  - ports `80` and `443` must be reachable for automatic TLS
  - run `caddy validate --config /etc/caddy/Caddyfile` before reload

## Skills
- `legal-rag-devops`: Use when the task involves deploy/runbook/domain/Caddy/DNS/TLS or checking whether `https://legal.build` is really live. Global Codex skill path: `$CODEX_HOME/skills/legal-rag-devops/SKILL.md`
- Local AgentFirst mirror: `.agentfirst/skills/devops_deploy.md`

## Definition Of Done
- scope stays inside the extracted RAG platform
- contracts remain compatible unless intentionally versioned
- tests/compile checks are green
- for any non-docs-only app task, `infra/docker` has been rebuilt and the known local Docker endpoints have been verified
- for any deploy task, target runtime has been rebuilt during deploy and public `https://legal.build` + `https://legal.build/docs` are verified
- docs are updated when behavior or boundaries change
