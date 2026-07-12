# Memory Bank — Index (Tier 0)

> Always-loaded тонкий указатель.

remlab — «Смета-first» v0.4 (ADR-0016): расчёт ремонта/материалов → реф-смета; мастер —
`plans/MASTER-cost-first.md`. Выжимки: `product_brief.md`, `core/market.md`, `core/goals.md`.
Правила — `CLAUDE.md` («Критично») + `.claude/rules/*.md` (path-scoped, авто).

## Decision tree — что читать

**Tier 1 (`core/<тема>.md`, сводки)** → drill-down в Tier 2 (`docs/`, `<area>/`, `guides/`).

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде | `core/access-and-integrations.md` | `../domain/integrations.md` |
| Стек, структура, модули, генерация, деплой — по коду | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Реальная схема БД (таблицы), изоляция сессий, миграции, pgvector | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Деплой/откат/сервер exit-fi — playbook | `deployment.md` | — |
| Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф | `core/estimate.md` | `../domain/pricing-works-ru.md` |
| Цели продукта — v0.4 «Смета-first»; fit-ветка — отложена (архив) | `core/goals.md` | `../goals-one-photo-furnish-fit.md` |
| Рынок RU/UK — спрос, конкуренты, монетизация, оценки, контекст основателя | `core/market.md` | `../domain/market-research.md` |
| Привлечение/реклама — Яндекс (Директ/Метрика/Вордстат), семантика ниши, сезонность, стратегия | `core/marketing-acquisition.md` | `../domain/wordstat-semantics.md` |
| Трейсинг AI-пайплайна — лог каждого вызова LLM, «номер генерации», разбор, сжатие | `core/observability-tracing.md` | `../domain/observability.md` |
| Бизнес-контекст — зачем/для кого; v0.4 «Смета-first» (v0.3 — истор.) | `product_brief.md` | `domain/brief-details.md` |
| Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Stage 1 UX-flow (построенный AI-флоу), экраны, аналитика | `core/user-flow.md` | `../domain/user-flow-details.md` |
<!-- GENERATED:decision-tree END -->

**Правило:** сначала `core/<тема>.md`, затем drill в Tier 2 (указан в конце сводки).

## Always-on docs (Tier 0/1)
`source-of-truth.md` (конфликты) · `project-state.md` (снимок) · `decisions.md` (ADR) ·
`deployment.md` (деплой/откат exit-fi).

## Ключевые исходники
`docs/master-brief-v0.3.md` — бизнес v0.3 (истор.) · `docs/tech-spec-ts-stack.md` — инж. спека ·
`docs/cjm-ux-v0.2.md` — CJM/экраны · `docs/market-research-ru-uk.md` — рынок · `docs/DECISIONS.md` — ADR.

## Планы
**Мастер: `plans/MASTER-cost-first.md`** (v0.4 «Смета-first», ADR-0016; М0–М7, сценарий,
судьба прежних; старое — `archive/plans/`). Исполнение — `guides/execution-playbook.md`.
Цикл: draft → «деплой» → completed → `completed_plans/` (гейт: `/memory-check` + audit чисто).

## Обслуживание
`/memory-check` (конец сессии) · `/memory-cleanup` · `METADATA_SCHEMA.md` · лог — `changelog/memory-log.md`.
