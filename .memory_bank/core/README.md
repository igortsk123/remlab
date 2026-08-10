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
| `access-and-integrations.md` | access-and-integrations | Интеграции/доступы — ключи, эндпоинты, клиенты | `../domain/integrations.md` | 2026-08-06 |
| `architecture.md` | architecture | Стек, модули, генерация, деплой — по коду | `../../docs/tech-spec-ts-stack.md` | 2026-08-06 |
| `catalog.md` | catalog | Каталог товаров — состав, свежесть, обогащение, дельта | `../domain/catalog-enrichment.md` | 2026-08-08 |
| `data-model.md` | data-model | Схема БД, изоляция сессий, миграции, pgvector | `../../docs/tech-spec-ts-stack.md` | 2026-07-31 |
| `estimate.md` | estimate | Смета-лист — калькуляторы, стоимость, /go/ реф | `../domain/pricing-works-ru.md` | 2026-08-06 |
| `furniture.md` | furniture | Мебель — каталог, сеты, визуализация | `../domain/viz-fidelity-playbook.md` | 2026-08-08 |
| `goals.md` | goals-furnish-fit | Цели продукта — v0.4 «Смета-first» | `../goals-one-photo-furnish-fit.md` | 2026-08-09 |
| `knowledge-db.md` | knowledge-db | Source-KB из книг — спека, план KB0–KB9 | `../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` | 2026-08-10 |
| `layout.md` | layout | Расстановка — свод правил, зона-билдер, прод-ядро | `../domain/occupancy-rules.md` | 2026-08-09 |
| `leads.md` | leads | Лид-канал «найдём дешевле» — заявка, TG-бот | — | 2026-07-28 |
| `lessons.md` | lessons | Уроки перед планированием — что пробовали и что НЕ сработало | `../anti-patterns.md` | 2026-08-09 |
| `lr-composition.md` | lr-composition | Композиция гостиной — доли площади | `../domain/lr-composition-guide.md` | 2026-08-01 |
| `market.md` | market | Рынок RU/UK — спрос, конкуренты, монетизация | `../domain/market-research.md` | 2026-07-11 |
| `marketing-acquisition.md` | marketing-acquisition | Реклама — Яндекс, семантика, стратегия | `../domain/wordstat-semantics.md` | 2026-07-11 |
| `observability-tracing.md` | observability-tracing | Трейсинг AI-пайплайна — лог LLM-вызовов, разбор | `../domain/observability.md` | 2026-08-06 |
| `regression-net.md` | regression-net | Регресс-защита — тесты, CI, eval, гардрейлы, DoD | `../../docs/tech-spec-ts-stack.md` | 2026-08-08 |
| `room-measurement.md` | room-measurement | Замер комнаты по фото — что готово, чем меряем, что переиспользовать | `../domain/room-measurement.md` | 2026-08-04 |
| `styles.md` | styles | Стили — паспорта, скоринг товаров, сеты и генерация | `../domain/interior-styles.md` | 2026-08-02 |
| `user-flow.md` | user-flow | Stage 1 UX-flow, экраны, аналитика | `../domain/user-flow-details.md` | 2026-08-06 |
| `lr-checklist.md` | lr-checklist | Состав гостиной — роли сета и пригодность товаров | `../domain/living-room-checklist.md` | 2026-08-02 |
<!-- GENERATED:core-registry END -->

> Реестр и decision tree в INDEX регенерирует `tools/memory-audit.mjs` (или `/memory-check`
> вручную, без Node). Создал сводку — проставь frontmatter и запусти аудит: он сам впишет её
> и в реестр, и в decision tree. Руками таблицы не правим.
