# Core — Tier 1 короткие сводки

> Файлы по 2–3 KB. Читаются как первый drill-down из `INDEX.md`. Каждый имеет frontmatter
> (`topic`/`tier:1`/`scope`/`tier2`/`updated`) и финальную строку `Tier 2:` для расширения.
> Шаблон новой сводки — `_template.md`. Типовые темы: `product`, `architecture`, `data-models`,
> `flows`, `access-and-integrations` (+ домен-специфичные).

## Реестр сводок

<!-- GENERATED:core-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Файл | topic | Когда читать (scope) | Tier 2 | updated |
|------|-------|----------------------|--------|---------|
| `access-and-integrations.md` | access-and-integrations | Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде | `../domain/integrations.md` | 2026-07-11 |
| `architecture.md` | architecture | Стек, структура, модули, генерация, деплой — по коду | `../../docs/tech-spec-ts-stack.md` | 2026-07-11 |
| `data-model.md` | data-model | Реальная схема БД (4 таблицы), изоляция сессий, миграции, pgvector | `../../docs/tech-spec-ts-stack.md` | 2026-07-09 |
| `estimate.md` | estimate | Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф | `../domain/pricing-works-ru.md` | 2026-07-11 |
| `goals.md` | goals-furnish-fit | Цели продукта — v0.4 «Смета-first»; fit-ветка — отложена (архив) | `../goals-one-photo-furnish-fit.md` | 2026-07-09 |
| `market.md` | market | Рынок RU/UK — спрос, конкуренты, монетизация, оценки, контекст основателя | `../domain/market-research.md` | 2026-07-11 |
| `marketing-acquisition.md` | marketing-acquisition | Привлечение/реклама — Яндекс (Директ/Метрика/Вордстат), семантика ниши, сезонность, стратегия | `../domain/wordstat-semantics.md` | 2026-07-11 |
| `observability-tracing.md` | observability-tracing | Трейсинг AI-пайплайна — лог каждого вызова LLM, «номер генерации», разбор, сжатие | `../domain/observability.md` | 2026-07-09 |
| `regression-net.md` | regression-net | Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD | `../../docs/tech-spec-ts-stack.md` | 2026-07-11 |
| `user-flow.md` | user-flow | Stage 1 UX-flow (построенный AI-флоу), экраны, аналитика | `../domain/user-flow-details.md` | 2026-07-09 |
<!-- GENERATED:core-registry END -->

> Реестр и decision tree в INDEX регенерирует `tools/memory-audit.mjs` (или `/memory-check`
> вручную, без Node). Создал сводку — проставь frontmatter и запусти аудит: он сам впишет её
> и в реестр, и в decision tree. Руками таблицы не правим.
