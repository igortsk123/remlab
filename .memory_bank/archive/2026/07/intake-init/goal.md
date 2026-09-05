# remlab — краткий бриф проекта

## Что это
**remont-lab** (`remont-lab.online`) — B2C AI-помощник по ремонту/обновлению квартиры.
Формула Stage 1: **фото комнаты → стиль через карточки → AI-preview → ограниченный бесплатный результат → платный room pack → workspace «Мои комнаты»**.

## Кто пользователь / боль
Человек хочет обновить гостиную или спальню без капитального ремонта, но не понимает, что купить, как сочетать, сколько это стоит и где взять товары. Продукт даёт визуальную идею (AI), подбор товаров, диапазон бюджета и план действий.

## Сегменты (приоритет)
- **A. «Хочу обновить комнату»** — главный сценарий Stage 1.
- **B. «Хочу понять стоимость»** — Stage 1B (Renovation Cost Engine, НЕ LLM).
- C. «Часть сделаю сам» — блок внутри room pack.
- D. «Повторить интерьер с фото» — Stage 1.5 / Stage 2 (fake-door в Stage 1).
- E. «Ремонт под ключ» — Stage 3 (contractor handoff).

## Scope
- **Stage 1:** landing, короткий flow (комната/цель/уровень → фото/бриф → style cards → AI-preview → free preview → paywall → paid room pack → workspace), гостиная/спальня, PDF-экспорт, базовый каталог.
- **Stage 1B:** сценарий стоимости + Cost Engine (city/work/material rates + coefficients + confidence).
- **НЕ в Stage 1:** repeat-reference как главный сценарий, кухня/ванная, точная смета, чертежи, 3D, подрядчики, маркетплейс внутри.

## Стек (TS end-to-end)
TypeScript strict + pnpm + Next.js (App Router, full-stack) + Supabase-совместимый Postgres+pgvector + Drizzle + Zod (контракты на границах) + Inngest (durable jobs) + внешний инференс (Vertex/fal/Replicate за провайдер-интерфейсом) + YooKassa + Sentry + PostHog + Vitest/Playwright + GitHub Actions.
> В нашем деплое БД — **самохостед `postgres:17 + pgvector` в контейнере** на сервере exit-fi (не Supabase Cloud). Auth/Realtime/Storage — решаются по мере фич (интерим: polling вместо Realtime; см. DECISIONS).

## Главные инженерные приоритеты (владелец не пишет код)
Самопроверяемость: тесты рядом с кодом, CI-гейт блокирует merge, observability (Sentry/PostHog), eval-харнесс качества генерации, гардрейлы стоимости, Zod-контракты как анти-дрейф. Гипотезы, не аксиомы → отклонения фиксировать в `docs/DECISIONS.md` (ADR).

## Полные исходники
- Инженерная тех-спека (TS-стек): `docs/tech-spec-ts-stack.md`
- CJM + UX Flow v0.2: `docs/cjm-ux-v0.2.md`
- Инфраструктура/деплой и подтверждённые решения: `_intake/history/deploy-and-decisions.md`
