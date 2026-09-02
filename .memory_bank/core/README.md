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
| `access-and-integrations.md` | access-and-integrations | Интеграции/доступы — ключи, клиенты | `../domain/integrations.md` | 2026-09-01 |
| `architecture.md` | architecture | Стек, модули, генерация, деплой — по коду | `../../docs/tech-spec-ts-stack.md` | 2026-08-06 |
| `catalog.md` | catalog | Каталог — состав, свежесть, дельта | `../domain/catalog-enrichment.md` | 2026-09-01 |
| `data-model.md` | data-model | Схема БД, миграции, pgvector | `../../docs/tech-spec-ts-stack.md` | 2026-08-31 |
| `demo-planner.md` | demo-planner | Демо-планировщик для партнёра — интерактивная расстановка и AI-фото | `../domain/demo-planner-ui.md` | 2026-09-02 |
| `estimate.md` | estimate | Смета — калькуляторы, /go/ реф | `../domain/pricing-works-ru.md` | 2026-08-06 |
| `furniture.md` | furniture | Мебель — сеты, визуализация | `../domain/viz-fidelity-playbook.md` | 2026-09-01 |
| `goals.md` | goals-furnish-fit | Цели — v0.4 «Смета-first» | `../goals-one-photo-furnish-fit.md` | 2026-08-09 |
| `knowledge-db.md` | knowledge-db | Source-KB из книг — спека, KB0–KB9 | `../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` | 2026-08-10 |
| `layout.md` | layout | Расстановка: правила, зоны, прод-ядро | `../domain/occupancy-rules.md` | 2026-08-26 |
| `leads.md` | leads | Лид-канал — заявка, TG-бот | — | 2026-08-28 |
| `lessons.md` | lessons | Уроки перед планированием — что НЕ сработало | `../anti-patterns.md` | 2026-09-02 |
| `lr-composition.md` | lr-composition | Композиция гостиной — доли | `../domain/lr-composition-guide.md` | 2026-09-01 |
| `market.md` | market | Рынок RU/UK — спрос, монетизация | `../domain/market-research.md` | 2026-08-13 |
| `marketing-acquisition.md` | marketing-acquisition | Реклама — Яндекс, семантика | `../domain/wordstat-semantics.md` | 2026-08-13 |
| `mesh-color.md` | mesh-color | Цвет мешей — диагноз промаха покраски, мерка, рычаги | `../domain/viz-fidelity-playbook.md` | 2026-09-01 |
| `mesh-pipeline.md` | mesh-pipeline | 3D-меши товаров — генерация, приёмка, ориентация | `../domain/viz-fidelity-playbook.md` | 2026-09-01 |
| `observability-tracing.md` | observability-tracing | Трейсинг AI-пайплайна — лог, разбор | `../domain/observability.md` | 2026-08-06 |
| `pipeline-order.md` | pipeline-order | Канонический порядок конвейера — от фида до расстановки в планировке | `../domain/pipeline-order-details.md` | 2026-08-29 |
| `regression-net.md` | regression-net | Регресс-защита — тесты, CI, гардрейлы | `../../docs/tech-spec-ts-stack.md` | 2026-08-22 |
| `room-measurement.md` | room-measurement | Замер комнаты по фото — что готово и чем меряем | `../domain/room-measurement.md` | 2026-08-04 |
| `styles.md` | styles | Стили — паспорта, скоринг, сеты | `../domain/interior-styles.md` | 2026-09-02 |
| `user-flow.md` | user-flow | Stage 1 UX-flow, аналитика | `../domain/user-flow-details.md` | 2026-08-06 |
| `lr-checklist.md` | lr-checklist | Состав гостиной — роли и пригодность | `../domain/living-room-checklist.md` | 2026-08-12 |
<!-- GENERATED:core-registry END -->

> Реестр и decision tree в INDEX регенерирует `tools/memory-audit.mjs` (или `/memory-check`
> вручную, без Node). Создал сводку — проставь frontmatter и запусти аудит: он сам впишет её
> и в реестр, и в decision tree. Руками таблицы не правим.
