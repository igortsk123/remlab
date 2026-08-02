# Memory Bank — Index (Tier 0)

remlab — «Смета-first» v0.4 (ADR-0016): расчёт ремонта/материалов → реф-смета; мастер —
`plans/MASTER-cost-first.md`. Выжимки: `product_brief.md`, `core/market.md`, `core/goals.md`.

## Decision tree — что читать

**Tier 1 (`core/<тема>.md`, сводки)** → drill-down в Tier 2 (`docs/`, `<area>/`, `guides/`).

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Интеграции/доступы — ключи, эндпоинты, клиенты | `core/access-and-integrations.md` | `../domain/integrations.md` |
| Стек, модули, генерация, деплой — по коду | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Схема БД, изоляция сессий, миграции, pgvector | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Деплой/откат/сервер exit-fi — playbook | `deployment.md` | — |
| Смета-лист (ядро v0.4) — калькуляторы, стоимость ремонта, чек-лист, /go/ реф | `core/estimate.md` | `../domain/pricing-works-ru.md` |
| Мебельный трек — каталог, сеты, визуализация | `core/furniture.md` | `../domain/viz-fidelity-playbook.md` |
| Цели продукта — v0.4 «Смета-first» | `core/goals.md` | `../goals-one-photo-furnish-fit.md` |
| Лид-канал «найдём дешевле» — заявка, TG-бот | `core/leads.md` | — |
| Уроки перед планированием — что пробовали и что НЕ сработало | `core/lessons.md` | `../anti-patterns.md` |
| Композиция гостиной — доли площади (справка владельца) | `core/lr-composition.md` | `../domain/lr-composition-guide.md` |
| Рынок RU/UK — спрос, конкуренты, монетизация | `core/market.md` | `../domain/market-research.md` |
| Привлечение/реклама — Яндекс, семантика, стратегия | `core/marketing-acquisition.md` | `../domain/wordstat-semantics.md` |
| Трейсинг AI-пайплайна — лог вызовов LLM, «номер генерации», разбор | `core/observability-tracing.md` | `../domain/observability.md` |
| Бизнес-контекст — зачем/для кого; v0.4 «Смета-first» (v0.3 — истор.) | `product_brief.md` | `domain/brief-details.md` |
| Регресс-защита — тесты, CI, eval, гардрейлы, DoD | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Stage 1 UX-flow, экраны, аналитика | `core/user-flow.md` | `../domain/user-flow-details.md` |
| Состав гостиной — обязательные категории сета и пригодность товаров | `core/lr-checklist.md` | `../domain/living-room-checklist.md` |
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
