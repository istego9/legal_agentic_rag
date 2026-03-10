# Module Specs

Этот каталог содержит ТЗ по модулям, которые должны цепляться к общему platform scaffold.

## Порядок работы
1. Сначала замораживается scaffold:
   - `docs/product-specs/agentic-legal-platform-scaffold.md`
2. Затем central lane:
   - `01-control-plane-and-contracts.md`
3. После заморозки central lane можно вести параллельно:
   - `02-ingest-and-corpus-canonicalization.md`
   - `05-eval-scorer-and-reporting.md`
   - `08-web-research-console.md`
4. После появления минимально стабильного canonical corpus можно параллелить:
   - `03-retrieval-and-evidence-selection.md`
   - `07-gold-and-synthetic-data.md`
5. После стабилизации retrieval contracts можно параллелить:
   - `04-typed-solvers-and-no-answer.md`
   - `06-experiments-and-leaderboard.md`

## Центральные модули
- `01-control-plane-and-contracts.md`

Эти изменения нельзя распараллеливать без одного владельца, потому что они замораживают общие контракты.

## Параллельные модули
- ingestion
- retrieval
- solvers
- eval
- experiments
- gold/synth
- web console

Каждый модуль обязан:
- иметь явную цель создания;
- публиковать и потреблять только зафиксированные контракты;
- иметь собственный validation plan;
- не менять shared contracts без отдельного ТЗ.
