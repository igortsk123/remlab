# Memory Bank — Index (Tier 0)

> Always-loaded тонкий указатель. Drill-down только когда нужно.

remlab — B2C AI-помощник по ремонту комнаты, модель v0.3 (affiliate-first freemium).
Истина: `docs/master-brief-v0.3.md`; выжимки — `product_brief.md`, `core/market.md`, `core/goals.md`.

## Минимум правил (всегда)
План first (`.claude/rules/agent-workflow.md`) · читай INDEX → только нужный tier · один факт — одно
место · гипотезы, не аксиомы (`docs/DECISIONS.md`) · не ломать VPN-ноду exit-fi (`deployment.md`) ·
изменил архитектуру/контракты → обнови память (`.claude/rules/memory-discipline.md`).

## Decision tree — что читать

Идём: **Tier 1 (`core/<тема>.md`, сводки)** → drill-down в Tier 2 (`docs/`, `<area>/`, `guides/`) при нехватке.

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде | `core/access-and-integrations.md` | `../domain/integrations.md` |
| Стек, структура, модули, генерация, деплой — по коду | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Реальная схема БД (4 таблицы), изоляция сессий, миграции, pgvector | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Деплой/откат/сервер exit-fi — playbook | `deployment.md` | — |
| Цели продукта — меблировка/замена по одному фото с проверкой «влезет/не влезет» | `core/goals.md` | `../goals-one-photo-furnish-fit.md` |
| Рынок RU/UK — спрос, конкуренты, монетизация, оценки, контекст основателя | `core/market.md` | `../domain/market-research.md` |
| Трейсинг AI-пайплайна — лог каждого вызова LLM, «номер генерации», разбор, сжатие | `core/observability-tracing.md` | `../domain/observability.md` |
| Бизнес-контекст — зачем продукт, для кого, монетизация (v0.3) | `product_brief.md` | `domain/brief-details.md` |
| Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Stage 1 UX-flow, экраны, free/paid граница, аналитика | `core/user-flow.md` | `../domain/user-flow-details.md` |
<!-- GENERATED:decision-tree END -->

**Правило:** сначала `core/<тема>.md`. Не хватает данных — drill в Tier 2 (указан в конце сводки).

## Always-on docs (Tier 0/1)
- `source-of-truth.md` — разрешение конфликтов источников.
- `project-state.md` — снимок «где проект сейчас» (обновлять после крупных изменений).
- `decisions.md` — ADR-лог (полные — `docs/DECISIONS.md`).
- `deployment.md` — playbook деплоя/отката/автоочистки на exit-fi.

## Ключевые исходники (docs/)
- **`docs/master-brief-v0.3.md` — МАСТЕР-документ (бизнес/монетизация, приоритет выше v0.2).**
- `docs/tech-spec-ts-stack.md` — инженерная спека (стек, контракты, схема, регресс-защита).
- `docs/cjm-ux-v0.2.md` — продуктовый слой (CJM, экраны, free/paid, аналитика).
- `docs/market-research-ru-uk.md` — рыночное исследование RU/UK (спрос, конкуренты, монетизация).
- `docs/DECISIONS.md` — полные ADR.

## Path-scoped rules (auto-loaded)
`.claude/rules/*.md` грузятся автоматически при работе с релевантными файлами (по `paths:`).

## Plans workflow
draft → «деплой» → in_progress → completed → в `completed_plans/` (гейт: /memory-check + audit чисто).
Шаблон: `plans/_template.md`; реестры генерирует аудит.

## Index map
- `core/` — Tier 1 сводки. `docs/` — полные исходники/спеки. `guides/` — процесс-доки.
- `archive/` — устаревшая, но ценная память. `changelog/memory-log.md` — лог очисток.

## Слои памяти и обслуживание
Канон — этот `.memory_bank/` (в git); авто-память харнесса — per-user, мост — `/memory-check` Этап 1.5.
Конец сессии — `/memory-check` (или `node tools/memory-audit.mjs`); глубокая уборка — `/memory-cleanup`
(`CLEANUP_POLICY.md`); поля шапки — `METADATA_SCHEMA.md`; как устроено — `guides/memory-automation.md`.
