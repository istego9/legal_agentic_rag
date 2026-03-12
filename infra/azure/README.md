# infra/azure

Azure deployment references for the extracted Legal Agentic RAG product.

## Required platform resources

- Azure OpenAI deployment for the general platform path
- Separate Azure OpenAI deployment for corpus metadata normalization is recommended
  when you want a GPT-5-family typed extraction path
  - recommended deployment name: `wf-gpt5mini-metadata`
- App runtime for API
- App runtime for Web

## Optional domain routing

Use:

- `infra/caddy/Caddyfile.legal.build`

## API environment variables

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_MAX_TOKENS`
- `AZURE_OPENAI_TEMPERATURE`
- `AZURE_OPENAI_TIMEOUT_SECONDS`
- `AZURE_OPENAI_TOP_P`
- `AZURE_OPENAI_TRIES`
- `AZURE_OPENAI_TOKEN_PARAMETER`
- `AZURE_OPENAI_REASONING_EFFORT`
- `CORPUS_METADATA_NORMALIZER_PROVIDER`
- `CORPUS_METADATA_NORMALIZER_DEPLOYMENT`
- `CORPUS_METADATA_NORMALIZER_MODEL`
- `CORPUS_METADATA_NORMALIZER_MAX_TOKENS`
- `CORPUS_METADATA_NORMALIZER_TIMEOUT_SECONDS`
- `CORPUS_METADATA_NORMALIZER_TOKEN_PARAMETER`
- `CORPUS_METADATA_NORMALIZER_REASONING_EFFORT`

## Local Docker quickstart

1. Copy `infra/docker/.env.example` to `infra/docker/.env`.
2. Fill in the Azure OpenAI deployment values.
3. Rebuild the stack:

```bash
cd infra/docker
docker compose up --build -d
```

4. Verify API docs on `http://127.0.0.1:18000/docs`.
