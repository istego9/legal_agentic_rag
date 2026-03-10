# Skill: DevOps / Deploy

## Purpose
Зафиксировать source of truth для деплоя и не путать локальный запуск с адресом проекта.

## Source of Truth
- публичный адрес проекта: `https://legal.build`
- публичный API: `https://legal.build/v1/...`
- публичная документация API: `https://legal.build/docs`
- единственный валидный публичный адрес деплоя: `https://legal.build`
- внешний reverse proxy: `infra/caddy/Caddyfile.legal.build`
- внешний Caddy ожидает:
  - API на `127.0.0.1:8000`
  - web на `127.0.0.1:5173`
- локальный Docker Caddy: `infra/docker/Caddyfile.local`
  - внутренний ingress контейнера: `:8080`
  - хостовый preview: `http://127.0.0.1:18080`
- локальные опубликованные Docker-порты:
  - API: `http://127.0.0.1:18000`
  - web dev server: `http://127.0.0.1:15188`

## Action Items
- определить, речь идет о локальном запуске или о публичном деплое
- после любой завершенной задачи, которая меняла приложение, а не только документацию, обязательно пересобрать `infra/docker` перед отчетом о готовности
- проверить реальные слушающие порты и процессы
- проверить ответ API и web напрямую
- проверить локальные Docker endpoints на `18000`, `15188` и объединенный ingress на `18080`
- всегда отдельно проверять `https://legal.build/` и `https://legal.build/docs` и явно указывать статус в отчете
- если приложение запущено на `8010` и `5176`, зафиксировать mismatch с Caddy
- считать деплой успешным только после выравнивания портов или обновления proxy-конфига

## Checks
- `cd infra/docker && docker compose up --build -d`
- `cd infra/docker && docker compose ps`
- `lsof -nP -iTCP -sTCP:LISTEN | rg '(:18000|:15188|:18080|:8000|:5173|:8010|:5176|:8080|:80|:443)'`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/docs`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:15188/`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/docs`
- `ps aux | rg '(uvicorn|vite|caddy|legal_rag_api)'`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs`
- `curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/`
- `curl -sS -o /dev/null -w '%{http_code}' https://legal.build/`
- `curl -sS -o /dev/null -w '%{http_code}' https://legal.build/docs`

## Guardrails
- не говорить "проект задеплоен", если проверен только локальный процесс
- не смешивать локальные адреса `127.0.0.1:*` с публичным `https://legal.build`
- не считать никакой другой домен валидным публичным деплоем для этого проекта
- не пропускать публичные проверки `https://legal.build/` и `https://legal.build/docs` в финальном devops-отчете
- не считать проверку задачи полной без локальной Docker-пересборки, если менялось приложение, а не только документация
- mismatch `8000/5173` против `8010/5176` считать блокером релиза
- перед reload Caddy сначала делать validate
