---
tier: 1
topic: manager-links
scope: Ссылка от менеджера застройщика покупателю, сигналы менеджеру, его страница и бот
tier2: "../domain/manager-links.md"
updated: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-05
review_after: 2026-12-13
---

# Ссылка от менеджера — Tier 1 (план b2b-02, ADR-0257)

## Что это
Менеджер делает ссылку покупателю — в Telegram-боте («Новая ссылка» → заметка → ссылка ответом) или на странице
`/manager#<ключ>`. Покупатель открывает `/demo/?s=<id>`: карточка менеджера (ушедший не показывается), «консультация»/«ипотека» —
окно с заполненными каналами (WhatsApp/Telegram с готовым текстом, звонок — номер), «хочу другой вариант» — причина из списка
(блок «ССЫЛКА ОТ МЕНЕДЖЕРА» в `tools/scout/flat215-demo/index.html`). Менеджеру — сигналы, статусы ставит он.

## Главное
- **Данных покупателя нет:** заметка — в чате/браузере менеджера; храним id сообщения и чата (`sends.origin_*`); сигнал —
  ответом на заметку, если чат тот же (`modules/sends/dispatch.ts`).
- **Ключи — 128 бит** (`lib/token.ts`), ключ менеджера — во #фрагменте; Метрики на `/manager` нет (`lib/metrika.ts:noMetrikaPath`).
- **Статусы:** `sent→opened→engaged` — система, `contacted/meeting/deal/lost` — только менеджер
  (`contracts/send.ts:autoAdvanceAllowed`, `modules/sends/service.ts:setStatusByManager`).
- **Антишум** (`modules/sends/service.ts`): «открыл» — раз в сутки; выбор — сводкой через 30 мин; дубль клика — 2 мин;
  `quiz_done` — сразу, повтор раз в 30 мин; `selection_send` — сразу; 20 сигналов/час на менеджера. Доставка — очередь
  `signal_outbox` с повторами, таймер `remlab-signals` раз в минуту; нет бота или подключения — `no_channel`, видно на странице.
- Словарь событий — `contracts/send.ts:buyerEventKind` (`flat3d_open` — без сигнала); отчёт застройщику — ADR-0265.

Код, таблицы, API и заведение менеджера — [[manager-links-details]] (Tier 2).

## Сегодня
Бот работает, только если заданы `MANAGER_TG_TOKEN` и `MANAGER_TG_WEBHOOK_SECRET` (`app/api/manager-bot/route.ts`).
Прод (по коду не проверяется): токена не было (⚑ владелец), заведён `demo-test`. Квартиры — из [[partners]]; бот даёт ссылку,
лишь если у застройщика одна квартира. API для CRM — только описание `docs/partner-api.md`.
