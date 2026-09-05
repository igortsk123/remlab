---
tier: 1
topic: leads
scope: Лид-канал — заявка, TG-бот
tier2: ""
updated: 2026-08-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-28
review_after: ""
---

# Лид-коммуникации — Tier 1 (П7, ADR-0180)

## Флоу
Чип Телеграм/MAX/почта в `LeadCard` → ОДНА модалка `LeadModal`: город (автокомплит по справочнику
~1106 городов РФ, `data/ru-cities.json`, hflabs CC BY-SA) + e-mail (только канал «почта») + согласие →
`captureLead` (Zod) → заявка в БД (`leads`: leadNo из sequence, канал, город, ip_region, статус) →
карточка владельцу в СЛУЖЕБНЫЙ TG-бот. TG/MAX: после заявки кнопки «Подписаться…» с deep-link
`?start=<lead.id>` (бот не может писать первым — нужен Start).

## Ответы
Владелец отвечает РЕПЛАЕМ в служебном боте → `byAdminMsg` (маппинг `lead_messages.admin_tg_message_id`)
→ `replyToLead`: почта → SMTP Яндекс (`lib/leads/mailer.ts`); tg → клиентский бот; MAX — деградация до
токена. Входящие клиента из клиентского бота пересылаются владельцу с подписью «Заявка #N».

## Код
`lib/leads/{tg,mailer,router,cities}.ts` · вебхуки `app/api/leads/{tg-admin,tg-client,max}/route.ts`
(секрет: заголовок X-Telegram-Bot-Api-Secret-Token) · `app/api/leads/cities` (автокомплит) ·
`modules/leads/repository.ts` (pg+memory) · SQL `db/init/005-leads.sql` (+`lead_messages`).

## Активация (owner)
Токены в `/opt/remlab/.env`: `LEADS_ADMIN_TG_TOKEN`+`CHAT_ID`, `LEADS_CLIENT_TG_TOKEN`,
`LEADS_TG_WEBHOOK_SECRET`, `LEADS_MAX_TOKEN`, `LEADS_SMTP_USER/PASS` (palmarius.ru@yandex.ru временно;
доступ — sup2 `_secrets/ACCESS.md`) + setWebhook обоих ботов на `/api/leads/tg-{admin,client}`.
Без токенов всё деградирует (заявки пишутся, карточки/ответы — нет). ПДн — TODO (юрист).

> Сверено 2026-08-28: изменений в лид-канале нет; новое — очередь отправки подборок демо (`/opt/remlab/test/share/_queue`) ждёт те же токены ботов (`LEADS_CLIENT_TG_TOKEN`, MAX).
