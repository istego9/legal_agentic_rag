# infra/azure

Azure deployment references for the extracted Legal Agentic RAG product.

## Required platform resources

- Azure OpenAI deployment (`gpt-4o-mini` recommended for budget)
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
