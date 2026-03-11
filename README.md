# Legal Agentic RAG

Extraction of the main Legal RAG product from `/Users/artemgendler/dev/legal-arag`.

Mission: build and harden a competition-grade Legal Agentic RAG system for `agentic-challenge.ai`, optimized for fast iteration and measurable gains in contest score.

Included here:

- Corpus ingest and canonicalization
- Retrieval and typed runtime QA
- Evaluation and experiments
- Gold and synthetic dataset workflows
- Product web console (`apps/web`)
- Shared contracts, schemas, migrations, and tests

Intentionally excluded:

- Separate control-panel / workflow stack
- `apps/ops`
- Workboard and wave-runner orchestration surface

## Quick Start

1. Create Python environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install fastapi uvicorn pydantic httpx opentelemetry-sdk opentelemetry-instrumentation-fastapi pytest pyyaml python-multipart pypdf psycopg[binary]
```

2. Run API:

```bash
PYTHONPATH=apps/api/src:. .venv/bin/uvicorn legal_rag_api.main:app --host 0.0.0.0 --port 8000
```

3. Run Web:

```bash
cd apps/web
npm install
npm run dev
```

4. Check:

- `http://127.0.0.1:8000/v1/health`
- `http://127.0.0.1:5173`

## Validation

```bash
.venv/bin/python scripts/agentfirst.py verify
```

This runs:

- Python compile checks
- Contract and integration tests for the RAG backend
- Web unit tests
- Web build

## Offline Competition Batch Runner

Run local/offline dataset bundles end-to-end and emit official starter-kit `submission.json` artifacts.

Prepare corpus from local documents bundle:

```bash
.venv/bin/python scripts/competition_batch.py prepare \
  --documents datasets/official_fetch_2026-03-11/documents.zip \
  --output reports/competition_runs/prepare_report.json
```

Run local batch inference and export official submission:

```bash
.venv/bin/python scripts/competition_batch.py run \
  --questions datasets/official_fetch_2026-03-11/questions.json \
  --output reports/competition_runs/dev_smoke \
  --limit 10
```

Validate already-produced submission artifact without rerun:

```bash
.venv/bin/python scripts/competition_batch.py validate \
  --submission reports/competition_runs/dev_smoke/submission.json
```

Run artifacts:

- `submission.json` (official starter-kit shape)
- `run_manifest.json` (machine-readable run metadata and validation status)
- `question_status.jsonl` (per-question status/route/contract snapshot)
- `preflight_report.json` (strict contract preflight)
- `submission.validation_report.json` (official submission semantics validation)
- `run_summary.md` (human-readable summary)

## Docker

Minimal local product stack:

```bash
cd infra/docker
docker compose up --build
```

Endpoints:

- API: `http://127.0.0.1:18000`
- Web: `http://127.0.0.1:15188`
- Caddy entrypoint: `http://127.0.0.1:18080`
- Postgres: `127.0.0.1:15432`

## Azure LLM

Set only when needed. Otherwise the deterministic runtime path stays active.

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_MAX_TOKENS`
- `AZURE_OPENAI_TEMPERATURE`
- `AZURE_OPENAI_TIMEOUT_SECONDS`
- `AZURE_OPENAI_TOP_P`
- `AZURE_OPENAI_TRIES`

## OpenTelemetry

FastAPI OTel instrumentation is enabled by default when dependencies are installed.

- `OTEL_ENABLED=1`
- `OTEL_TRACE_REQUIRED_FOR_COMPLETENESS=1`
