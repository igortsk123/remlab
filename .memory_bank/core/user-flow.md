---
tier: 1
topic: user-flow
scope: Stage 1 UX-flow, аналитика
tier2: ../domain/user-flow-details.md
updated: 2026-08-06
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-31
review_after: 2026-12-05
---

> ⚠️ ADR-0016: **v0.4 «Смета-first»** — `plans/MASTER-cost-first.md`; v0.3-детали ниже — историч.

# User Flow — Tier 1

## Навигация (v0.4, сквозная шапка — ADR-0017)
Одна шапка `SiteHeader.tsx`: логотип + «Моя лаборатория»; ряд материалы · ремонт · Дизайн ·
Стили · Советы; адаптив ≤700/≤480 (урок 7 [[lessons]]); активный раздел — заливка.
Иконки — [[access-and-integrations]]. Главная = «о проекте».
- **`/styles`** — игра-карточки «узнай свой вкус» (`components/StyleQuiz.tsx`, сид `lib/styles/quiz.ts`):
  лайк/скип → стиль → CTA дизайн/смета; событие `quiz_completed` (`app/styles-actions.ts`). Фото карточек
  и статьи по стилям — ПЛЕЙСХОЛДЕРЫ (позже).
- **`/sovety`** — плитки-советы ПЛЕЙСХОЛДЕРЫ (тексты позже, М7). **`/lab`** — центр сохранений
  (ADR-0038): вкладки `?tab=` Материалы/Ремонт/Дизайны (WIP — тизеры «Скоро»), «Мой стиль»
  (итог /styles → `style_results`), событие `lab_tab`; `/estimates` → `/lab` (ADR-0036).
Детали — `completed_plans/site-nav-and-scenarios.md`.

## AI-флоу (Stage 1 → ступень М5; сверено 2026-08-06) — детали Tier 2
Главная `/` — хаб из 6 плиток (calc/remont/start/styles/sovety/lab). Экраны `/start` →
`/p/[id]/{brief→select→preview→paywall}`, `/rooms`, `/soon` (fake-door, событие не эмитится). Выбор
управляет генерацией: `/select` — `runAnalyze` + keep/change/remove (`objectChoices`) + стиль + `wish`;
«Сгенерировать» → `runGenerate` (restyle+ideas) = «генерация» с номером. Free/Paid = уровень (3
варианта, owner 2026-07-02): «Освежить» бесплатно (виз.+до 3 товаров), «Недорого» ~1490 ₽, «Под ключ»
9900 ₽; реф-ссылки везде, paywall-триггер = выбор 2/3. ⚠️ Код-долг: товары seed, вар.2/3 и YooKassa нет.

## Аналитика
`lib/analytics.ts` (PostHog, no-op без ключа), сверка 06.08: 22 события объявлено, 12 эмитится
(estimate_*, lab_tab, lead_*, quiz_completed, viz_started, project_started, preview_ready…).

**Tier 2:** `../domain/user-flow-details.md`; полный CJM — `../../docs/cjm-ux-v0.2.md`.
