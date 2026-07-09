---
workstream: memory-bank
slug: kit-align
title: Приведение remlab к киту v1.1.0 (по HEAL.md, эталон sup2)
status: completed
created: 2026-07-09
updated: 2026-07-09
completed: 2026-07-09
---

## Цель
Кит v1.1.0 в remlab: enforcement (хуки/гейт/аудит), сводки в бюджетах, снимок вместо журнала,
мост авто-памяти. Структура уже правильная — лечение без переезда.

## Источник задачи
Команда владельца «то же самое по remlab» (чат 2026-07-09). Конвейер — `HEAL.md` кита.

## Разведка (2026-07-09)
- ✅ Структура канонична: одна папка `/home/pakar/igor/remlab` = код (Next.js, pnpm) + `.memory_bank`
  (48 md, 492K) + git с GitHub (igortsk123/remlab). Переезд НЕ нужен.
- `remlab-temp` — артефакты экспериментов (картинки/отчёты), НЕ банк — вне скоупа, не трогаем.
- Аудит v1.1: 12 проблем — BLOATED ps 15KB; TIER1-BLOAT ×6 (goals-док 19.5KB!); TIER0 12.5KB;
  реестры без GENERATED-маркеров. Планов-зомби и NO-TIER1 нет (свежий проект).
- Settings: autopilot, hooks нет. Авто-память: 3 файла (communication-style — per-user;
  user-location-market — проектный контекст → в банк).
- Кит = v0 (старые tools/скиллы).

## Этапы
- [ ] 0. Бэкап банка+.claude в ~/backups/
- [ ] B. Кит: upgrade.sh (конфликты *.kit-new разобрать: чистый старый шаблон → принять кит) →
      apply.sh (hooks/gitignore-блок/_secrets/_kit/project-history) → project-owned: гейт в
      agent-workflow+CLAUDE.md, memory-discipline v1.1, DoD+title в plans/_template,
      GENERATED-маркеры реестров → audit write-mode
- [ ] C. Рехидратация-лайт (проект свежий, код не разошёлся с памятью сильно):
      ужать 6 раздутых сводок ≤3KB (детали → Tier 2, goals-док 19.5KB → tier:2 или разнести);
      project-state 15KB → снимок + changelog/project-history; Tier 0 ≤8KB;
      мост: user-location-market → банк (+mirrored), communication-style — per-user остаётся
- [ ] D. Верификация-компакт: факт-чек core/* против кода + drill 3 вопроса; фиксы
- [ ] E. Аудит «чисто», коммиты+push (секрет-гард!), FLEET.md кита, план → completed

## Критерии приёмки
- [ ] `node tools/memory-audit.mjs .` — «проблем не найдено»; кит v1.1.0 в `_kit/VERSION`
- [ ] Хуки Stop+SessionStart активны; гейт в правилах
- [ ] Drill-тест: ключевые вопросы отвечаются за ≤2 перехода
- [ ] Всё запушено в GitHub; секреты не в git

## Лог выполнения
- 2026-07-09 — разведка выполнена, план создан, исполнение начато (команда «то же самое»)

## Completion summary
Выполнено 2026-07-09. Кит v1.1.0 (7 .kit-new = чистый старый шаблон, приняты; кастомная секция
«Выкатка» слита с новым правилом). Рехидратация: 6 сводок ужаты в ≤3KB (детали → 6 новых Tier-2),
goals-док 19.5KB → tier-2 + сводка core/goals; project-state 15KB → снимок 8KB + project-history;
мост авто-памяти (market-контекст → банк). Верификация: 229 утверждений, 12 wrong + 16 outdated —
ГЛАВНОЕ: architecture/data-model описывали спеку как реальность (Inngest/8 модулей/RLS/Drizzle-
миграции не существуют) — переписаны ОТ КОДА, целевое помечено «спека — НЕ реализовано»; 40 фиксов.
Drill 3/3 (≤1 drill). Аудит: 12 → 0 (Tier 0 9.8KB, порог 10). Продукт-находки владельцу:
PgRepository.get(id) без проверки сессии; RLS нет; генерация синхронна без ретраев; оплата заглушка
(490 ₽ демо vs 2 990 ₽ бриф); fit-check v1 живёт в /home/pakar/mltest ВНЕ репо.
