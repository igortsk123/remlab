---
workstream: product
slug: onb-11-flat3d-rooms
title: onb-11 — /flat: все комнаты в 3D-конфигураторе (мост спальни и кухни), UK-двойник
status: draft
created: 2026-11-05
updated: 2026-11-05
completed:
plan_kind: sub
parent_plan: onb-00-quiz-master
---

## Цель
Покупатель в 3D-конфигураторе `/flat` видит не только гостиную, но и спальни и кухню с теми же вариантами, что в `/demo`; в EN-версии
то же с маской UK. Сейчас мост `lib/configurator/fromDemo.ts` жёстко собирает `roomId: "living"` (`:245`, `:308`, `:359`).

## Источник
Метаплан `onb-00`; ADR-0330 (`room_type`, наборы по комнатам); `core/apartment-configurator.md`, `domain/flat3d-configurator.md`;
наборы мебели kits — `lib/viewer3d/kits/bedroom.ts`, `lib/viewer3d/kits/kitchen.ts`.

## Скоуп — входит
- Мост: слоты и цены по `room_id` из демо-данных для всех комнат с флагом `enabled`; итог по комнатам и общий бюджет (ADR-0308).
- Спальни: мебель вариантов из `onb-06/10`; кухня: опции `onb-09` через `kits/kitchen.ts`.
- UK: `data/partners/demo-uk.json` — те же комнаты, маска ADR-0328 (курс × маска, без магазинов РФ).
- Живые проверки `/flat` RU/UK: телефон 375×667 и компьютер; тесты моста по каждой комнате.

## Скоуп — не входит
Новые kits (Г/П-кухня — в `onb-09`, если понадобится); правка расстановки.

## Файлы
- `lib/configurator/fromDemo.ts` (+ тесты рядом), `data/partners/demo-uk.json` — по одному писателю после `onb-07`/`onb-09`

## Критерии приёмки
- [ ] Каждая клетка матрицы ADR-0330 для `/flat` — как в матрице
- [ ] Гостиная `/flat` без регресса (тесты и снимки до/после)
- [ ] Ведущий посмотрел RU/UK на телефоне и компьютере

## Оценка
3–4 дня после `onb-07` и `onb-09`.

## Definition of Done — память
- [ ] `core/apartment-configurator.md` + Tier 2; аудиты чисты

## Правки по общей проверке Codex 05.11 (главнее текста выше)
- Срок 6–10 дней. Единственный писатель `lib/configurator/fromDemo.ts`.

## Лог выполнения
- 2026-11-05 — черновик (ведущий) по Codex.
