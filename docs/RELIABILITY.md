# RELIABILITY.md

## SLO / бюджеты
Опишите бюджеты (пример):
- p95 latency основных эндпоинтов
- время старта сервиса
- error rate
- critical journeys (UI) — max span duration

## Непереговорные правила
- Любой новый критический путь → метрики + алерты.
- Любое ухудшение SLO → блокирует релиз (или требует explicit waiver).

## Canonical Chunk Model v1 (2026-03-05)
- Введён feature flag: `canonical_chunk_model_v1`.
- Введён canary rollout: `CANONICAL_CHUNK_MODEL_CANARY_PERCENT`.
- Введён rollback path:
  1) выключить feature flag,
  2) оставить legacy read path,
  3) отключить projection write path,
  4) применить down migration.
