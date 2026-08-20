# remlab (remont-lab)

B2C-сервис **«Смета-first» (v0.4, ADR-0016)**: расчёт ремонта/материалов → смета-список с
реф-ссылками (комиссия, в т.ч. с юзерских ссылок) → хвосты: AI-визуализация и мастера-лиды.
Мастер-план — `.memory_bank/plans/MASTER-cost-first.md` (М0–М7). Рынок РФ (Гдеслон) → UK.
Стек: TS strict + Next.js (App Router) + Drizzle + Zod + Inngest + self-host postgres/pgvector +
Gemini (Vertex/fal запас) + YooKassa + PostHog (детали — `core/architecture.md`).
Стадия: **Stage 1 задеплоен** (`remont-lab.online`), трейсинг, Метрика, Директ (4 кампании
+ автопилот dry-run). ⚠️ Ядро сметы (М1–М3) не построено —
код-долг v0.4.
Владелец не пишет код → приоритет самопроверяемости (тесты/CI/observability/гардрейлы).

## Память и старт
Tier 0 = этот файл + импортированный INDEX + `.claude/rules/*.md` (auto); Tier 2 =
`.memory_bank/**` + `docs/*` по decision tree.
@.memory_bank/INDEX.md
Сначала прочитай: `source-of-truth.md` (истина при конфликте) → `project-state.md` (где проект).
При компакции сохранить: активный план (slug+статус), изменённые файлы, команды тестов,
next steps, содержимое `_intake/session-scratch.md`.

## Критично
- **Конец задачи = `/memory-check`.** План не `completed`, пока durable сессии не в `.memory_bank/` и audit не «чисто».
- **План first, code second** — `.claude/rules/agent-workflow.md`. Без явного «деплой» код не пишем.
- **Гипотезы, не аксиомы:** спека — набор гипотез; отклонился обоснованно → запиши в `docs/DECISIONS.md`.
- **Сложное/неоднозначное/рискованное решение:** сначала свой вывод, потом скилл `ask-codex` (независимое второе мнение) — и только затем финализируй. Полное правило — `.claude/rules/codex-adviser.md`.

## Команды
`pnpm test` · `pnpm e2e` · `pnpm typecheck` · `pnpm lint` · `pnpm db:migrate` · `pnpm build` · `./deploy.sh`

## Решения человека (не Claude)
Гдеслон-аккаунт и выбор партнёрок (мастера); кэшбек юзеру; цены paid-ступеней; выбор модели после бенча; источники прайсов/каталога; дизайн экранов; юр. вопросы.

## Path-scoped правила (.claude/rules/)
`agent-workflow` (план→деплой, всегда) · `memory-discipline` (память, всегда) ·
`codex-adviser` (когда обязателен независимый разбор Codex, всегда) ·
`code-standards` (ts/tsx) · `ui-rules` (app/components tsx) · `pipeline-tracing` (ADR-0013).
