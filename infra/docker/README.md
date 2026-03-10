# infra/docker

Local dockerized stack for API + product Web + Postgres + Caddy.

## Files

- `docker-compose.yml`
- `Caddyfile.local`

## Start

```bash
cd infra/docker
docker compose up --build -d
```

If interactive logs are needed, omit `-d`.

## Required After App-Affecting Tasks

Any completed task that changes runtime application behavior, UI, API, DB wiring, or deployment wiring must rebuild this stack before being reported as done.

```bash
cd infra/docker
docker compose up --build -d
docker compose ps
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18000/docs
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:15188/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/docs
```

Endpoints:

- API canonical host binding (for external/local-edge Caddy): `http://127.0.0.1:8000`
- Web canonical host binding (for external/local-edge Caddy): `http://127.0.0.1:5173`
- API (container published): `http://127.0.0.1:18000`
- Product dev server (direct): `http://127.0.0.1:15188`
- Product preview (via Caddy): `http://127.0.0.1:18080`
- Postgres: `127.0.0.1:15432`
