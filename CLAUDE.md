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

## Память и старт
Tier 0 = этот файл + `.claude/rules/*.md` (auto) → Tier 1 = `.memory_bank/INDEX.md`
(decision tree) → Tier 2 = `.memory_bank/**` + `docs/*` по мере нужды.
Сначала прочитай: `INDEX.md` → `source-of-truth.md` (истина при конфликте) →
`project-state.md` (где проект) → далее по decision tree.

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
`agent-workflow` (план→деплой, всегда) · `memory-discipline` (память, всегда) ·
`code-standards` (ts/tsx) · `ui-rules` (app/components tsx) · `pipeline-tracing` (ADR-0013).
