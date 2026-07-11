# remlab (remont-lab)

B2C-сервис **«Смета-first» (v0.4, ADR-0016)**: расчёт ремонта/материалов → сохранённая
смета-список с реф-ссылками (комиссия — и со ссылок самого юзера, deeplink) →
хвосты: AI-визуализация по фото и мастера-лиды. Входы: калькуляторы материалов и «сколько стоит ремонт». **Мастер-план — `.memory_bank/plans/MASTER-cost-first.md`** (М0–М7
+ сценарий). Модель v0.3 (`docs/master-brief-v0.3.md`) — истор. база ступени М5.
Рынок РФ (Гдеслон) → UK, locale-agnostic.
Стек: TS strict + Next.js (App Router) + Drizzle + Zod + Inngest + self-host postgres/pgvector +
Gemini (Vertex/fal запас) + YooKassa + PostHog (детали — `core/architecture.md`).
Стадия: **Stage 1 задеплоен** (`remont-lab.online`), трейсинг, Метрика, Директ (4 кампании
+ автопилот dry-run). ⚠️ Ядро сметы (М1–М3) не построено —
код-долг v0.4.
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
- Конфликты — `source-of-truth.md`; живые факты: прод wins → обновить память.
- **Память — только в `.memory_bank/`** (в git), не в локальной памяти Клода. Меняется архитектура/контракты → фиксируй сразу (`.claude/rules/memory-discipline.md`). **В конце сессии — `/memory-check`** (единый свод в Memory Bank + гигиена). Как это работает: `.memory_bank/guides/memory-automation.md`.

## Команды
`pnpm test` · `pnpm e2e` · `pnpm typecheck` · `pnpm lint` · `pnpm db:migrate` · `pnpm build` · `./deploy.sh`

## Решения человека (не Claude)
Гдеслон-аккаунт и выбор партнёрок (мастера); кэшбек юзеру; цены paid-ступеней; выбор модели после бенча; источники прайсов/каталога; дизайн экранов; юр. вопросы.

## Path-scoped правила (.claude/rules/)
`agent-workflow` (план→деплой, всегда) · `memory-discipline` (память, всегда) ·
`code-standards` (ts/tsx) · `ui-rules` (app/components tsx) · `pipeline-tracing` (ADR-0013).
