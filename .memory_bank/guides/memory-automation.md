---
tier: 2
topic: memory-automation
scope: Как история проекта попадает в Memory Bank — слои, мост, хуки-напоминания, гейты
tier1: ""
last_verified: 2026-11-12
updated: 2026-11-12
importance: high
source: manual
---

# Memory Automation — как история проекта попадает в Memory Bank

> Задача: чтобы ВСЁ проектное durable оседало в `.memory_bank/` (в git, видно команде), а не
> в чате или авто-памяти харнесса. Принцип: **записывает агент (нужно суждение), а система
> напоминает, детектит дрейф и не даёт закрыть работу без захвата.**

## Два слоя и мост
- `.memory_bank/` (в git) — канон проекта, ОДНА копия, в репо кода.
- `~/.claude/projects/<cwd>/memory/` (per-user) — служебное про работу агента; харнесс пишет
  сюда по умолчанию. НЕ хранилище проекта.
- Мост: `/memory-check` Этап 1.5 реконсилит — проектное переносится в банк, per-user остаётся.
Полное правило — `.claude/rules/memory-discipline.md` (auto-loaded).

## Цикл сессии (что гарантирует полноту)
1. **Старт** — SessionStart-hook (`tools/session-freshness.mjs`) печатает баннер, если
   `project-state` старше 14 дней, аудит нашёл проблемы или есть хотя бы предупреждения (CODE-DRIFT и др.); иначе молчит. Читать: `INDEX.md` → нужные доки.
2. **В процессе** — durable-факт фиксировать сразу в `.memory_bank/` (no-orphan). PostToolUse(Read)-hook
   (`tools/read-logger.mjs`) логирует чтения доков в `changelog/reads.log`. PostToolUse(Edit|Write)-hook
   (`tools/code-touch-hint.mjs`, кит 1.9) подсказывает агенту, какие доки описывают правленый файл кода
   (раз на файл за сессию) — описание правится в том же изменении.
   С кита 1.11 корень берётся по пути файла (правка рабочего в `.claude/worktrees/<имя>/` тоже видна), журнал правок —
   один на репо: `<git-common-dir>/memory-bank/code-touch-hint.log`. При приёмке ветки — `node tools/memory-impact.mjs
   --base main --head <ветка>`: какие доки описывают изменённый код (обновлён / сверен без правок / в очередь сверки).
   Ночью — `tools/nightly-verify/nightly-verify.mjs` (план mem-freshness-01, конфиг `_kit/nightly-verify.conf`).
3. **Конец сессии** — `/memory-check`: захват → мост → сверка затронутого (этап 1.6: доки изменённого кода +
   CODE-DRIFT + ротация одной давней сводки → `verify`; `last_verified` — только по таблице доказательств,
   каждая сверка — `node tools/memory-health.mjs --log-verify …`) → уровни → связи+INDEX+реестры → чистота.
   Работает ли механизм — `node tools/memory-health.mjs` (сверки, найдено/исправлено, сдвиги дат без записи).
   Stop-hook (`tools/session-reminder.mjs --block --scratch-fresh-days 2`, `.claude/settings.json`) блокирует
   завершение ответа, только если одновременно есть план `in_progress` (или `completed`, ещё не перенесённый из
   `plans/`), правки вне `.memory_bank/` и при этом блокнот пуст или без записи свежее 2 дней, либо грязен
   `memory-audit --check` (без CODE-DRIFT).
4. **Завершение плана** — гейт: план не `completed`, пока `/memory-check` не выполнен и audit
   не «чисто» (`agent-workflow.md`, DoD в `plans/_template.md`).

## Скиллы (инструменты)
- `/memory-init` — первичная сборка Memory Bank из `_intake/` (bootstrap; заводит core-сводки под ВСЕ домены).
- `/memory-check` — **единая команда после работы**: захват сессии → мост авто-памяти → уровни →
  связи+INDEX+реестры → структурная чистота. Запускает Клод (без рекурсии/runaway).
- `/memory-cleanup` — глубокая РАЗРУШИТЕЛЬНАЯ уборка целых доков: дубли→merge, устаревшее→архивация
  (dry-run → подтверждение). Отдельно от memory-check.

## Механический слой (Node, опционально, но рекомендован)
- `tools/memory-audit.mjs` — детерминированная проверка; полный список категорий — в его шапке. Основные
  (ORPHAN/STALE/LAGGING/BROKEN/REVIEW/UNVERIFIED/BLOATED/TIER1-BLOAT/TIER0-BLOAT/NO-TIER1/PLACEHOLDER/
  DUP-TOPIC/BAD-FM/INDEX-REF/REGISTRY-STALE/PLAN-STUCK/PLAN-MISPLACED/DIVERGENCE/SECRET/CODE-REF/FROZEN-MEMORY/
  RULES-FM/MEM-INJECT/ADR-DUP) — проблемы (exit 1, Stop-гейт); CODE-DRIFT, LAST-VERIFIED-OLD, NO-ANCHOR, TIER0-RULES,
  DOC-*, остальные ADR-*/PLAN-*, DECISIONS-BLOAT, CANON-INTAKE-REF, INTAKE-*, KIT-* — предупреждения (прогон не грязнят). Плюс регенерация decision tree и реестров.
  Для CI/хука: `--check` (не пишет файлы); пороги remlab — `_kit/audit-flags.txt`. CI: `.github/workflows/memory-audit.yml`
  (режим `_kit/gate-mode.txt` = `warn`) и `memory-project-audit --check` в `.github/workflows/ci.yml`.
- В remlab хуки — в `.claude/settings.json` (в репозитории, ADR-0208): SessionStart = `tools/session-freshness.mjs` +
  `memory-project-audit.mjs --brief`; Stop = `session-reminder.mjs --block --scratch-fresh-days 2` (аудит встроен, без
  CODE-DRIFT); PreCompact = `tools/precompact-guard.mjs`; PostToolUse = `tools/read-logger.mjs` (Read) и
  `tools/code-touch-hint.mjs` (Edit|Write); PreToolUse(Bash) = `tools/hooks/guard-bash.mjs`. Мягкий шаблон для чужих
  проектов — `tools/stop-hook.example.json`. Без Node, но с `r` — хуки идут через `r node tools/…`
  на pakardev (кроме `guard-bash`: он только при локальном Node); без Node и без `r` — только shell-напоминание у Stop.

## Почему не авто-хук ЗАПИСИ на каждый SessionEnd
Авто-запись контента опасна (рекурсия, стоимость, нужно суждение о том, что durable). Поэтому
запись — через скилл, который запускает Клод; система лишь НАПОМИНАЕТ (хуки), ДЕТЕКТИТ дрейф
(audit) и ГЕЙТИТ завершение плана. Это осознанный дизайн, не пробел.

## Старт разработки «с нуля» в этом проекте
Memory Bank самодостаточен: новая сессия читает `CLAUDE.md` → `INDEX.md` → `project-state.md` и
может продолжать. Скиллы `/memory-*` установлены в `.claude/skills/`. Версия кита — `.memory_bank/_kit/VERSION`
(обновление kit-owned файлов — `upgrade.sh` из кита).

## Подробности дисциплины памяти (перенесено из `.claude/rules/memory-discipline.md` 2026-09-05)
Правило ужато (05.09 — 55 строк, на 18.10 — 61; норма `guides/how-to-write-rules.md` ≤~60); сюда — обоснования и примеры.
- **Захват на ходу.** Захват в точке максимальной salience дешевле и надёжнее, чем раскопки диалога
  в конце сессии; блокнот лечит «согласованное замерзание» (работал → не записал). Формат строки:
  `- ГГГГ-ММ-ДД — <что> — <куда в память>`, ≤2 строки; цифры и хроника — сразу в
  `changelog/project-history.md` или ADR. После свода блокнот усекается до метки; одна честная
  датированная строка «- ГГГГ-ММ-ДД — свод выполнен, блокнот чист» допустима: Stop-хук remlab (`--scratch-fresh-days 2`)
  требует непустоты и записи не старше 2 дней; строки без даты считает свежими.
- **Anti-rediscovery / инвентаризация доступов.** `tools/access-inventory.mjs` ищет ключи в `.env`-файлах
  под `~/igor`, `~/mltest`, `~/.config` (печатает имена и первые 4 символа, значения — нет); причина — ключ fal.ai и проект замера комнаты лежали вне репо (урок 57).
- **Триггеры сохранения (полный список):** архитектура (слои/папки/паттерны) → `core/architecture.md`;
  маршруты/флоу → `core/*`; контракты/API/модели → `domain/` + `core/data-model.md`; решение → ADR
  (том + индекс); интеграция (эндпоинт, где ключ/прокси, формат, клиент в коде) →
  `core/access-and-integrations.md`; новая область → `core/<домен>.md`; смена этапа → снимок.
- **Sync Tier 1 ↔ Tier 2.** Рассинхрон `Tier2.updated > Tier1.updated` ловит STALE; отставание слоя
  от `project-state` — LAGGING; реестры (core/plans/completed_plans) и decision tree — только аудитом.
- **Якорь на код.** Не «трейсинг пишет шаги», а «трейсинг пишет шаги — `lib/trace/`, таблицы
  `db/schema.ts`»: якорь включает CODE-REF (путь исчез) и CODE-DRIFT (warning: код изменён позже `last_verified`,
  без неё — `updated`, на `--code-drift-days` = 7 дн. и больше; журналы decisions/project-state/source-of-truth не проверяются). Аннотировать каждую фразу не надо — Tier 1 ограничен 3 КБ.
- **Отравление памяти (OWASP ASI06).** Персистентная память превращает разовую инъекцию в постоянную;
  external-доки аудит сканирует на императивы (MEM-INJECT).
- **Гигиена.** `/memory-check` — часто (структурный гейт); `/memory-cleanup` — после крупных изменений
  (дубли, устаревшее, архивация, лог; правила — `CLEANUP_POLICY.md`).
