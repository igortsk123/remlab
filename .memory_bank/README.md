# Memory Bank — remlab (remont-lab)

B2C AI-помощник по обновлению квартиры. Memory Bank проекта.

> **Canonical index.** `INDEX.md` — тонкий always-loaded указатель (Tier 0). Этот файл —
> полный каталог иерархии. Обновляй каталог здесь.

## Иерархия (3-tier)

| Tier | Где | Когда грузится | Размер |
|------|-----|----------------|--------|
| **0 — Always** | `CLAUDE.md` (корень), `INDEX.md` | каждая сессия | ~5 KB |
| **0 — Path-scoped** | `.claude/rules/*.md` (frontmatter `paths:`) | авто при касании файлов | ~10 KB |
| **1 — Summaries** | `core/*.md` | первый drill-down из INDEX | ~20 KB |
| **2 — Full docs** | `<area>/*.md`, `guides/*.md` | по требованию | без лимита |

**Правило обхода:** INDEX → `core/` (Tier 1) → drill в `<area>/`/`guides/` (Tier 2) если нужны детали.

## Каталог

### Always-on
- `INDEX.md` — decision tree (генерируется аудитом).
- `source-of-truth.md` — разрешение конфликтов источников.
- `project-state.md` — снимок состояния.
- `decisions.md` — ADR-лог.
- `product_brief.md` — бизнес-контекст.

### Tier 1
- `core/*.md` — короткие сводки по темам (`core/README.md` — реестр).

### Tier 2
- `guides/` — полные процесс-доки (workflow, code-standards, review-rules).
- `domain/` — доменные модели.
- `<area>/` — детали по областям (добавляются по мере роста).

### Workflow
- `plans/` — активные планы (+ `_template.md`, реестр). `completed_plans/` — архив планов.

### Maintenance / lifecycle
- `CLEANUP_POLICY.md` — правила очистки памяти (классификация, safety, archive-before-delete).
- `METADATA_SCHEMA.md` — поля frontmatter и допустимые значения.
- `archive/` — устаревшая, но ценная память (история; исключена из аудита).
- `changelog/memory-log.md` — журнал очисток/архиваций.

### Tooling
- `tools/memory-audit.mjs` (в корне kit) — регенерит decision tree, ловит orphan/stale/битые ссылки.
- Скиллы: `/memory-init` (бутстрап) · `/memory-check` (быстрая гигиена) · `/memory-cleanup`
  (глубокая уборка после крупных изменений: дубли/устаревшее/архивация, dry-run → подтверждение).

**Lifecycle:** init → use → `/memory-check` → `/memory-cleanup` → archive.

## Frontmatter (обязателен у всех memory-доков)
Базово: `tier` · `topic` · `scope` · `tier1`|`tier2` · `updated` · `importance` · `source`.
Опционально (для очистки): `status` · `source_of_truth` · `last_verified` · `review_after`.
Полностью — `METADATA_SCHEMA.md`.
