---
tier: 1
topic: manager-links
scope: Ссылка от менеджера застройщика покупателю, сигналы менеджеру, его страница и бот
tier2: "../domain/manager-links.md"
updated: 2026-10-14
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-13
review_after: 2026-12-13
---

# Ссылка от менеджера — Tier 1 (план b2b-02, ADR-0257)

## Что это
Менеджер застройщика после показа делает ссылку покупателю на его квартиру — в Telegram-боте
(«Новая ссылка» → заметка «Вася, после показа» → ссылка ответом) или на своей странице
`/manager#<ключ>`. Покупатель открывает `/demo/?s=<id>`, видит карточку менеджера, кнопки
«консультация»/«ипотека» ведут к менеджеру в WhatsApp/Telegram/звонок с готовым текстом,
«хочу другой вариант» — причина из списка. Менеджеру приходят сигналы, статусы ставит он.

## Главное
- **Данных покупателя нет:** заметка менеджера живёт в его чате/браузере; храним только id сообщения
  (`sends.origin_message_id`), сигналы идут ответом на него (`modules/sends/dispatch.ts`).
- **Ключи — 128 бит** (`lib/token.ts`); ключ менеджера — во #фрагменте, Метрика на `/manager` выключена
  (`app/layout.tsx`, `components/MetrikaPageviews.tsx`).
- **Статусы:** `sent→opened→engaged` ставит система, `contacted/meeting/deal/lost` — только менеджер
  (`contracts/send.ts:autoAdvanceAllowed`, `modules/sends/service.ts:setStatusByManager`).
- **Антишум:** «открыл» раз в сутки, выбор — сводкой через 30 мин, дедуп кликов 2 мин, 20 сигналов/час
  (`modules/sends/service.ts`). Доставка — очередь `signal_outbox` с повторами, таймер `remlab-signals`
  раз в минуту; нет бота — `no_channel`, видно на странице менеджера.
- Словарь событий — `contracts/send.ts:buyerEventKind` (`b2b-03`; `flat3d_open` — без сигнала).
  Отчёт застройщику по этим событиям — ADR-0265.

## Код
`contracts/send.ts` · `modules/sends/*` · `app/api/sends/*`, `app/api/manager/*`, `app/api/manager-bot`,
`app/api/internal/signals/flush` · `app/manager/page.tsx` + `components/manager/*` · блок «ССЫЛКА ОТ
МЕНЕДЖЕРА» в `tools/scout/flat215-demo/index.html` · SQL `db/init/014-sends.sql` · заведение менеджера —
`infra/server/manager-add.sh` · тесты `tests/unit/sends.test.ts`.

## Сегодня
Бот не подключён — нет токена (⚑ владелец); заведён `demo-test`. Квартира одна (`flat215`, реестр
`modules/sends/apartments.ts` до `b2b-06`). API для CRM — только описание `docs/partner-api.md`.
