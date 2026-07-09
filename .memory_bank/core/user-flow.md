---
tier: 1
topic: user-flow
scope: Stage 1 UX-flow, экраны, free/paid граница, аналитика
tier2: ../domain/user-flow-details.md
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-09
---

# User Flow — Tier 1 (freemium v0.3)

## Stage 1 flow (7 экранов, план)
Landing → Комната+цель+уровень → Фото+бриф → Style cards → AI-preview + до N реальных товаров
→ Paywall / room pack → Workspace «Мои комнаты».

## Free vs Paid = уровень (3 варианта, owner 2026-07-02)
1. «Освежить без ремонта» — БЕСПЛАТНО: визуализация + до 3 реальных предметов
   (цена/реф-ссылка) + товарный бюджет.
2. «Недорого обновить» — ~1 490 ₽: мебель без лимита + материалы.
3. «Ремонт под ключ» — 9 900 ₽: + гайды, чертежи, смета (Cost Engine), живой дизайнер.
- Реф-ссылки везде. Paywall-триггер — выбор варианта 2/3, НЕ 3 бесплатных товара (всегда открыты).
- ⚠️ Код-долг: `FREE_VISIBLE=3` есть (вар.1), но товары — seed (нужны фиды Гдеслон); вариантов 2/3
  нет; оплата — заглушка (YooKassa нет); согласовать с `interventionLevel`.

## Flow в коде — сверено 2026-07-09
`/` → `/start` → `/p/[id]/brief` → `/p/[id]/select` → `/p/[id]/preview` → `/p/[id]/paywall`;
`/rooms` — «Мои комнаты»; `/soon` — fake-door стоимости; `/style` — редирект на `/select`.
Выбор пользователя РЕАЛЬНО управляет генерацией: `/select` — `runAnalyze` (пред-шаг вне трейса,
идемпотентен), пообъектно keep/change/remove (`objectChoices`, дефолт от модели) + стиль +
пожелание (`wish`); «Сгенерировать» → `runGenerate` (restyle по выбору + ideas) = «генерация»
с номером.

## Прочие сценарии (план) — детали Tier 2
«Найти похожую мебель по фото» (pgvector, без генерации); сегмент F — дизайнер B2B (Stage 1.5);
Cost-сценарий (Stage 1B): сумму считает движок, НЕ LLM.

## Аналитика
`lib/analytics.ts`: серверный PostHog; без `POSTHOG_KEY` — no-op. Объявлено 9 событий, реально
эмитятся 5 (project_started, preview_ready, pack_unlocked, problem_reported, app_error);
остальные 4 НЕ вызываются. План CJM (landing_*, affiliate_*, лимиты генерации)
НЕ реализован — Tier 2.

**Tier 2:** `../domain/user-flow-details.md`; полный CJM — `../../docs/cjm-ux-v0.2.md`.
