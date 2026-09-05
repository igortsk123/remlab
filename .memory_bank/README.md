# Memory Bank — remlab (remont-lab.online)

Сервис «Смета-first»: расчёт ремонта/материалов → смета-список с реф-ссылками → хвосты
(визуализация с реальной мебелью, мастера). Memory Bank проекта — единственный канон памяти
(кит memory-bank-template v1.6.0, версия — `_kit/VERSION`).

> **Canonical index.** `INDEX.md` — тонкий always-loaded указатель (Tier 0) с decision tree.
> Этот файл — полный каталог иерархии; обновлять при смене структуры.

## Иерархия (3-tier)

| Tier | Где | Когда грузится | Бюджет |
|------|-----|----------------|--------|
| **0 — Always** | `CLAUDE.md` (корень) + `INDEX.md` | каждая сессия | ≤ 8 KB суммарно (аудит TIER0-BLOAT) |
| **0 — Rules** | `.claude/rules/*.md` (без `paths:` — всегда; с `paths:` — по файлам) | авто | ориентир ~10 KB always-on |
| **1 — Summaries** | `core/*.md` (27 сводок) + always-on `project-state`, `source-of-truth`, `decisions`, `deployment`, `product_brief` | первый drill из INDEX | сводка ≤ 3 KB |
| **2 — Full docs** | `domain/`, `guides/`, `<area>/`, `decisions/`, `lessons/`, `docs/` | по требованию | без лимита; оглавление в доках > 15 KB |

**Обход:** INDEX → `core/<тема>.md` → drill в Tier 2 по `tier2:`/`[[ссылке]]` (≤ 2 перехода).

## Контракт каталогов
- `core/` — Tier 1 сводки (`core/README.md` — реестр, генерируется).
- `domain/` — **модель предмета**: сущности, правила, контракты, данные (каждый док — Tier 2
  какой-то сводки, иначе NO-TIER1).
- `guides/` — **процесс, методика и исследовательские своды** (workflow, спеки движков, верифицированные правила).
- `<area>/` (`advertising/`) — состояние области; свой `README.md`.
- `decisions.md` — индекс ADR (canonical) · `decisions/adr-NNNN-MMMM.md` — полные тексты по
  блокам номеров (`decisions/README.md` — куда писать новое).
- `core/lessons.md` — живые правила по темам · `lessons/<тема>.md` — уроки дословно ·
  `lessons/README.md` — карта номеров · `anti-patterns.md` — код-антипаттерны.
- `plans/` — открытые планы (`README.md`: статусы, поля `plan_kind/pause_reason/…`, «Сейчас в
  работе») · `completed_plans/` — выполненные · `archive/plans/` — отложенные/поглощённые.
- `_intake/` — вход, не хранилище: `brief/`, `history/`, `session-scratch.md` (блокнот), `codex/`
  (вопросы/ответы советника), `owner/` (сырьё владельца); индекс — `_intake/README.md`
  (`tools/intake-index.mjs`). Логи — вне банка (`~/scout-logs/`).
- `archive/` — устаревшее, но ценное (`archive/README.md`), `changelog/` — история и лог уборок,
  `_secrets/` — вне git (значения доступов; в доках — указатели), `_kit/` — версия и манифест кита.

## Frontmatter (обязателен у всех memory-доков)
Базово: `tier` · `topic` · `scope` · `tier1`|`tier2` · `updated` · `importance` · `source`.
Lifecycle (проверяет аудит: REVIEW/UNVERIFIED/LAST-VERIFIED-OLD/CODE-DRIFT): `status` ·
`source_of_truth` · `last_verified` (двигать только после сверки с кодом) · `review_after`.
Полностью — `METADATA_SCHEMA.md`; очистка — `CLEANUP_POLICY.md`.

## Tooling и цикл
- `tools/memory-audit.mjs` (кит) — структурный аудит + регенерация INDEX/реестров; `--check` в CI
  (`.github/workflows/memory-audit.yml`, режим `_kit/gate-mode.txt`).
- `tools/memory-project-audit.mjs` (проект) — уникальность ADR, TTL планов, свежесть блокнота,
  ссылки канона на intake, секреты, md5 кита; тесты `tests/memory-project-audit.test.mjs`.
- Хуки: SessionStart (свежесть + проектный аудит) · Stop `--block` (захват не сделан / аудит грязный) ·
  PreCompact · PreToolUse-гард Bash.
- Скиллы: `/memory-check` (каждая сессия, гейт завершения плана) · `/memory-cleanup` (глубокая
  уборка, dry-run → подтверждение) · `/memory-init` (бутстрап, однократно).
- Верификация: субагент `.claude/agents/verify.md` (план vs diff; доки vs код).

**Lifecycle:** init → use (захват в блокнот на ходу) → `/memory-check` (конец сессии) →
`/memory-cleanup` (после крупных изменений) → archive.
