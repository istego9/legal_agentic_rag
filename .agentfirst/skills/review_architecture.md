# Skill: Architecture Review

## Purpose
Проверить, что изменения соблюдают архитектурные инварианты.

## Inputs
- diff / список файлов
- `docs/ARCHITECTURE.md`

## Checks
- зависимости не нарушают направления
- новые модули попали в правильный слой
- boundary contracts обновлены

## Output
- список замечаний с severity: S1 (blocking), S2, S3
