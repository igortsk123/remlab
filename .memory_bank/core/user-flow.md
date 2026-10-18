---
tier: 1
topic: user-flow
scope: Stage 1 UX-flow, аналитика
tier2: ../domain/user-flow-details.md
updated: 2026-10-18
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-10-14
review_after: 2026-12-05
---

> ⚠️ ADR-0016: **v0.4 «Смета-first»** — `plans/MASTER-cost-first.md`; v0.3-детали ниже — историч.

# User Flow — Tier 1

## Навигация (v0.4, сквозная шапка — ADR-0017)
Одна шапка `SiteHeader.tsx`: логотип + «Моя лаборатория»; ряд материалы · ремонт · Дизайн ·
Стили · Советы; адаптив ≤700/≤480 (урок 7 [[lessons]]); активный раздел — заливка.
Иконки — [[access-and-integrations]]. Главная = ХАБ из шести плиток и два CTA (не «о проекте»).
- `/styles` (игра-карточки, `components/StyleQuiz.tsx`), `/sovety`, `/start`, `/calc/remont` — за заглушкой `ComingSoon`
  (`NEXT_PUBLIC_SHOW_WIP=1`); `/lab` — центр сохранений (ADR-0038, вкладки `?tab=`, «Мой стиль» → `style_results`).
Детали — `completed_plans/site-nav-and-scenarios.md`.

## AI-флоу (Stage 1 → ступень М5; сверено 2026-08-06) — детали Tier 2
Главная `/` — хаб из 6 плиток (calc/remont/start/styles/sovety/lab). Экраны `/start` →
`/p/[id]/{brief→select→preview→paywall}`, `/rooms`, `/soon` (fake-door, событие не эмитится). Выбор
управляет генерацией: `/select` — `runAnalyze` + keep/change/remove (`objectChoices`) + стиль + `wish`;
«Сгенерировать» → `runGenerate` (restyle+ideas) = «генерация» с номером. Free/Paid = уровень (3
варианта, owner 2026-07-02): «Освежить» бесплатно (виз.+до 3 товаров), цены ступеней в коде НЕТ: фактически один
платный пакет 490 ₽ (`app/p/[id]/paywall/page.tsx`); реф-ссылки везде, paywall-триггер = выбор 2/3. ⚠️ Код-долг: товары seed, вар.2/3 и YooKassa нет.

**Избранное/«поделиться» (18.10, demo-15, ADR-0306):** ♡ в окне → коллекция «<Стиль> #N» с секретом переименования
(`modules/collections/repository.ts`); раздел «Избранное» на главной; ⇪ share/копирование. Карта 2.13–2.15.

## Аналитика
`lib/analytics.ts` (PostHog, no-op без ключа), сверка 11.10: 17 событий объявлено (`EventName`), 12 эмитится
(estimate_*, lab_tab, lead_*, quiz_completed, viz_started, project_started, preview_ready…).

**Отчёт застройщику (ADR-0265):** `/partner/report#<ключ>` — воронка по ссылкам менеджеров
(`modules/partner-report/report.ts:buildReport`) + анонимные счётчики `/api/events`; детали — Tier 2.

**Tier 2:** `../domain/user-flow-details.md`; полный CJM — `../../docs/cjm-ux-v0.2.md`.
