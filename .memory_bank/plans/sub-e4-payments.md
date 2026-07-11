---
workstream: commercial
slug: sub-e4-payments
title: "Э4 Монетизация: YooKassa, тарифы 1490/9900, entitlements"
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

## Цель
Демо-оплату (490 ₽, `unlockPack`) заменить на реальные деньги: YooKassa 1490 ₽,
заявка-концьерж 9900 ₽, entitlements как источник прав, чеки 54-ФЗ.

## Источник задачи
Этап Э4 мастер-плана [[commercial-master-plan]].

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md` (строка Э4) + `.memory_bank/guides/execution-playbook.md` + `docs/master-brief-v0.3.md`.
- Демо-код: `app/actions.ts` стр. 94–98 (`unlockPack`); `app/p/[id]/paywall/page.tsx` (`PRICE = 490`); `app/p/[id]/preview/page.tsx` стр. 78 (locked уходят в HTML); `modules/ideas/index.ts`.
- `lib/analytics.ts` — `EventName`/`track()`, `paywall_viewed` не отправляется; `lib/env.ts` (`providerEnvSchema`) + `.env.example` стр. 23–24 (`YOOKASSA_SHOP_ID`/`YOOKASSA_SECRET_KEY` закомментированы).

## Скоуп — что входит
- 1490 через YooKassa (redirect); entitlements = права; истина оплаты — только webhook; серверный enforcement подбора.
- 9900 = заявка + уведомление, руками; 54-ФЗ на ЮKassa; runbook возвратов; события PostHog.

## Скоуп — что НЕ входит
- Подписки; Cost Engine/PDF-сметы; автоматизация возвратов (только runbook).
- Аккаунты/magic-link — Э3 (`sub-e3-foundation`): потребляем, не строим.

## Файлы к изменению
- [ ] (новый): `modules/payments/yookassa.ts`, `modules/payments/entitlements.ts`, `app/api/payments/yookassa/route.ts`, `db/init/004-payments.sql`, `tests/unit/payments.test.ts`, `.memory_bank/core/payments.md`, `.memory_bank/guides/payments-runbook.md`.
- [ ] Правки: `tools/migrate.mjs`, `db/schema.ts`, `lib/env.ts`, `.env.example` (раскомментировать, без значений), `app/actions.ts`, `app/p/[id]/paywall/page.tsx`, `app/p/[id]/preview/page.tsx`, `lib/analytics.ts`.

## Задачи
**Блок 0.** Э3 смерджен (`user_id` в actions)? Нет → СТОП, эскалация. WebFetch актуальных доков ЮKassa (платёж, webhook, подлинность, receipt); способ проверки → ADR в `decisions.md`. Дефолт: контрольный GET `/v3/payments/{id}`, телу уведомления не доверять.

**Блок 1 — БД.** `payment_events` (id uuid, payment_id text+индекс, event_type, raw jsonb NOT NULL, processed bool=false, created_at) — raw пишем ДО обработки. `entitlements` (id, user_id NOT NULL, type=`room_pack_1490`, project_id, source_payment_id text UNIQUE — идемпотентность, granted_at). `premium_leads` (id, user_id, project_id, name, contact, created_at). DDL: `004-payments.sql` + `migrate.mjs` (`create table if not exists`) + `db/schema.ts`.

**Блок 2.** `createPayment(...)` → POST `/v3/payments`: Basic-auth из env, `Idempotence-Key` (UUID, обязателен), `capture: true`, redirect-confirmation с `return_url`, `metadata: {user_id, project_id, tariff}`, `receipt` (предмет расчёта, НДС, email; параметры — владелец, до подтверждения TODO). Ответ через Zod → `confirmation_url`, `payment_id`. `getPayment(id)` — GET статуса. `grantEntitlement` — INSERT `on conflict (source_payment_id) do nothing`; `hasEntitlement(userId, type, projectId?)`. Секреты в логи/трейсы не писать.

**Блок 3 — webhook.** POST: raw → `payment_events`; парс Zod; подлинность контрольным GET; `succeeded` → grant по `metadata`; `processed=true`; 200. Ошибка после raw → 500 (ЮKassa ретраит). Там же `track("purchase_completed")`; `paid: true` — производная от entitlement. Redirect на `return_url` прав НЕ выдаёт: страница «проверяем оплату», права — из БД.

**Блок 4 — UI/enforcement.** `unlockPack` → создать платёж + redirect на `confirmation_url` + `purchase_initiated`; судьбу `pack_unlocked` зафиксировать. Хелпер видимости рядом с `buildCatalog()`/`FREE_VISIBLE`: без entitlement — открытые + счётчик; с entitlement — всё. Починить preview (стр. 78). Paywall: карточки 1490/9900, `paywall_viewed`, демо-тексты убрать.

**Блок 5 — 9900.** Форма (имя, контакт, проект) → `premium_leads` + письмо владельцу транспортом Э3 (нет — запись + `premium_lead`, письмо руками); без онлайн-оплаты.

**Блок 6 — runbook.** Найти платёж в кабинете → возврат (чек делает ЮKassa) → отозвать entitlement (пометить, не удалять) → снять `paid` → лог. Плюс «оплатил, а доступа нет»: `payment_events` → статус в API → grant руками.

**Блок 7 — тесты.** Unit: двойной webhook → один entitlement (мок GET); `canceled` → без entitlement; кривое тело → raw записан, 4xx/5xx. Фейк-платежи по паттерну `REMLAB_FAKE_AI` (`lib/providers/fake.ts`, `lib/providers/index.ts`) — `pnpm e2e` без сети. Sandbox руками, сценарий в runbook; в CI не гонять.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` и `pnpm e2e` — зелёные.
- [ ] Два одинаковых POST `payment.succeeded` на `/api/payments/yookassa` (curl + мок статуса) → в `entitlements` ровно 1 строка.
- [ ] Подбор без entitlement / чужим → без locked в теле. Sandbox: оплата 1490 → entitlement, полный подбор, чек.
- [ ] Бизнес-gate (после выката): ≥10 оплат 1490; конверсия ≥1–2%; refund <15%. Kill: <0.5% → цена/граница (владелец); 9900 не берут → премиум из роадмапа.

## Чекпоинты владельца
- ⏸ Владельцу (до кода): таблица настроек ЮKassa (параметр → что выбрать → зачем): договор, shopId, фискализация, чек. «Подтверди — без этого платежи не включаем».
- ⏸ Владельцу: скрин paywall 1490/9900. «Цены и тексты — ок?»
- ⏸ Владельцу: sandbox-покупка от клика до чека. «Путь покупателя — ок?»
- ⏸ Владельцу (перед продом): runbook возвратов. «Сможешь сам сделать возврат?»
- ⏸ Владельцу (2–4 нед. после выката): конверсия/оплаты. «Gate ≥1–2% или kill?»

## Если пошло не по плану
- **Э3 не готов** → fallback на session_id НЕ городить → эскалация владельцу.
- **Webhook не доходит** → логи Caddy, curl снаружи, статик-роуты. Fallback: опрос статуса через API на `return_url`. `remnanode` не трогать.
- **401/400 на платёж / чек не формируется** → env на сервере, боевые/тестовые креды, receipt/фискализация. Договор, налоги, юридика — владелец.
- **2 entitlement** → UNIQUE + `on conflict`, grant в транзакцию; дубль гасить по runbook.
- **Конверсия ниже kill** → кодом не чинить; решает владелец («Решения человека», CLAUDE.md).

## Критерии приёмки
- [ ] Гейты зелёные; секретов в git/логах нет; runbook подтверждён владельцем.
- [ ] Redirect назад без webhook доступ НЕ открывает.
- [ ] Заявка 9900 → запись + уведомление; 4 события PostHog отправляются.
- [ ] Демо-код удалён: `PRICE = 490`, «(демо)», «Демо-режим», «Оплата — заглушка», безусловный `paid: true`.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] `core/payments.md` (видна в INDEX); `core/access-and-integrations.md` — ЮKassa; `decisions.md` — ADR «истина оплаты = webhook + контрольный GET»; `project-state.md` переписан.
- [ ] `/memory-check` выполнен, audit «чисто»; статус обновлён в [[commercial-master-plan]].

## Лог выполнения
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- [ ] Онлайн-оплата 9900; автоматизация возвратов; e-mail покупателю (Э7); `project.paid` → чистая производная от entitlements.
