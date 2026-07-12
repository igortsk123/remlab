---
workstream: calc-materials
slug: calc-K6-find-cheaper
title: К6 — «Найти дешевле» + лид-магнит (email / Telegram / MAX)
status: draft
created: 2026-07-12
updated: 2026-07-12
completed:
---

## Цель
Кнопка «Найти дешевле»: если ссылка на товар уже есть — используем её, иначе просим добавить.
Система ищет аналог/скидки/спецпредложения. Результат открывается за лид: e-mail / подписка на
Telegram-бота / подписка на бота в MAX.

## Источник задачи
Роадмап `plans/calc-materials-roadmap.md` (К6), шаг 6 сценария («найти дешевле» + лид-гейт).

## Скоуп — что входит
- **`components/calc/FindCheaper.tsx`** — кнопка/поток: есть `productUrl` → авто; нет → добавить
  ссылку; запуск поиска, состояния loading/empty/error.
- **`lib/calc/find-cheaper.ts`** — поиск аналога/скидок (MVP: источник по решению владельца; правило
  доверия — «подберём дешевле, даже если магазин без нашей партнёрки»). Возврат: варианты дешевле + где.
- **Лид-гейт:** `components/LeadGate.tsx` — открыть результат за e-mail / подписку Telegram / MAX.
  `app/api/lead/route.ts` — приём лида (email/канал/subid), запись. `db/init/00X-leads.sql` +
  `db/schema.ts` — таблица `leads`.
- **Интеграции ботов:** `lib/integrations/telegram-bot.ts`, `lib/integrations/max-bot.ts` — deeplink
  подписки + проверка подписки (webhook/поллинг). Ключи — в `.env`.
- **ПДн:** e-mail/подписка = персональные данные → согласие/политика — **TODO (юрист), не блокируемся**
  (CLAUDE.md); в MVP — минимально необходимый сбор + чекбокс согласия-заглушка.

## Скоуп — что НЕ входит
- Полноценный движок сравнения цен по всем площадкам (MVP-эвристика/источник).
- Реализация юр. логики ПДн/152-ФЗ (только TODO + место под согласие).

## Файлы к изменению
- [ ] `components/calc/FindCheaper.tsx` — поток «найти дешевле».
- [ ] `lib/calc/find-cheaper.ts` — поиск аналога/скидок.
- [ ] `components/LeadGate.tsx` — гейт e-mail/Telegram/MAX.
- [ ] `app/api/lead/route.ts` — приём/запись лида.
- [ ] `lib/integrations/telegram-bot.ts`, `lib/integrations/max-bot.ts` — подписки.
- [ ] `db/init/00X-leads.sql` + `db/schema.ts` — таблица лидов.
- [ ] `.env.example` — токены ботов.

## Задачи
- [ ] Поток «найти дешевле» (ссылка есть/нет), поиск-MVP.
- [ ] Лид-гейт (email + ≥1 бот), запись лида, subid-атрибуция.
- [ ] Интеграции Telegram/MAX (deeplink + проверка подписки).
- [ ] TODO по ПДн зафиксирован; typecheck/lint/test/build зелёные.

## Критерии приёмки
- [ ] «Найти дешевле» использует существующую ссылку или просит добавить; выдаёт варианты.
- [ ] Лид фиксируется; e-mail/подписка открывает результат; секреты не в git.
- [ ] Без ключей ботов — понятная деградация (не падает).

## Definition of Done — память
- [ ] `core/access-and-integrations.md` — Telegram/MAX боты, поиск дешевле (где ключи, эндпоинты).
- [ ] `core/data-model.md` + `domain/*` — таблица `leads`.
- [ ] `decisions.md` — ADR: лид-магнит (email/TG/MAX) + правило доверия «дешевле».
- [ ] `/memory-check`, audit «чисто».

## Решения владельца / открытые
- Обязательные каналы лида (email и/или Telegram и/или MAX); MAX-бот — новая интеграция.
- Источники поиска «дешевле» и глубина MVP. ПДн/согласие — юрист.

## Лог выполнения
- 2026-07-12 — план создан (draft).

## Completion summary
[при completed]

## Follow-up
- [ ] После серии: обновить `core/estimate.md` итогово; связать с M6/M7 роста.
