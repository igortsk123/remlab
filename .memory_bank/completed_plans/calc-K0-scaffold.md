---
workstream: calc-materials
slug: calc-K0-scaffold
title: К0 — Каркас калькулятора v2 (контракты + локальное состояние + мультикомната)
status: completed
created: 2026-07-12
updated: 2026-07-12
completed: 2026-07-12
---

## Цель
Фундамент калькулятора v2: Zod-контракты проекта расчёта, клиентское состояние с сохранением
локально в сессии (localStorage) и мультикомнатный каркас (добавить/переименовать/удалить/выбрать
комнату). Под флагом `CALC_V2` — прод-путь не меняется. Формул/результата пока нет.

## Источник задачи
Роадмап `plans/calc-materials-roadmap.md` (фаза К0), шаги 1–2 сценария (выбор типа расчёта; данные
локально в сессии; «Комната 1» по умолчанию + добавить/удалить/редактировать).

## Скоуп — что входит
- **`contracts/calc.ts`** (Zod): `CalcKind` (обои/плитка/краска/ламинат), `Opening` (окно/дверь/
  прочее: ширина×высота, count), `Surface` (метка, длина, высота, openings[]), `Zone` (метка,
  длина, ширина), `Floor` (длина, ширина, extraZones[], excludedZones[]), `MaterialSpec`
  (дискриминированный юнион по виду — поля-каркас, детально в К2), `Room` (id, name, kind,
  surfaces? | floor?, material?, productUrl?), `CalcProject` (version, kind, rooms[], updatedAt).
  Типы через `z.infer`.
- **Локальное состояние в сессии:** `lib/calc/storage.ts` — верс'ионированные load/save/clear в
  localStorage (client-only guard, миграция по `version`). `components/calc/useCalcProject.ts` —
  хук: state + CRUD комнат (add/rename/duplicate/remove/select), автосейв в storage.
- **Каркас билдера:** `components/calc/CalcBuilder.tsx` — список/табы комнат, «+ Комната», выбор
  активной, переименование/удаление; активная комната = плейсхолдер (геометрия — К1). Пустые состояния.
- **Флаг:** `lib/calc/flag.ts` — `isCalcV2(searchParams, env)` (`?v2=1` или `CALC_V2=1`).
  `app/calc/[kind]/page.tsx` — рендер `CalcBuilder` под флагом, иначе текущий `CalcForm` (дефолт).
- Тест: `tests/unit/calc-state.test.ts` — чистая логика CRUD комнат (add/rename/remove/select).

## Скоуп — что НЕ входит
- Формулы, геометрия проёмов/зон, параметры материалов, экран результата, сохранение в смету
  (К1–К3). Автозаполнение по ссылке, услуги (К4–К6). Прод-дефолт калькулятора НЕ меняем.

## Файлы к изменению
- [ ] `contracts/calc.ts` — новые Zod-контракты (полная форма, поля материала — каркас).
- [ ] `lib/calc/storage.ts` — localStorage-персист (версионируемый).
- [ ] `lib/calc/flag.ts` — флаг `CALC_V2`.
- [ ] `components/calc/useCalcProject.ts` — клиентский хук состояния + CRUD.
- [ ] `components/calc/CalcBuilder.tsx` — каркас билдера (комнаты).
- [ ] `app/calc/[kind]/page.tsx` — рендер v2 под флагом, иначе текущая форма.
- [ ] `tests/unit/calc-state.test.ts` — тесты CRUD комнат.

## Задачи
- [ ] Контракты + типы; плоская, версионируемая схема.
- [ ] Persist в localStorage (переживает перезагрузку вкладки), client-only.
- [ ] Хук состояния + CRUD комнат; билдер-каркас; пустые состояния.
- [ ] Флаг-гейт на роуте; текущий калькулятор не тронут.
- [ ] typecheck/lint/test/build зелёные.

## Критерии приёмки
- [ ] Под `?v2=1` можно завести 2–3 комнаты, переименовать/удалить; данные переживают перезагрузку.
- [ ] Без флага — прежний калькулятор работает как раньше (нет регресса).
- [ ] Только семантические токены; нет отладочного вывода; файлы вне scope не задеты.

## Definition of Done — память
- [ ] `core/estimate.md` — отметить калькулятор v2 (каркас, флаг, локальное состояние).
- [ ] `core/architecture.md` — новые `contracts/calc.ts`, `lib/calc/*`, `components/calc/*`.
- [ ] `decisions.md` — ADR: калькулятор v2 = клиентское локальное состояние + мост в смету позже.
- [ ] `/memory-check`, audit «чисто».

## Лог выполнения
- 2026-07-12 — план создан (draft).
- 2026-07-12 — реализовано, проверки+смоук зелёные, память обновлена → completed.

## Completion summary
Сделано: `contracts/calc.ts` (Zod — проект/комната/поверхность/проём/зона/пол/параметры материала),
`lib/calc/state.ts` (чистый CRUD комнат, покрыт `tests/unit/calc-state.test.ts`), `lib/calc/storage.ts`
(localStorage по виду, версионируемый), `lib/calc/flag.ts` (`CALC_V2`/`?v2=1`),
`components/calc/useCalcProject.ts` (клиентский хук), `components/calc/CalcBuilder.tsx` (мультикомната:
табы + добавить/переименовать/удалить), `app/calc/[kind]/page.tsx` (v2 под флагом, иначе прежняя форма).
Проверки: typecheck/lint/test(37)/build зелёные; смоук — default /calc/oboi без регресса, `?v2=1` рендерит
билдер. Память: ADR-0018 (архитектура всей серии), `core/estimate.md`, `core/architecture.md`.
Упрощено: под флагом v2 SSR отдаёт «Загрузка…», билдер гидрируется на клиенте (localStorage только там).

## Follow-up
- [ ] К1 — геометрия и площади.
