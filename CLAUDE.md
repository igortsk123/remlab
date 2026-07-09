# remlab (remont-lab)

B2C AI-помощник по ремонту/обновлению комнаты: фото → AI-визуализация → реальные товары из фидов.
Бизнес-модель **v0.3** (affiliate-first freemium, 3 ступени: бесплатно/1 490 ₽/9 900 ₽) — истина в
`docs/master-brief-v0.3.md`, выжимка — `product_brief.md` + `core/market.md`; движок «одно фото →
подбор в масштабе» — `core/goals.md`. Рынок РФ (фиды Гдеслон) → UK, архитектура locale-agnostic.
Стек: TS strict + Next.js (App Router) + Drizzle + Zod + Inngest + self-host postgres/pgvector +
Gemini (Vertex/fal запас) + YooKassa + PostHog (детали — `core/architecture.md`).
Стадия: **Stage 1 задеплоен** (`remont-lab.online`) + трейсинг (ADR-0013). ⚠️ Пивот v0.2→v0.3
(ADR-0014): товары открыть с реф-ссылками, paywall на «комнату целиком+сервис» — код-долг.
Владелец не пишет код → приоритет самопроверяемости (тесты/CI/observability/гардрейлы).

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
- **Конец задачи = `/memory-check`.** План не `completed`, пока durable сессии не в `.memory_bank/` и audit не «чисто».
- **План first, code second** — `.claude/rules/agent-workflow.md`. Без явного «деплой» код не пишем.
- **Гипотезы, не аксиомы:** спека — набор гипотез; отклонился обоснованно → запиши в `docs/DECISIONS.md`.
- **Не ломать VPN-ноду на exit-fi** (`89.167.127.0` делит хост с боевым внутренним VPN): бэкап+rollback перед правками сервера, изолированная docker-сеть `remlab-net`, лимиты памяти.
- **Секреты только в `.env` на сервере**, не в git и не в Memory Bank.
- **Не реализуй юридическую логику** (ПДн/лицензии) — ставь TODO, не блокируйся.
- При конфликте источников — `source-of-truth.md` решает; для живых фактов прод wins, затем обновить память.
- **Память — только в `.memory_bank/`** (в git), не в локальной памяти Клода. Меняется архитектура/контракты → фиксируй сразу (`.claude/rules/memory-discipline.md`). **В конце сессии — `/memory-check`** (единый свод в Memory Bank + гигиена). Как это работает: `.memory_bank/guides/memory-automation.md`.

## Команды (после S3)
`pnpm test` · `pnpm e2e` · `pnpm typecheck` · `pnpm lint` · `pnpm db:migrate` · `pnpm build` · `./deploy.sh`

## Решения человека (не Claude)
Граница/цена free-paid; сколько hero в paid; финальный выбор модели после бенча; источники каталога/расценок; дизайн экранов; юридические вопросы. (Спека §16.)

## Path-scoped правила (.claude/rules/)
- `agent-workflow.md` — workflow план→деплой (всегда).
- `memory-discipline.md` — когда сохранять/извлекать/синхронизировать память (всегда).
- `code-standards.md` — TS/TSX стандарты (`**/*.{ts,tsx}`).
- `ui-rules.md` — UI-конвенции (`app/**/*.tsx`, `components/**/*.tsx`).
- `pipeline-tracing.md` — трейсинг AI-пайплайна не отстаёт от смены модели/промпта/шага (ADR-0013).
