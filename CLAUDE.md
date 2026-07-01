# remlab (remont-lab)

B2C AI-помощник по ремонту/обновлению квартиры: фото комнаты → стиль через карточки → AI-preview → ограниченный бесплатный результат → платный room pack → workspace «Мои комнаты».
Стек: TypeScript (strict) + Next.js (App Router, full-stack) + Drizzle + Zod + Inngest + postgres/pgvector + внешний инференс (Vertex/fal/Replicate) + YooKassa + Sentry + PostHog + Vitest/Playwright + GitHub Actions.
Стадия: **bootstrap** (каркас + сервер + контейнер). Фичи Stage 1/1B — после каркаса, отдельными планами. Владелец не пишет код → приоритет: самопроверяемость (тесты/CI/observability/гардрейлы).

## Иерархия памяти
- **Tier 0 (auto-loaded):** этот файл + `.claude/rules/*.md` (path-scoped, грузятся по `paths:`).
- **Tier 1 (navigation):** `.memory_bank/INDEX.md` — приоритезированный decision tree.
- **Tier 2 (details):** `.memory_bank/**/*.md` + `docs/*` — полные документы по мере нужды (см. INDEX).

## Сначала прочитай
1. `.memory_bank/INDEX.md` — навигация: «задача → что читать».
2. `.memory_bank/source-of-truth.md` — что считать истиной при конфликте.
3. `.memory_bank/project-state.md` — где проект сейчас.
4. `docs/tech-spec-ts-stack.md` (инженерная спека) + `docs/cjm-ux-v0.2.md` (продукт) + `docs/DECISIONS.md`.

## Критично
- **План first, code second** — `.claude/rules/agent-workflow.md`. Без явного «деплой» код не пишем.
- **Гипотезы, не аксиомы:** спека — набор гипотез; отклонился обоснованно → запиши в `docs/DECISIONS.md`.
- **Не ломать VPN-ноду на exit-fi** (`89.167.127.0` делит хост с боевым внутренним VPN): бэкап+rollback перед правками сервера, изолированная docker-сеть `remlab-net`, лимиты памяти.
- **Секреты только в `.env` на сервере**, не в git и не в Memory Bank.
- **Не реализуй юридическую логику** (ПДн/лицензии) — ставь TODO, не блокируйся.
- При конфликте источников — `source-of-truth.md` решает; для живых фактов прод wins, затем обновить память.
- **Память — только в `.memory_bank/`** (в git), не в локальной памяти Клода. Меняется архитектура/контракты → фиксируй сразу (`.claude/rules/memory-discipline.md`). **В конце сессии — `/memory-consolidate`** (свод в Memory Bank), затем `/memory-check`. Как это работает: `.memory_bank/guides/memory-automation.md`.

## Команды (после S3)
`pnpm test` · `pnpm e2e` · `pnpm typecheck` · `pnpm lint` · `pnpm db:migrate` · `pnpm build` · `./deploy.sh`

## Решения человека (не Claude)
Граница/цена free-paid; сколько hero в paid; финальный выбор модели после бенча; источники каталога/расценок; дизайн экранов; юридические вопросы. (Спека §16.)

## Path-scoped правила (.claude/rules/)
- `agent-workflow.md` — workflow план→деплой (всегда).
- `memory-discipline.md` — когда сохранять/извлекать/синхронизировать память (всегда).
- `code-standards.md` — TS/TSX стандарты (`**/*.{ts,tsx}`).
- `ui-rules.md` — UI-конвенции (`app/**/*.tsx`, `components/**/*.tsx`).
