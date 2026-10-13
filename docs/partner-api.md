# API для CRM застройщика (черновик, план b2b-02)

> Статус: **описание, не реализовано.** Делается отдельным планом после первого платящего застройщика.
> Сегодня ссылку покупателю создаёт менеджер — в Telegram-боте или на своей странице `/manager#<ключ>`.

## Зачем
Когда в CRM застройщика отмечен «показ состоялся», ссылка покупателю создаётся сама и уходит ему от
имени менеджера — без ручного шага. Мы при этом не получаем ни имени, ни телефона покупателя.

## Создать отправку
`POST /api/partner/v1/sends` — заголовок `Authorization: Bearer <ключ партнёра>`.
```json
{ "apartmentId": "flat215", "managerId": "demo-1a2b3c4d", "externalRef": "crm-deal-8812" }
```
Ответ: `{ "id": "<22 символа>", "url": "https://remont-lab.online/demo/?s=<id>" }`.
`externalRef` — номер сделки в CRM (не ПДн), по нему застройщик сопоставит наши события со своими.
Доставку ссылки покупателю делает CRM (её SMS/WhatsApp-шаблон).

## Получать события
Вебхук партнёра (URL и секрет задаются при подключении), подпись `X-Remlab-Signature: sha256=<HMAC тела>`:
```json
{ "sendId": "…", "externalRef": "crm-deal-8812", "kind": "manager_contact_click",
  "at": "2026-10-14T09:31:00Z", "payload": { "purpose": "consult", "sum": 210000 } }
```
`kind` — словарь `contracts/send.ts` (`designer_open`, `variant_view`, `item_swap`,
`manager_contact_click`, `alternative_request`). Повтор при не-2xx: 1, 5, 15, 60 минут.

## Статусы
`POST /api/partner/v1/sends/{id}/status` `{ "status": "meeting" }` — те же статусы, что ставит менеджер
(`contacted | meeting | deal | lost`). Отзыв ссылки — `{ "revoke": true }`.
