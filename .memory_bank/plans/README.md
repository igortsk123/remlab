# Plans — активные планы

## Lifecycle
```
draft → in_progress → completed → перенос в completed_plans/
                   ↘ partial   → остаётся здесь
        cancelled → остаётся здесь
```
Только `completed` переносятся в `completed_plans/`. `partial`/`cancelled` остаются здесь.

## Статусы
| Статус | Описание |
|--------|----------|
| `draft` | Создан, ждёт команду «деплой» |
| `in_progress` | Деплой начат |
| `partial` | Прерван, часть выполнена — НЕ переносить |
| `completed` | Всё выполнено → перенести в `completed_plans/` |
| `cancelled` | Отменён явно |

## Реестр активных планов

| slug | Название | status | created |
|------|----------|--------|---------|
| `stage1-skeleton` | Stage 1 каркас: схема БД + 7 экранов flow + e2e | draft | 2026-07-01 |

> `remlab-bootstrap` завершён → `completed_plans/`.
> `pipeline-tracing` (трейсинг AI-пайплайна, ADR-0013) завершён 2026-07-02 → `completed_plans/`.

> Шаблон нового плана — `_template.md`.
