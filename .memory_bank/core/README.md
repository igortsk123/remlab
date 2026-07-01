# Core — Tier 1 короткие сводки

> Файлы по 2–3 KB. Читаются как первый drill-down из `INDEX.md`. Каждый имеет frontmatter
> (`topic`/`tier:1`/`scope`/`tier2`/`updated`) и финальную строку `Tier 2:` для расширения.
> Шаблон новой сводки — `_template.md`.

## Реестр сводок

| Файл | Тема (topic) | Tier 2 |
|------|--------------|--------|
| `architecture.md` | стек, структура, границы модулей, деплой | `docs/tech-spec-ts-stack.md` |
| `data-model.md` | сущности, таблицы, pgvector, RLS | `docs/tech-spec-ts-stack.md` §4 |
| `user-flow.md` | Stage 1 flow, экраны, free/paid, аналитика | `docs/cjm-ux-v0.2.md` |
| `regression-net.md` | тесты, CI, observability, гардрейлы, DoD | `docs/tech-spec-ts-stack.md` §12 |

> Бизнес-контекст — в `../product_brief.md`. Деплой-playbook — в `../deployment.md`.
> Реестр и decision tree в INDEX держатся в согласии через `tools/memory-audit.mjs` / `/memory-check`.
