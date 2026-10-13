---
tier: 2
topic: manager-links-details
scope: Детали ссылки от менеджера — таблицы, ручки, бот, активация, проверка
tier1: ../core/manager-links.md
updated: 2026-10-13
importance: med
source: manual
---

# Ссылка от менеджера — детали (план b2b-02, ADR-0257)

## Таблицы (`db/init/014-sends.sql`)
- `managers` — сотрудники застройщика: публичные контакты (`public_phone/telegram/whatsapp`) отдельно от
  `connect_phone` (номер для привязки бота), `tg_user_id/tg_chat_id`, `page_key` (128 бит), `active`.
- `sends` — ссылка: квартира, менеджер, язык/рынок, `status`, `created_via` bot|page|crm,
  `origin_chat_id/origin_message_id`, `revoked`, `opened_at`, `open_signal_at`, `summary_due_at`.
- `send_events` — действия покупателя и смены статуса `{from,to,by}`.
- `signal_outbox` — сигналы: pending → sent | failed | no_channel; повтор 1/5/15/60 мин.
- `tg_updates` — обработанные `update_id` (Telegram повторяет вебхук).

## Ручки
| Ручка | Кто | Защита |
|---|---|---|
| `GET /api/sends/<id>` | демо покупателя | лимит 60/мин с адреса, 404 для неизвестной/отозванной |
| `POST /api/sends/<id>/event` | демо | только события покупателя (zod), 120/10 мин; сигнал — `after()` |
| `GET /api/manager`, `POST /api/manager/sends[/<id>]` | страница менеджера | заголовок `x-manager-key` |
| `POST /api/manager-bot` | Telegram | `MANAGER_TG_TOKEN` + `MANAGER_TG_WEBHOOK_SECRET`, иначе 401 |
| `POST /api/internal/signals/flush` | таймер | `INTERNAL_API_TOKEN`, снаружи 404 |

## Бот (`modules/sends/bot.ts`)
Только личный чат. `/start` → «поделиться номером» (`request_contact`); принимается только СВОЙ контакт
(`contact.user_id == from.id`), номер нормализуется (`modules/sends/phone.ts`) и ищется в `connect_phone`
(ровно один). «Новая ссылка» → просьба заметки с `force_reply`; ответ на неё = отправка, ссылка приходит
ответом на заметку с кнопками статуса. Кнопки (`callback_data st:<id>:<status>`) работают только у
владельца ссылки. Прочий текст — подсказка, отправку не создаёт.

## Активация (владелец)
1. Создать бота у @BotFather → токен. 2. В `/opt/remlab/.env`: `MANAGER_TG_TOKEN`, `MANAGER_TG_WEBHOOK_SECRET`
(случайная строка); `docker compose up -d --no-deps app`. 3. setWebhook на
`https://remont-lab.online/api/manager-bot` с `secret_token`. 4. Менеджеры —
`/opt/remlab/scripts/manager-add.sh --partner demo --name … --phone … [--telegram …] [--whatsapp …]`,
скрипт печатает ссылку на страницу менеджера.

## Проверено 13.10 (прод)
Создал ссылку со страницы → карточка → события open/variant/consult = 200, `status` от покупателя = 400,
чужой ключ = 403; статус `engaged`, сигналов «не доставлено» 2 (бота нет); на `/manager` 0 запросов к
Метрике; демо по `?s=` показывает менеджера, по кривому `s` — честный баннер.
