# Product Spec: Ingest and Corpus Canonicalization

## 0) Goal / Purpose
- Создать детерминированный pipeline, который превращает ZIP/PDF corpus в canonical documents/pages/paragraphs с корректным lineage и stable source identity.
- Цель модуля: дать runtime и gold/eval надежный корпус, а не "приблизительный набор текстов".
- Импортированный corpus является shared asset платформы и не должен требовать project binding для загрузки или canonical identity.
- Агент может менять parser strategy, OCR fallback, quality heuristics и metadata extraction, если published corpus contracts и canonical IDs сохраняются.
- Phase 1 v3 уточнение:
  - ingest остается parser-only;
  - после ingest автоматически запускается offline agentic enrichment;
  - ontology и relation graph строятся chunk-first и проектируются в stable retrieval subset без online runtime dependency.

## 1) Problem / Job-to-be-done
- Конкурс зависит от корректного page grounding.
- В корпусе ожидаются duplicate files, versioned laws и низкокачественные PDF.
- Ошибки ingest ломают сразу retrieval, source export и no-answer behavior.

## 2) Contracts / Boundaries
### Publishes
- `DocumentManifest`
- page artifacts with stable `source_page_id`
- paragraph artifacts for retrieval
- lineage/version metadata
- parse quality diagnostics
- enrichment jobs
- ontology registry entries
- chunk ontology assertions
- document ontology views

### Consumes
- Global policy/config versions.
- Shared document/page/paragraph contract names.

### Forbidden changes
- Генерировать нестабильные page ids.
- Привязывать canonical corpus import к project scope.
- Скрывать low-quality parse failures.
- Смешивать paragraph identity и page identity.
- Делать OCR silent default path.
- Подменять review/runtime retrieval candidate-only ontology labels до promotion в stable subset.

## 3) Success criteria (acceptance)
- [ ] Один и тот же ZIP дает детерминированный canonical corpus.
- [ ] Duplicate files correctly grouped.
- [ ] Latest/current version preference вычисляется воспроизводимо.
- [ ] Плохие документы видны через diagnostics, а не silently pass.

## 4) Non-goals
- Не отвечать на вопросы.
- Не считать contest score.
- Не выбирать финальные sources для ответа.

## 5) UX notes
- UI должен видеть parse quality, duplicates, lineage и per-document diagnostics.
- UI import path не должен требовать project selection для загрузки ZIP в corpus.

## 6) Data / Telemetry
- Нужны поля:
  - parser version
  - OCR used
  - extraction confidence
  - duplicate group
  - version group
  - current version marker
  - parse warning/error

## 7) Risk & Autonomy
- Риск: high
- Автономность: L3
- Human judgment:
  - правила определения current version в неоднозначных случаях
  - policy на OCR fallback

## 8) Action items
- [ ] Довести PDF parser path до production-like baseline.
- [ ] Не добавлять OCR в Phase 1; держать parser-only path explicit.
- [x] Убрать обязательную project binding из corpus import path.
- [ ] Реализовать duplicate and version grouping.
- [ ] Перевести version grouping в family bucket + relation graph модель без ложного linear supersession.
- [ ] Зафиксировать deterministic ingest command для private-set window.
- [ ] Добавить diagnostics отчет по parse quality и broken files.
- [ ] Ввести auto-run offline agentic enrichment после ingest.
- [ ] Собирать dynamic ontology в candidate layer и stable projected subset для retrieval.

## 9) Validation plan
- Ingest regression fixtures:
  - duplicate pdf
  - same law multiple editions
  - low-quality page
  - broken pdf
- Contract tests на documents/pages/paragraphs.
- Determinism check: repeated ingest same input -> same exported identities.
