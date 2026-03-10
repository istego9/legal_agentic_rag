# Bundle: ARB-016-2023 case cluster / full-judgment taxonomy / workflows

## Что это
Этот bundle делает две вещи:

1. **Моделирует сложный case cluster вокруг `ARB-016-2023`**, где прямой root-order `ARB-016-2023`
   во время исследования не был найден в публичном листинге DIFC и не был явно выделен как отдельный
   файл в твоём запросе.
2. Даёт **полную taxonomy full judgment / order with reasons** на **реальном доступном сложном документе**
   из того же кластера: `ENF 269/2023`, который прямо ссылается на `ARB-016-2023`, Partial Award
   от `10 March 2023`, Final Award от `21 June 2023`, Arbitration Claim Form от `17 August 2023`
   и amended recognition order от `6 September 2023` / re-issued `27 September 2023`.

Иными словами: для `ARB-016-2023` мы строим **case cluster model**, а для детальной
`full judgment`-модели используем **доступный anchor-document** `ENF 269/2023`.

## Что внутри
- `docs/arb016_case_cluster_profile.md` — profile всего кластера
- `docs/full_judgment_case_taxonomy_v1.md` — taxonomy для длинных judgment/order-with-reasons документов
- `docs/full_judgment_parsing_rules_v1.md` — правила парсинга
- `docs/hq21_workflow_fit_assumptions.md` — допущения по HQ21 workflow runtime
- `docs/workflow_dsl_spec.md` — DSL для workflow-файлов
- `schemas/*.json` — JSON Schemas
- `examples/*.json` — заполненные примеры
- `workflows/*.yaml` — детальные workflows
- `diagrams/*.mmd` — Mermaid-диаграммы
- `sources_and_limitations.md` — ограничения и ссылки на источники

## Ключевое ограничение
Прямой текст root-order `ARB-016-2023` в публично доступном DIFC arbitration listing,
который был доступен во время исследования, не был найден. Поэтому bundle честно
строится вокруг **публично доступного и загруженного complex downstream document**
`ENF 269/2023`, который ссылается на `ARB-016-2023` и позволяет восстановить case-cluster.

## Как использовать
1. Возьми `schemas/` как контракт данных.
2. Возьми `examples/` как ground truth для одного сложного кейса.
3. Возьми `workflows/` как спецификацию orchestration.
4. Если runtime HQ21 поддерживает stateful node/edge workflows, conditional branching,
   HTTP/tool nodes, retries и persisted state — эти YAML можно маппить почти напрямую.
   Если нет, DSL всё равно можно исполнять через Python/FastAPI orchestration layer.

## Идентификаторы
- `competition_pdf_id`: `5d3df6d69fac3ef91e13ac835b43a35e9e434fbc7e72ea5c01e288d69b66e6a2`
- `canonical_slug`: `enf_269_2023_ozias_ori_octavio_v_obadiah_oaklen`
- `case_cluster_id`: `oaklen_obadiah_ARB-016-2023_cluster`