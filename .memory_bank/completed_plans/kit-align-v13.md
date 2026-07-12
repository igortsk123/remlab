---
workstream: infra/memory
slug: kit-align-v13
title: Апгрейд Memory Bank remlab до кита v1.3.0 (merge-gate, память↔код, захват на ходу, метрики)
status: completed
created: 2026-07-12
updated: 2026-07-12
completed: 2026-07-12
---

## Цель
Довести память remlab с кита **v1.1.0 → v1.3.0**: механические проверки CODE-REF/FROZEN-MEMORY,
CI merge-gate (режим `warn`), захват на ходу (`session-scratch`), пассивные метрики (footprint +
частота находок). Разобрать 2 реальных CODE-REF remlab. Гейт остаётся `warn` (флип в `block` — позже, решение владельца).

## Источник задачи
Промпт владельца: «составь детальный план как довести наш мемори банк remlab до новшеств шаблона».
Кит доведён до v1.3.0 в этой сессии (репо `/home/pakar/igor/memory-bank-template`).

## Предпосылки (сверено 2026-07-12)
- remlab на ките **v1.1.0**; ни одной новинки v1.2–1.3 нет (gate-mode/code-ref-ignore/session-scratch/
  metrics.log/metrics-append.sh/workflow отсутствуют).
- **Все 13 kit-owned файлов remlab не изменены с установки** (сверка с `_kit/manifest.txt`) →
  `upgrade.sh` обновит их начисто, конфликтов `*.kit-new` НЕ будет.
- Реальные CODE-REF на remlab (абсолютные пути `/opt/…`,`/go/`,`/home/…` уже НЕ флагаются в v1.2+):
  1. `core/access-and-integrations.md` — `ads-watchdog/common.py`, реальный путь `infra/server/ads-watchdog/common.py`;
  2. `goals-one-photo-furnish-fit.md` — `mltest/*.py` ×4 (внешняя研究-папка `/home/pakar/mltest`, не репо-код).
- FROZEN-MEMORY: remlab держит память свежей → ожидается чисто.
- Tier 0 remlab ≈ 8.0 KB; Stop-хук проекта уже гоняет audit с `--tier0-max-kb 10`.

## Скоуп — что входит
- `upgrade.sh` (kit-owned → v1.3.0) + повторный `apply.sh` (seed новых project-owned файлов).
- Ручной перенос СМЫСЛА в project-owned правило: захват на ходу в `memory-discipline.md`.
- Разбор 2 CODE-REF: фикс пути ads-watchdog в памяти + `mltest/` в allowlist.
- Пост-проверка: новый audit чисто, `/memory-check`, первая строка метрик, обновить `FLEET.md` кита.

## Скоуп — что НЕ входит
- Флип гейта в `block` и required-check в branch protection — решение владельца, позже.
- A/B-эксперимент по токенам (`EXPERIMENT.md`) — отдельно, с человеком.
- Отложенные #4/#5 (ROADMAP кита).
- Любой продуктовый код remlab.

## Файлы к изменению
**Авто — `upgrade.sh` (kit-owned, чистый апдейт):**
- [ ] `tools/memory-audit.mjs` (CODE-REF/FROZEN-MEMORY + метрики/footprint)
- [ ] `tools/session-reminder.mjs` (нудж при пустом блокноте)
- [ ] `tools/session-freshness.mjs`, `tools/metrics-append.sh` (новый), 3× `.claude/skills/*/SKILL.md`
- [ ] `.memory_bank/METADATA_SCHEMA.md`, `CLEANUP_POLICY.md`, `archive/README.md`, `_secrets/README.md`
- [ ] `.memory_bank/_kit/VERSION → 1.3.0` + `manifest.txt` (пересобирает upgrade)

**Авто — повторный `apply.sh` (seed, no-overwrite):**
- [ ] `.memory_bank/_kit/gate-mode.txt` (= `warn`), `.memory_bank/_kit/code-ref-ignore.txt`
- [ ] `.memory_bank/_intake/session-scratch.md`, `.memory_bank/changelog/metrics.log`
- [ ] `.github/workflows/memory-audit.yml` (отдельный workflow; конфликта с `ci.yml`/`deploy.yml` нет)

**Ручной перенос (project-owned, upgrade НЕ трогает):**
- [ ] `.claude/rules/memory-discipline.md` — добавить пункт «В процессе: 1–2 строки в
      `_intake/session-scratch.md` СРАЗУ» + строку в таблицу «Куда писать» (по образцу кита v1.3.0,
      сохранив специфику remlab). Обновить п.3 цикла: Этап 1 = консолидировать блокнот.
- [ ] `.memory_bank/_kit/code-ref-ignore.txt` — добавить строку-префикс `mltest/`.
- [ ] `.memory_bank/core/access-and-integrations.md` — `ads-watchdog/common.py` →
      `infra/server/ads-watchdog/common.py` (реальный путь); проверить парный `domain/integrations.md`.
- [ ] (опц.) `CLAUDE.md` — в блок «Память и старт» указатель на `session-scratch`.

## Задачи (по порядку)
- [ ] 1. **Бэкап:** `tar` `.memory_bank` + `.claude` + `CLAUDE.md` в `~/backups/remlab-prev13-<дата>.tgz`.
- [ ] 2. **apply повторно:** `bash /home/pakar/igor/memory-bank-template/apply.sh /home/pakar/igor/remlab
      --permission-mode <как в settings>` → сеет новые файлы; проверить, что 6 seed-файлов появились,
      `gate-mode.txt` = `warn`.
- [ ] 3. **upgrade:** `bash /home/pakar/igor/memory-bank-template/upgrade.sh /home/pakar/igor/remlab`
      → убедиться «обновлено N, конфликтов 0», `_kit/VERSION` = 1.3.0.
- [ ] 4. **Ручные переносы** (файлы выше): scratch-правило, `mltest/` в allowlist, фикс пути ads-watchdog.
- [ ] 5. **Аудит:** `node tools/memory-audit.mjs --check --tier0-max-kb 10 .` → CODE-REF/FROZEN пусто;
      footprint-строка печатается (~2%). Остаточное — починить или осознанно в allowlist.
- [ ] 6. **/memory-check** — прогнать (новый Этап 1: блокнот пуст → лёгкий проход; аудит «чисто»).
- [ ] 7. **Метрики:** `tools/metrics-append.sh .` → первая строка footprint в `changelog/metrics.log`.
- [ ] 8. **FLEET.md кита** (локально): строка remlab → v1.3.0 + дата; строка гейта remlab = `warn`.
- [ ] 9. **Выкатка:** ветка `feature/kit-align-v13` → `pnpm typecheck && lint && test && build` зелёные
      → merge в `main` → `git push` (CI прогонит и новый `memory-audit.yml` в режиме warn). **Деплой на
      сервер НЕ нужен** — меняется только память/тулинг/CI, не продуктовый код.

## Критерии приёмки
- [ ] `upgrade.sh` прошёл без `*.kit-new`; `_kit/VERSION` = 1.3.0.
- [ ] Новый audit: CODE-REF и FROZEN-MEMORY чисто (mltest в allowlist, путь ads-watchdog исправлен);
      footprint печатается.
- [ ] Присутствуют: `gate-mode.txt`=warn, `code-ref-ignore.txt` (с `mltest/`), `session-scratch.md`,
      `changelog/metrics.log` (≥1 строка), `tools/metrics-append.sh`, `.github/workflows/memory-audit.yml`.
- [ ] `memory-discipline.md` содержит правило захвата на ходу.
- [ ] `/memory-check` завершён, audit «чисто» (кроме, возможно, TIER0-BLOAT — см. риск).
- [ ] `pnpm typecheck/lint/test/build` зелёные; `main` запушен; workflow memory-audit прошёл (warn).
- [ ] `FLEET.md` кита обновлён.

## Риски / калибровка
- **Tier 0 ≈ 8 KB vs дефолт workflow `--tier0-max-kb 8`:** новый CI-workflow гоняет аудит с дефолтом
  (8), а Stop-хук remlab — с 10. Возможен TIER0-BLOAT как **warn** (гейт=warn НЕ блокирует). Варианты:
  (а) принять предупреждение на время warmup; (б) ужать Tier 0 (`CLAUDE.md`/`INDEX.md`) под 8 KB;
  (в) не форкать kit-owned workflow. Рекомендация: сверить точные байты; чуть за порогом → слегка ужать
  INDEX/CLAUDE, иначе принять warn. Не блокер.
- **upgrade конфликты:** исключены (все хэши совпали с манифестом) — но всё равно проверить вывод.
- **Новый workflow на PR remlab:** в режиме `warn` не может уронить CI. Безопасно.
- **Обратимость:** бэкап (шаг 1) + git-ветка; всё откатываемо.

## Definition of Done
Память remlab на v1.3.0, 2 CODE-REF закрыты, метрики собираются (footprint зафиксирован), гейт warn
работает в CI, план → `completed` + перенос в `completed_plans/` (гейт: `/memory-check` + audit чисто).

## Completion summary (2026-07-12)
Выполнено полностью. `apply.sh` досеял 6 project-owned файлов (gate-mode=warn, code-ref-ignore,
session-scratch, metrics.log, workflow, metrics-append), `upgrade.sh` обновил kit-owned до v1.3.0 —
**0 конфликтов** (все хэши совпали с манифестом): memory-audit.mjs, session-reminder.mjs,
memory-check SKILL.md. Ручные переносы: правило захвата на ходу в `memory-discipline.md`, `mltest/`
(префикс) в allowlist, путь `ads-watchdog/common.py → infra/server/ads-watchdog/common.py`.
Аудит **чист (0 находок)** и на `--tier0-max-kb 10` (Stop-хук), и на дефолте 8 (CI): Tier 0 = 8177 B < 8192.
Footprint Tier 0 = **2.1%** активного корпуса (388 KB); первая строка метрик в `changelog/metrics.log`.
Гейт остаётся `warn`. Не входило: флип в `block`, A/B-эксперимент по токенам, #4/#5. Бэкап:
`~/backups/remlab-prev13-2026-07-12.tgz`. FLEET.md кита обновлён.

**Грабля (CI vs локально):** `tools/` в `.gitignore` remlab («не часть проекта»). Локальный аудит
видит скрипты на диске → чисто; CI на свежем checkout их НЕ видит → CODE-REF флагал 10 `tools/*`
ссылок. Фиксы: (1) `!tools/memory-audit.mjs` — этот скрипт нужен CI-гейту, трекается (zero-dep);
(2) префикс `tools/` в `_kit/code-ref-ignore.txt` — ссылки на локальные тулзы не репо-claim.
Продуктовый код (`app/lib/infra/db`) под CODE-REF остаётся. Проверять enforcement — по CI-прогону
(`git archive HEAD`), а не локальным аудитом: локальный видит гитигнор-файлы. CI-прогон memory-audit
зелёный, 0 находок, footprint 2.1%.
