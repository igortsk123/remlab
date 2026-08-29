# Memory Bank — Index (Tier 0)

remlab — «Смета-first» v0.4 (ADR-0016): расчёт ремонта/материалов → реф-смета; мастер —
`plans/MASTER-cost-first.md`.

## Decision tree — что читать

**Tier 1 (`core/<тема>.md`, сводки)** → drill-down в Tier 2 (`docs/`, `<area>/`, `guides/`).

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Интеграции/доступы — ключи, клиенты | `core/access-and-integrations.md` | `../domain/integrations.md` |
| Стек, модули, генерация, деплой — по коду | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Каталог — состав, свежесть, дельта | `core/catalog.md` | `../domain/catalog-enrichment.md` |
| Схема БД, миграции, pgvector | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Демо-планировщик для партнёра — интерактивная расстановка и AI-фото | `core/demo-planner.md` | `../domain/viz-fidelity-playbook.md` |
| Деплой/откат/сервер exit-fi — playbook | `deployment.md` | — |
| Смета — калькуляторы, /go/ реф | `core/estimate.md` | `../domain/pricing-works-ru.md` |
| Мебель — сеты, визуализация | `core/furniture.md` | `../domain/viz-fidelity-playbook.md` |
| Цели — v0.4 «Смета-first» | `core/goals.md` | `../goals-one-photo-furnish-fit.md` |
| Source-KB из книг — спека, KB0–KB9 | `core/knowledge-db.md` | `../../remlab_knowledge_db_v1/spec/SPEC_source_kb_v1.md` |
| Расстановка: правила, зоны, прод-ядро | `core/layout.md` | `../domain/occupancy-rules.md` |
| Лид-канал — заявка, TG-бот | `core/leads.md` | — |
| Уроки перед планированием — что НЕ сработало | `core/lessons.md` | `../anti-patterns.md` |
| Композиция гостиной — доли | `core/lr-composition.md` | `../domain/lr-composition-guide.md` |
| Рынок RU/UK — спрос, монетизация | `core/market.md` | `../domain/market-research.md` |
| Реклама — Яндекс, семантика | `core/marketing-acquisition.md` | `../domain/wordstat-semantics.md` |
| 3D-меши товаров — генерация, приёмка, ориентация | `core/mesh-pipeline.md` | `../domain/viz-fidelity-playbook.md` |
| Трейсинг AI-пайплайна — лог, разбор | `core/observability-tracing.md` | `../domain/observability.md` |
| Канонический порядок конвейера — от фида до расстановки в планировке | `core/pipeline-order.md` | `../domain/pipeline-order-details.md` |
| Бизнес-контекст; v0.4 «Смета-first» | `product_brief.md` | `domain/brief-details.md` |
| Регресс-защита — тесты, CI, гардрейлы | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Замер комнаты по фото — что готово и чем меряем | `core/room-measurement.md` | `../domain/room-measurement.md` |
| Стили — паспорта, скоринг, сеты | `core/styles.md` | `../domain/interior-styles.md` |
| Stage 1 UX-flow, аналитика | `core/user-flow.md` | `../domain/user-flow-details.md` |
| Состав гостиной — роли и пригодность | `core/lr-checklist.md` | `../domain/living-room-checklist.md` |
<!-- GENERATED:decision-tree END -->

## Always-on docs (Tier 0/1)
`source-of-truth.md` (конфликты) · `project-state.md` (снимок) · `decisions.md` (ADR) ·
`deployment.md` (деплой/откат exit-fi).

## Ключевые исходники
`docs/`: tech-spec-ts-stack · DECISIONS · истор.: master-brief-v0.3, cjm-ux-v0.2.

## Планы
**Мастер: `plans/MASTER-cost-first.md`** (М0–М7; старое — `archive/plans/`). Исполнение —
`guides/execution-playbook.md`. Цикл: draft → «деплой» → completed → `completed_plans/`.

## Обслуживание
`/memory-check` · `/memory-cleanup` · `METADATA_SCHEMA.md` · лог — `changelog/memory-log.md`.
