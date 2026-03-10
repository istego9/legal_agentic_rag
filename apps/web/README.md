# apps/web

Vite + React + Mantine UI for Legal Agentic RAG platform.

## Run

```bash
cd apps/web
npm install
npm run dev
```

Default UI URL: `http://127.0.0.1:5173`

Configure API URL with `VITE_API_BASE_URL`. If omitted, UI calls relative `/v1/*` paths and Vite proxy forwards to `http://127.0.0.1:8000`.

## Test

```bash
npm run test
```

E2E smoke support is maintained with the existing Vitest stack:

```bash
npm run test:e2e
```

Use the runbook in `/Users/artemgendler/dev/legal_agentic_rag/docs/web-console-e2e.md` for the manual/browser-backed flow. Any UI change that affects a critical operator journey should keep `test:e2e` green and extend the smoke when the journey changes materially.
