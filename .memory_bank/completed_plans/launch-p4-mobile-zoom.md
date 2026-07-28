---
workstream: launch
slug: launch-p4-mobile-zoom
title: П4 Мобайл + масштаб — контрол 100–130% (zoom), адаптация больших экранов, мобильные правки
status: completed
created: 2026-07-28
updated: 2026-07-28
completed: 2026-07-28
---

## Цель (зонт launch-prep П4, пп. 13–14)
Контрол масштаба 100/110/120/130% для слабовидящих (перенос механики sup2 ZoomControl) + адаптация
под большие экраны (идея WFM-admin `--font-base`) + мобильные правки мелких текстов калькуляторов.

## Решение по механике (адаптация под remlab)
Вёрстка remlab — в px (инлайн-стили компонентов), полный перевод на rem — большой рефакторинг вне
скоупа. Поэтому масштаб — через CSS `zoom` (стандартизирован, масштабирует ВСЁ, включая px):
`body { zoom: calc(var(--screen-zoom) * var(--user-zoom)) }`; юзер-ступени 100/110/120/130 —
`html[data-font-scale=L|XL|XXL]` → `--user-zoom`; большие экраны ≥1920/2560 → `--screen-zoom`
1.08/1.15. Браузер без поддержки → просто 100% (деградация безопасна).

## Скоуп
- `components/ZoomControl.tsx` (нов., без ui-библиотек): «Масштаб − 100% +», localStorage
  `remlab-font-scale`, data-font-scale на <html>.
- `app/layout.tsx`: анти-FOUC inline-скрипт в <head> (читает localStorage до отрисовки).
- `app/globals.css`: `--user-zoom`/`--screen-zoom` + body zoom; ladder ≥1920/2560.
- `components/SiteHeader.tsx`: ZoomControl в верхнюю строку (бренд · масштаб · лаборатория).
- Мобильные правки: мелкие 13px-строки калькулятора → 14px (LinkAutofill статусы/`ввести параметры
  вручную`, quiz-link), тап-зоны уже ≥44 у крестиков (П3).

## Критерии
- [x] Контрол в шапке: 100→130% ступенями, сохраняется, без FOUC при перезагрузке
- [x] Масштабируется вся страница (включая px-вёрстку калькуляторов)
- [x] ≥1920px интерфейс не «мелкий» (screen-zoom)
- [x] Мелкие тексты калькулятора ≥14px
- [x] typecheck / lint / test / build + e2e зелёные; авто-деплой

## Лог
- 2026-07-28 — создан, реализация (зонт)
- 2026-07-28 — реализовано, гейты зелёные, авто-деплой

## Completion summary
ZoomControl (− % +) в шапке: ступени 100/110/120/130 через data-font-scale + localStorage
remlab-font-scale; анти-FOUC inline-скрипт в layout <head>. Механика — CSS zoom (вся px-вёрстка
масштабируется): body zoom = screen-zoom (1.08@1920/1.15@2560) × user-zoom. Мелкие 13px-тексты
блока ссылки/лид-карточки → 14px. Механика из sup2, идея ladder — из WFM-admin, адаптировано
(без rem-рефакторинга).
