# QUALITY_SCORE.md

Цель: сделать качество **видимым и измеримым**. Агентам проще улучшать то, что измеряется.

## Scoreboard (пример)
| Домен/слой | Тесты | Типы/валидация | Арх.инварианты | Документация | Observability | Security | Итог |
|---|---:|---:|---:|---:|---:|---:|---:|
| domain:core | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/18 |
| domain:auth | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/18 |
| domain:canonical-chunk-model | 2/3 | 2/3 | 2/3 | 2/3 | 1/3 | 2/3 | 11/18 |

## Последнее обновление (2026-03-05)
- Добавлены контрактные тесты для additive compatibility и typed corpus filters.
- Добавлены explicit schema contracts для canonical/type/facet/lineage/search projection.
- Добавлены migration scripts up/down для canonical chunk model v1.
- Риски:
  - observability пока минимальная (in-memory bootstrap path),
  - нет production-grade migration runner в репозитории.

Шкала 0–3:
- 0 — отсутствует
- 1 — частично / ручная проверка
- 2 — покрыто автоматикой, но есть дырки
- 3 — устойчиво, есть evals/метрики/регрессии ловятся

## Как обновлять
- Небольшие изменения: обновляйте соответствующую строку в PR.
- Ночной GC (если настроен): скрипт может обновлять автоматически и открывать PR.
