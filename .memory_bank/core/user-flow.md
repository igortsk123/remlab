---
tier: 1
topic: user-flow
scope: Stage 1 UX-flow (построенный AI-флоу), экраны, аналитика
tier2: ../domain/user-flow-details.md
updated: 2026-07-30
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-30
---

> ⚠️ ADR-0016: **v0.4 «Смета-first»** — `plans/MASTER-cost-first.md`; v0.3-детали ниже — историч.

# User Flow — Tier 1

## Навигация (v0.4, сквозная шапка — ADR-0017)
Одна шапка `SiteHeader.tsx`: логотип + «Моя лаборатория»; ниже ОДИН ряд: материалы · ремонт ·
Дизайн · Стили · Советы (шапка шире контента: 1100px против 720). Мобильный: скролл вниз
сворачивает ряд (`site-header--collapsed`, ≤700px), ≤480px — компакт, бейджи «скоро» скрыты.
Главная (`app/page.tsx`) = «о проекте целиком», не только калькулятор.
- **`/styles`** — игра-карточки «узнай свой вкус» (`components/StyleQuiz.tsx`, сид `lib/styles/quiz.ts`):
  лайк/скип → стиль → CTA дизайн/смета; событие `quiz_completed` (`app/styles-actions.ts`). Фото карточек
  и статьи по стилям — ПЛЕЙСХОЛДЕРЫ (позже).
- **`/sovety`** — плитки-советы ПЛЕЙСХОЛДЕРЫ (тексты позже, М7). **`/lab`** — хаб «Мои сметы»
  (`/estimates`) + «Мои дизайны» (`/rooms`); аккаунт/вход позже.
Детали — `completed_plans/site-nav-and-scenarios.md`.

## AI-флоу (Stage 1 → ступень М5; сверено 2026-07-09) — детали Tier 2
Экраны `/start` → `/p/[id]/{brief→select→preview→paywall}`, `/rooms`, `/soon` (fake-door). Выбор
управляет генерацией: `/select` — `runAnalyze` + keep/change/remove (`objectChoices`) + стиль + `wish`;
«Сгенерировать» → `runGenerate` (restyle+ideas) = «генерация» с номером. Free/Paid = уровень (3
варианта, owner 2026-07-02): «Освежить» бесплатно (виз.+до 3 товаров), «Недорого» ~1490 ₽, «Под ключ»
9900 ₽; реф-ссылки везде, paywall-триггер = выбор 2/3. ⚠️ Код-долг: товары seed, вар.2/3 и YooKassa нет.

## Аналитика
`lib/analytics.ts` (PostHog, no-op без ключа): из 9+ событий эмитятся project_started / preview_ready /
pack_unlocked / problem_reported / app_error (+ `quiz_completed`).

**Tier 2:** `../domain/user-flow-details.md`; полный CJM — `../../docs/cjm-ux-v0.2.md`.
