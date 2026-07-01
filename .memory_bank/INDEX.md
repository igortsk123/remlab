# Memory Bank — Index (Tier 0)

> Always-loaded тонкий указатель. Drill-down только когда нужно.

remlab (remont-lab) — B2C AI-помощник по обновлению квартиры (фото → стиль → AI-preview → free preview → paid room pack → workspace).

## Минимум правил (всегда)
- **План first** — задача → план-файл → ждать «деплой» (`.claude/rules/agent-workflow.md`).
- **Читай INDEX перед задачей**, дальше — только нужный Tier 1/Tier 2 (не сканируй всё).
- **Не дублируй память** — один факт в одном месте; сводка ≤3 KB со ссылкой на Tier 2.
- **Гипотезы, не аксиомы** — отклонение от спеки → `docs/DECISIONS.md`.
- **Не ломать VPN-ноду на exit-fi** — см. `deployment.md`.
- **Меняешь архитектуру/контракты → обнови память** (`.claude/rules/memory-discipline.md`).

## Decision tree — что читать

Идём: **Tier 1 (`core/<тема>.md`, сводки)** → drill-down в Tier 2 (`docs/`, `<area>/`, `guides/`) при нехватке.

<!-- GENERATED:decision-tree START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| Задача (scope) | Tier 1 | Tier 2 |
|----------------|--------|--------|
| Стек, структура репозитория, границы модулей, архитектура деплоя | `core/architecture.md` | `../../docs/tech-spec-ts-stack.md` |
| Модель данных, ключевые таблицы, pgvector, RLS | `core/data-model.md` | `../../docs/tech-spec-ts-stack.md` |
| Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD | `core/regression-net.md` | `../../docs/tech-spec-ts-stack.md` |
| Stage 1 UX-flow, экраны, free/paid граница, аналитика | `core/user-flow.md` | `../../docs/cjm-ux-v0.2.md` |
| Бизнес-контекст — зачем продукт, для кого, что в scope | `product_brief.md` | `../docs/cjm-ux-v0.2.md` |
<!-- GENERATED:decision-tree END -->

**Правило:** сначала `core/<тема>.md`. Не хватает данных — drill в Tier 2 (указан в конце сводки).

## Always-on docs (Tier 0/1)
- `source-of-truth.md` — разрешение конфликтов источников.
- `project-state.md` — снимок «где проект сейчас» (обновлять после крупных изменений).
- `decisions.md` — ADR-лог (полные — `docs/DECISIONS.md`).
- `deployment.md` — playbook деплоя/отката/автоочистки на exit-fi.

## Ключевые исходники (docs/)
- `docs/tech-spec-ts-stack.md` — инженерная спека (стек, контракты, схема, регресс-защита).
- `docs/cjm-ux-v0.2.md` — продуктовый слой (CJM, экраны, free/paid, аналитика).
- `docs/DECISIONS.md` — полные ADR.

## Path-scoped rules (auto-loaded)
`.claude/rules/*.md` грузятся автоматически при работе с релевантными файлами (по `paths:`).

## Plans workflow
1. `plans/<slug>.md` (status `draft`) → ждать «деплой».
2. Deploy → выполнить → `completed` → переместить в `completed_plans/`.
3. `partial` / `cancelled` остаются в `plans/`.
Активный план: `plans/remlab-bootstrap.md` (S1..S4). Шаблон: `plans/_template.md`.

## Index map
- `core/` — Tier 1 сводки. `docs/` — полные исходники/спеки. `guides/` — процесс-доки.
- `archive/` — устаревшая, но ценная память. `changelog/memory-log.md` — лог очисток.

## Обслуживание памяти
- **Быстро:** `/memory-check` (без Node) или `node tools/memory-audit.mjs`.
- **Глубоко:** `/memory-cleanup` (dry-run → подтверждение). Правила: `CLEANUP_POLICY.md`.
- Поля frontmatter: `METADATA_SCHEMA.md`.
