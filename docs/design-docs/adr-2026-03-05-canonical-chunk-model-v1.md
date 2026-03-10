# ADR 2026-03-05: Two-Contour Data Model (Canonical + Chunk Projection)

## Status
Accepted

## Context
Нужен быстрый retrieval и фильтрация по legal corpus без постоянной зависимости от LLM.
Требуется сохранить page-level source semantics и additive compatibility с текущими API контрактами.

## Decision
1. Хранить каноническую модель документов в Postgres (`documents` + type-specific tables).
2. Хранить денормализованную проекцию чанков (`chunk_search_documents`) для поиска/фильтрации.
3. Ввести `RelationEdge` для lineage/history traversal.
4. Применить additive v1 к существующим `DocumentManifest` и `ParagraphChunk`:
   - required минимум не меняется;
   - новые поля только optional.
5. Формула поискового объекта:
   - `search_chunk = chunk_base + projected_doc_fields + type_specific_facet + lineage_fields + retrieval_fields`.

## Consequences
Плюсы:
1. Большинство factoid запросов решаются search/filter path.
2. Быстрее deterministic маршруты без heavy LLM planning.
3. Явная версия/lineage модель для historical queries.

Минусы:
1. Усложняется ingest mapping (dual-write + projection writer).
2. Появляется необходимость поддерживать синхронизацию canonical и projection слоёв.

## Scope boundaries
Изначально не входило в phase 1:
1. inferred relation edges,
2. confidence calibration,
3. weak supervision labels.

Обновление Phase 1 v3:
1. inferred relation edges и chunk-first ontology enrichment теперь входят в phase 1 как offline-only ingest enrichment path;
2. они не попадают напрямую в runtime retrieval semantics, пока не спроецированы в stable subset;
3. confidence calibration и weak supervision labels по-прежнему вне текущей фазы.

## Rollout
1. Feature flag `canonical_chunk_model_v1`.
2. Dual-write до стабилизации.
3. Контрактные и интеграционные регрессии обязательны перед merge.
