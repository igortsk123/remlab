---
workstream: commercial
slug: sub-e1-validation
title: Э1 Stage 0 — concierge-валидация экономики на живом трафике
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

## Цель
Проверить деньгами экономику v0.3 на живом трафике (CPC/CR/CTR, первые заказы Гдеслон) — до кода фидов и платежей; товары подбирает владелец руками (concierge).

## Источник задачи
Этап Э1 (⭐) мастер-плана [[commercial-master-plan]], сессия 2026-07-11.

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md`, `.memory_bank/guides/execution-playbook.md`, `docs/master-brief-v0.3.md`
- `app/actions.ts` (образец: `track(event, sessionId, props)`); `lib/trace/admin.ts` (traceAdminOk); `lib/session.ts` (getSessionId)

## Скоуп — что входит
1. Заявка на ручной подбор на preview (email; cap 20/нед) + fake-door «Проверить, влезет ли» (фото с A4 + email; вердикт руками).
2. Admin заявок за токеном: 3 ссылки Гдеслон (`subid=projectId`), письмо.
3. Воронка PostHog (разрез UTM), недельный отчёт и ритм, памятка кампаний (Директ/VK).

## Скоуп — что НЕ входит
- Фиды/автоподбор (Э2), платежи (Э4), ML-код (∥ ML-трек).
- Загрузка A4-фото через сайт (просим письмом); юр-логика ПДн — только `// TODO(legal)`.
- Починка `e2e/flow.spec.ts` и дыры владения — Э0 (`sub-e0-stopkran`).

## Файлы к изменению
- [ ] Правки: `contracts/project.ts`, `modules/store/repository.ts` + `pg-repository.ts`, `app/actions.ts`, `app/p/[id]/preview/page.tsx`, `lib/analytics.ts`, `.env.example`
- [ ] Новые: `components/ConciergeRequest.tsx`, `components/FitCheckDoor.tsx`, `app/admin/concierge/page.tsx`, `app/admin/concierge/actions.ts`, `lib/email.ts`, `tools/weekly-report.mjs` (опц.), `tests/unit/concierge.test.ts`, `.memory_bank/guides/validation-ops.md`

## Задачи
**A. Данные и заявка**
- [ ] `contracts/project.ts`: optional `concierge` {email, requestedAt ISO, links ≤3 URL, sentAt?} и `fitCheck` {email, requestedAt}; старые записи парсятся без миграции.
- [ ] `modules/store/*`: `listConciergeRequests()` — интерфейс, in-memory, SQL по jsonb `data->'concierge'`.
- [ ] `requestConcierge(id, fd)`: email по Zod; `project.sessionId !== getSessionId()` → notFound(); запись `repo().update`; `track("concierge_requested", ...)`; заявок за 7 дней ≥20 (cap) → не писать, форме «мест нет».
- [ ] `ConciergeRequest.tsx`: после submit «пришлём в течение суток»; заявка есть → статус; место — после блока «Идеи изменений».

**B. Admin**
- [ ] `page.tsx`: гард `searchParams.token === process.env.TRACE_ADMIN_TOKEN`; строже traceAdminOk (в образце без токена открыто!): нет токена → только не-production, иначе notFound(). Список: дата, email, фото (`photos[0].dataUrl` в `<img>`), бриф/анализ, бюджет; форма на 3 ссылки.
- [ ] `actions.ts`: валидные URL; `subid=projectId` через URLSearchParams (не склейкой); сохранить `links`+`sentAt`; `track("concierge_sent", ...)`; письмо; экшен под тем же токеном (hidden-поле).
- [ ] `lib/email.ts`: `sendMail({to,subject,html})` → POST `https://api.resend.com/emails` (Bearer `RESEND_API_KEY`, from `CONCIERGE_FROM_EMAIL`); нет ключа → `{ok:false}`, admin показывает текст письма для ручной отправки.

**C. Fit-check**
- [ ] `FitCheckDoor.tsx` (рядом с заявкой): «Проверить, влезет ли» → просьба: фото с листом A4 на полу + email; `requestFitCheck(id, fd)` по образцу requestConcierge, запись `fitCheck`, `track("fit_check_interest", ...)`.
- [ ] Вердикт — владелец руками (после Э0 — `ml/`; до того `/home/pakar/mltest`: geometry_solver.py, fit_check.py); кода не требует.

**D. Воронка и отчёты**
- [ ] +3 EventName. Шаг «фото» и клики товаров/тарифов дошивает Э0 — сейчас шлются только `project_started|preview_ready|pack_unlocked|problem_reported`; не дошито → СТОП, вернуть в Э0.
- [ ] Дашборд в UI PostHog: funnel `project_started→фото→preview_ready→клик товара→клик тарифа`, разрез `utm_source/utm_campaign`; «как читать» → `validation-ops.md`.
- [ ] `weekly-report.mjs` (опц.): PostHog Query API (HogQL, `POSTHOG_PERSONAL_API_KEY`) → md: UTM-визиты, CR шагов, CTR товаров, интент тарифов; не отдаёт → руками из UI.

**E. Кампании** — кода нет; памятка владельцу, см. Чекпоинты.
**F. Ритм (2–6 нед)** — еженедельно: отчёт + 20–30 трейсов (`/trace N`) → свод в «Лог выполнения».

## Гейты
Машинные:
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build`, `pnpm e2e` — зелёные.
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://remont-lab.online/admin/concierge` → 404; с `?token=$TRACE_ADMIN_TOKEN` → 200.
- [ ] Сценарий локально: preview → email → admin → 3 ссылки → в письме все 3 с `subid=<projectId>`.
- [ ] unit: 21-я заявка отклоняется; старый проект без `concierge` парсится.
Бизнес-гейты (владелец): CPC≤15₽ · клик→фото≥20% · viz→клик товара≥15% · первые заказы Гдеслон · интент оплаты≥4%. Kill: CPC>30₽→канал; CTR товаров<5%→оффер; 0 заказов/300 кликов→paid-first.

## Чекпоинты владельца
- ⏸ ДО КОДА: тексты заявки, fake-door, письма — 2 варианта, простым языком. Вопрос: какой тон?
- ⏸ Скрин admin с тестовой заявкой + текст письма. Вопрос: удобно ли, чего не хватает?
- ⏸ ПАМЯТКА (зона владельца): Директ/VK, «сделать ремонт самому», CPC ~10₽, 3–4 креатива, транши 10–20 тыс.₽, UTM-шаблон даст агент; старт после зелёного Э0. Вопрос: первый транш и дата старта?
- ⏸ ЕЖЕНЕДЕЛЬНО: таблица метрик + 3–5 трейсов. Вопрос: продолжаем, крутим оффер или kill?

## Если пошло не по плану
1. Заявок > cap → форма закрывается сама; cap поднимает владелец.
2. Resend/DNS или Query API не заводятся → письма/отчёт вручную.
3. События Э0 не дошиты → вернуть в `sub-e0-stopkran`, план → `partial`.
4. Клик→фото < 20% → разбор (первый экран, скорость, трейсы); флоу не менять без владельца.
5. `subid` не виден → сверить с поддержкой Гдеслон; пока атрибуция вручную.

## Критерии приёмки
- [ ] Preview: заявка + fake-door, события в PostHog; admin за токеном, письмо с 3 ссылками `subid=projectId` уходит.
- [ ] Cap 20/нед покрыт тестом; дашборд собран; dry-run отчёта до трафика; кампании запущены; метрики ≥2 недели подряд.
- [ ] Решение по гейту Э1 (пройден/kill/pivot) — за владельцем, в [[commercial-master-plan]] и `docs/DECISIONS.md`.

## Definition of Done — память
- [ ] Обновлены (`updated:`) `core/user-flow.md`, `core/data-model.md`, `core/access-and-integrations.md` (Resend/PostHog — только имена env).
- [ ] Решения → `decisions.md` (ADR), отклонения → `docs/DECISIONS.md`; `/memory-check` выполнен, audit «чисто»; реестр [[commercial-master-plan]] обновлён.

## Лог выполнения
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- Э2 `sub-e2-feeds` — по CTR-gate Э1; заявки из jsonb в таблицу при росте потока.
- Weekly-report на Inngest; загрузка A4 через сайт при высоком интенте.
