---
workstream: growth
slug: sub-e7-growth
title: Э7 Рост — SEO, шаринг, e-mail, anti-abuse (скелет)
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

> **СКЕЛЕТ.** Детализировать только после экономики Э2/Э4 и лимитов расхода из Э0. До этого не исполнять.

## Цель
Масштабировать приток (SEO/шаринг/e-mail) без роста CAC и без неконтролируемого расхода генераций.

## Источник задачи
Этап Э7 мастер-плана [[commercial-master-plan]], сессия 2026-07-11.

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md` — гейты Э7, зависимости Э0/Э2/Э4
- `.memory_bank/guides/execution-playbook.md`; `docs/master-brief-v0.3.md` (free = реф-ссылки)
- `app/layout.tsx` (`export const metadata`) · `lib/analytics.ts` (union `EventName`, `track()`) ·
  `lib/env.ts` (Zod-схема, образец `providerEnvSchema`)
- `app/api/p/[id]/generate/route.ts` — сюда Turnstile/лимиты · `app/p/[id]/preview/page.tsx` — основа шаринга

## Скоуп — что входит
- SEO: `app/sitemap.ts` + `app/robots.ts` (новые), per-page `generateMetadata`, OG-картинки.
- Programmatic SSG: страницы «стиль×комната[×бюджет]» — НЕ тратят генераций.
- Шаринг: публичная страница результата, строго opt-in (владелец публикует явно).
- E-mail (Resend): «комната готова», «цены изменились»; env `RESEND_API_KEY`.
- Anti-abuse: Turnstile на генерацию (env `TURNSTILE_SECRET_KEY`, `NEXT_PUBLIC_TURNSTILE_SITE_KEY`),
  per-IP лимиты, алерт по расходу.
- Каналы: усиливать сработавшее в Э1.

## Скоуп — что НЕ входит
- Платный трафик как основной канал (только по ROI из Э1).
- Блог руками, мультиязычность/UK-локаль.
- Реферальная программа с вознаграждением (решение владельца).

## Файлы к изменению (ориентировочно)
- [ ] `app/sitemap.ts` (новый), `app/robots.ts` (новый)
- [ ] `app/layout.tsx` — OG/metadata
- [ ] `app/api/p/[id]/generate/route.ts` — Turnstile + per-IP лимит
- [ ] `lib/env.ts` — имена ключей в Zod-схему (значения — только в `.env` на сервере)
- [ ] `lib/analytics.ts` — события в `EventName` + вызовы `track()`
- [ ] директории под SSG/шаринг — спроектировать при детализации

## Задачи
Пошаговка — при детализации (после гейта Э2/Э4). Порядок жёсткий: 1) anti-abuse
(иначе SEO = кран расходов) → 2) SEO → 3) SSG → 4) шаринг → 5) e-mail.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` — зелёные; `pnpm e2e` — smoke жив
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://remont-lab.online/sitemap.xml` → 200
- [ ] POST `/api/p/<id>/generate` без Turnstile-токена → 4xx
- [ ] Gate этапа (PostHog): органика ≥30% новых сессий; blended CAC ≤0.5× дохода на пользователя

## Чекпоинты владельца
- [ ] ⏸ ПОКАЗАТЬ (до детализации): список SSG-страниц + скрин шаринг-страницы.
  Вопрос: что показываем всем, что оставляем приватным?

## Если пошло не по плану
- Расход генераций растёт после SEO → ужесточить per-IP (лимиты Э0); не помогло →
  закрыть индексацию генерящих страниц, сказать владельцу.
- Turnstile режет живых (конверсия падает в PostHog) → включать только при подозрении.
- Органика не растёт → этап режется по ROI (так задумано), доложить владельцу.

## Критерии приёмки
- [ ] Скелет заменён детальным планом (гейт Э2/Э4 пройден)
- [ ] Anti-abuse включён ДО открытия SEO-крана
- [ ] Gate этапа измерим в PostHog

## Definition of Done — память
- [ ] Memory Bank обновлён (core-сводки; решения → `decisions.md`)
- [ ] `/memory-check` выполнен, audit чисто
- [ ] Статус в реестре [[commercial-master-plan]] обновлён

## Лог выполнения
- 2026-07-11 — план создан, draft (скелет)

## Completion summary

## Follow-up work
- Э8 (масштаб) зависит от результатов этапа — [[commercial-master-plan]].
- Реферальная программа — решение владельца при детализации.
