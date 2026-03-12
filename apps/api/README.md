# apps/api

FastAPI gateway and API layer for Legal Agentic RAG.

## Boundaries
- runtime endpoints (`/v1/qa/*`, `/v1/runs/*`)
- corpus endpoints (`/v1/corpus/*`)
- eval/gold/synth/config endpoint surfaces
- telemetry and health

See `apps/api/src/legal_rag_api/contracts.py` and `docs/product-specs/` for API contracts and behavior.

## Azure OpenAI (runtime LLM)

Runtime LLM calls are optional and gated by env variables. Recommended economical defaults:

- Docker stack: place the values in `infra/docker/.env` before rebuild/restart.
- Direct `uvicorn` run: export the same variables in the shell that starts the API.

- `AZURE_OPENAI_ENDPOINT` — endpoint, e.g. `https://your-resource.openai.azure.com`
- `AZURE_OPENAI_API_KEY` — key
- `AZURE_OPENAI_DEPLOYMENT` — model deployment name (default: `gpt-4o-mini`)
- `AZURE_OPENAI_API_VERSION` — Azure API version (default: `2024-02-15-preview`)
- `AZURE_OPENAI_MAX_TOKENS` — max completion tokens (default: `256`)
- `AZURE_OPENAI_TEMPERATURE` — default `0.0`
- `AZURE_OPENAI_TIMEOUT_SECONDS` — request timeout (default: `6`)
- `AZURE_OPENAI_TOP_P` — nucleus sampling (default: `1.0`)
- `AZURE_OPENAI_TRIES` — retries on transient failure (default: `1`)
- `AZURE_OPENAI_TOKEN_PARAMETER` — `max_tokens` by default, switch to `max_completion_tokens` for GPT-5 reasoning deployments
- `AZURE_OPENAI_REASONING_EFFORT` — optional reasoning budget, e.g. `minimal` for lower TTFT on GPT-5-mini

If any of `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` are missing, the API works in deterministic-only mode.

## Direct OpenAI (runtime LLM)

The same runtime client can also call OpenAI directly. Set `LLM_PROVIDER=openai` and configure:

- `OPENAI_API_KEY` — required
- `OPENAI_MODEL` — model id, for example `gpt-4.1-nano`
- `OPENAI_BASE_URL` — default `https://api.openai.com/v1`
- `OPENAI_MAX_TOKENS` — default `256`
- `OPENAI_TEMPERATURE` — default `0.0`
- `OPENAI_TIMEOUT_SECONDS` — default `6`
- `OPENAI_TOP_P` — default `1.0`
- `OPENAI_TRIES` — retries on transient failure (default: `1`)
- `OPENAI_TOKEN_PARAMETER` — `max_tokens` by default, switch to `max_completion_tokens` for reasoning models
- `OPENAI_REASONING_EFFORT` — optional, for example `minimal`
- `OPENAI_SERVICE_TIER` — optional OpenAI processing tier such as `flex` or `priority`

## OpenTelemetry (FastAPI)

- `OTEL_ENABLED` — include FastAPI server span instrumentation (default: `1`)
- `OTEL_TRACE_REQUIRED_FOR_COMPLETENESS` — mark `telemetry_complete=false` when request has no active OTel trace (default: `1` when OTel is active)
- `OTEL_SERVICE_NAME` — service name for OTel resource (default: `legal-agentic-rag-api`)
- `OTEL_SERVICE_NAMESPACE` — service namespace for OTel resource (default: `legal-rag`)
- `OTEL_FASTAPI_EXCLUDED_URLS` — comma-separated excluded routes (default: `/v1/health,/docs,/openapi.json`)
- `OTEL_CONSOLE_EXPORTER_ENABLED` — print spans to API stdout (default: `0`)
