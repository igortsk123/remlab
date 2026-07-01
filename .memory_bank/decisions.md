---
tier: 1
topic: decisions
scope: ADR-лог — архитектурные решения с обоснованием и влиянием
tier2: "../docs/DECISIONS.md"
updated: 2026-07-01
importance: high
source: manual
status: stable
source_of_truth: canonical
last_verified: 2026-07-01
review_after: ""
---

# Decisions — ADR-лог

> Полные ADR с контекстом/последствиями — в `docs/DECISIONS.md`. Здесь — короткая навигация по решениям.

## [2026-07-01] Стек проекта
**Решение:** TypeScript (strict) end-to-end: Next.js (App Router, full-stack) + Drizzle + Zod (контракты на границах) + Inngest (durable jobs) + внешний инференс (Vertex/fal/Replicate за провайдер-интерфейсом) + YooKassa + Sentry + PostHog + Vitest/Playwright + GitHub Actions.
**Почему:** соло + не-кодер → один рантайм и сквозные типы убирают класс ошибок, которые владелец не читает.
**Альтернативы:** Python+TS два рантайма — отвергнуто (два деплоя, рассинхрон).
**Влияет на:** `core/architecture.md`, структуру `/modules`, `/contracts`.

## [2026-07-01] Self-host на exit-fi вместо Vercel — ADR-0001 (docs/DECISIONS.md)
Изолированный docker-compose на Hetzner exit-fi. Причина: свой сервер, контроль, дёшево. Fallback — Vercel+Supabase.

## [2026-07-01] БД в контейнере postgres:17+pgvector — ADR-0002
Не Supabase Cloud (полный self-host Supabase не влезает рядом с VPN). Auth/Realtime — интерим (anonymous id + polling), позже отдельным ADR.

## [2026-07-01] TLS Let's Encrypt TLS-ALPN-01 на :443 — ADR-0003
Домен GoDaddy A→сервер напрямую; :80 закрыт. Caddy авто-выпуск/продление на :443.

## [2026-07-01] Щедрые лимиты памяти контейнеров — ADR-0004
app 1G / pg 1G (shared_buffers 128MB) / caddy 128M — защита VPN-ноды от OOM.

## [2026-07-01] Дисковая гигиена/автоочистка + swap 4G — ADR-0005
Ротация логов Docker, scoped-очистка образов, weekly timer, ротация бэкапов, df-watchdog, swappiness=10.

## [2026-07-01] Образы под linux/arm64 — ADR-0006
exit-fi оказался ARM (aarch64). Собираем кросс-сборкой buildx `--platform linux/arm64` + binfmt. `deploy.sh` делает это сам. Обычный amd64-билд не запускается на сервере.
