---
workstream: ui
slug: design-polish-p1
title: Дизайн-полировка после UUI-миграции — цвета/бейджи/шрифты/тени (по скринам)
status: completed
created: 2026-07-31
updated: 2026-07-31
completed: 2026-07-31
---

## Цель
Убрать разнобой оттенков и мелкие UX-дефекты, найденные скрин-ревизией моб+веб после
миграции на Untitled UI (план `uui-migration`).

## Источник задачи
Владелец: «проанализируй компоненты, цвета/оттенки пляшут, посмотри как дизайнер, поправь».

## Скоуп — что входит
1. `.note` → нейтральная (bg-secondary/border-secondary): подсказка ≠ предупреждение; бренд-тинт
   остаётся только у `.lead-card`; баннер «✓ Сохранено» на `/e/[id]` — success-тинт.
2. Бейдж «скоро» — ЕДИНЫЙ стиль: строчные, slate-пилюля (Badge sm); шапка — нейтральная пилюля
   без капса (на тёмной CTA — полупрозрачно-белая, тоже строчными).
3. Шапка: второй CTA «Сколько стоит ремонт» — тинт brand-100/brand-800 (не конкурирует с главным).
4. Поля ввода ≥16px (iOS-автозум): NumInput text-md; NativeSelect/Input size md в калькуляторах и модалке.
5. Тени карточек мягче (--shadow).

## Скоуп — что НЕ входит
Иконки (emoji vs PNG — ассеты владельца), редизайн флоу, тексты.

## Файлы к изменению
- [x] `app/globals.css` — .note, .nav-cta--alt, --shadow
- [x] `app/page.tsx`, `app/lab/page.tsx`, `components/lab/MyStyleCard.tsx`, `components/SiteHeader.tsx` — бейджи
- [x] `app/e/[id]/page.tsx` — success-баннер
- [x] `components/calc/NumInput.tsx`, `components/calc/MaterialParams.tsx`, `components/calc/LinkAutofill.tsx`, `components/calc/LeadModal.tsx` — 16px

## Критерии приёмки
- [x] typecheck/lint/test/build зелёные; e2e в CI
- [x] Повторные скрины моб+веб: тинт один (lead-card), бейджи единые, поля 16px

## Definition of Done — память
- [x] Заметка в scratch (консолидируется следующим /memory-check); новых уроков нет (№16 покрывает)

## Лог выполнения
- 2026-07-31 — создан по скрин-ревизии, сразу in_progress (разрешение «подряд»)

## Completion summary
5 фиксов по скрин-ревизии применены и проверены повторными скринами (моб 390 / веб 1280):
нейтральная .note, единые бейджи «скоро», тинт-CTA в шапке, поля 16px (iOS), мягче тени.

### Уроки
Без отклонений (принцип «один цветовой акцент на страницу» — применение существующей системы).
