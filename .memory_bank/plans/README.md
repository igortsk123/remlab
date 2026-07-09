# Plans — активные планы

## Lifecycle
```
draft → in_progress → completed → перенос в completed_plans/
                   ↘ partial   → остаётся здесь
        cancelled → остаётся здесь
```
Только `completed` переносятся в `completed_plans/`. `partial`/`cancelled` остаются здесь.
**Гейт:** план не становится `completed`, пока не выполнен `/memory-check` и audit не «чисто»
(см. `.claude/rules/agent-workflow.md`).

## Статусы
| Статус | Описание |
|--------|----------|
| `draft` | Создан, ждёт команду «деплой» |
| `in_progress` | Деплой начат |
| `partial` | Прерван, часть выполнена — НЕ переносить |
| `completed` | Всё выполнено → перенести в `completed_plans/` |
| `cancelled` | Отменён явно |

## Реестр активных планов

<!-- GENERATED:plans-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| slug | Название | status | created | updated |
|------|----------|--------|---------|---------|
| kit-align | Приведение remlab к киту v1.1.0 (по HEAL.md, эталон sup2) | completed | 2026-07-09 | 2026-07-09 |
| round-oval-footprint | — | draft | 2026-07-07 | — |
| unified-measurement-pipeline | — | draft | 2026-07-06 | 2026-07-06 |
| object-size-reference | — | draft | 2026-07-06 | 2026-07-06 |
| accuracy-upgrade-fal | — | draft | 2026-07-06 | 2026-07-06 |
| MASTER-roadmap | — | active | 2026-07-06 | 2026-07-06 |
| room-measurement-a4 | — | draft | 2026-07-05 | 2026-07-05 |
| stage1-skeleton | — | draft | 2026-07-01 | 2026-07-01 |
| stage1-master-roadmap | — | draft | 2026-07-01 | 2026-07-01 |
<!-- GENERATED:plans-registry END -->

> Шаблон нового плана — `_template.md`. Реестр регенерирует аудит — руками не правим.
> Audit также ловит зомби: `in_progress` без движения (PLAN-STUCK) и `completed`,
> забытый в этой папке (PLAN-MISPLACED).
