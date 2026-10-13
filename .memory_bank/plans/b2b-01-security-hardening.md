---
workstream: infra
slug: b2b-01-security-hardening
title: Безопасность перед показом девелоперу — контакты не в файлах, лимиты на платное, подпись вебхука, CSP и встраивание по списку
status: draft
created: 2026-10-13
updated: 2026-10-13
completed:
plan_kind: sub
parent_plan: MASTER-developer-product
assignee: opus-5.5
review_after: 2026-11-13
---

## Цель
Ни один контакт покупателя не лежит в файле под веб-корнем; платные вызовы и заявки ограничены по
частоте; чужой сайт не может встроить нас без разрешения, а наш сайт — только разрешённым
девелоперам; вебхуки проверяют подпись; серверный конфиг совпадает с репо и катится деплоем.

## Источник задачи
Обследование 13.10 (Fable): инцидент — `/test/share/_queue/` с контактами людей был виден снаружи
через `file_server browse` (`caddy/Caddyfile`, блок `/test/*`). Закрыт в тот же день заплаткой
(`@sharequeue → 404`, бэкап `Caddyfile.bak.20261013-*`). Остальные находки — ниже.

## Диагноз (сверено 13.10)
1. **Контакты в файлах.** `tools/scout/draft_service.py:376-385` пишет `{channel, contact, …}` в
   `SHARE_DIR/_queue/<id>.json` под `/opt/remlab/test/share/` — папка раздаётся Caddy с browse
   (`Caddyfile` `handle_path /test/*` → `file_server browse`). Согласия нет, записи в БД нет.
2. **Платное без лимитов:** `app/api/calc/parse-link` (OpenAI + платный прокси), `app/api/p/[id]/analyze`,
   `app/api/p/[id]/generate` (Gemini) — без квот/рейт-лимита; в Next нигде нет 429 (grep).
3. **Вебхук ЮKassa без подписи/IP** (`app/api/pay/yookassa/webhook/route.ts:7-13`).
4. **CORS `*`** у Python-рендера (`draft_service.py:164`); токен трейса принимается в query
   (`lib/trace/admin.ts:8`); трейс открыт, если `TRACE_ADMIN_TOKEN` пуст; TG-вебхуки защищены только
   при заданном `LEADS_TG_WEBHOOK_SECRET` (`app/api/leads/tg-admin/route.ts:14`).
5. **Нет CSP / `frame-ancestors` / X-Frame-Options** нигде (`Caddyfile`, `next.config.mjs`) — любой
   сайт может встроить нас в iframe (фишинг под брендом девелопера), и наоборот — нет allowlist.
6. **Возможный stored XSS** на страницах подборок: `html.escape` не блокирует `javascript:` в `href`
   (`draft_service.py:353`).
7. **Caddyfile на сервере был новее репо** (блоки `@nextrce`, `/rt/*`); 13.10 выровнено копированием
   с сервера; автодеплой Caddyfile не возит (`deployment.md`).

## Скоуп — что входит
1. Очередь подборок: контакты — в БД (`leads`/новая таблица `share_requests`), файлы `_queue` —
   перенести вне веб-корня и удалить из `/opt/remlab/test/share/_queue` (бэкап → перенос → проверка
   404 снаружи); `SHARE_DIR` для страниц подборок остаётся, но без ПДн внутри.
2. Рейт-лимит (IP + сессия) на `parse-link`, `p/[id]/*`, `flat/config` POST, обращения/«отправить себе»/коллекции; дневной потолок
   стоимости на платные вызовы (есть `openai_budget` в scout — в Next нужен аналог); 429 с текстом.
3. ЮKassa: проверка подписи/IP-диапазонов ЮKassa по их документации (источник в плане), иначе 403.
4. CORS рендера — только свои origin'ы; токен трейса — только заголовок; пустой токен = закрыто.
5. CSP с `frame-ancestors 'self' <список доменов девелоперов>` (список — из конфигурации партнёров,
   см. `b2b-06`/`b2b-07`), `X-Content-Type-Options`, `Referrer-Policy`; для статики `/demo`, `/test`.
6. `href` в страницах подборок — только `http(s)`; экранирование через общий helper.
7. Caddyfile — в деплой: `infra/server/deploy-remote.sh` копирует с предохранителем (`comm`) и
   `caddy validate` → `reload`; drift-проверка в CI (diff репо vs сервер — отдельный шаг с ssh-ключом
   или отчёт в дайджест).
8. Тест: smoke на 404 для `_queue`, 403 для неподписанного вебхука, 429 при превышении, заголовки CSP.

## Скоуп — что НЕ входит
- Аутентификация пользователей (нет такой сущности в продукте).
- Юридические тексты (см. `b2b-04`).

## Файлы к изменению
- [ ] `caddy/Caddyfile`, `infra/server/deploy-remote.sh`, `.github/workflows/*` — заголовки, деплой конфига, drift-проверка
- [ ] `tools/scout/draft_service.py` — очередь в БД, CORS, экранирование
- [ ] `app/api/calc/parse-link/route.ts`, `app/api/p/[id]/*`, `app/api/flat/config/route.ts`, `app/lead-actions.ts` — лимиты
- [ ] `lib/ratelimit.ts` (новый, in-memory + Postgres), `lib/trace/admin.ts`, `app/api/pay/yookassa/webhook/route.ts`
- [ ] `db/schema.ts` + миграция — `share_requests`
- [ ] `e2e/smoke.spec.ts` — проверки заголовков и 404

## Критерии приёмки
- [ ] Снаружи: `/test/share/_queue/` 404, файлов с контактами под `/opt/remlab/test` нет (ssh-проверка)
- [ ] 50 запросов подряд к `parse-link` с одного IP → 429; ЮKassa без подписи → 403
- [ ] `curl -I /demo/` показывает CSP с `frame-ancestors`; iframe с чужого домена не открывается
- [ ] `diff` Caddyfile репо ↔ сервер пуст; деплой возит конфиг; VPN-нода не задета
- [ ] Lint / build / тесты зелёные

## Где обязательно советоваться с Codex
- Схема лимитов и потолка стоимости (п.2 правила), миграция очереди в БД (п.7 рискованное), CSP для
  встраивания (п.7).

## Definition of Done — память
- [ ] `deployment.md` § Безопасность (инцидент 13.10 + правило «ПДн не в файлах под веб-корнем»), урок в `lessons/devops-deploy.md`; ADR; `/memory-check`

## Лог выполнения
- 2026-10-13 — план создан (draft), Fable 5.1; заплатка в Caddy уже стоит

## Completion summary
—

### Уроки
—
