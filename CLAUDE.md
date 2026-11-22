# remlab (remont-lab)

B2C-сервис **«Смета-first» (v0.4, ADR-0016)**: расчёт ремонта/материалов → смета-список с
реф-ссылками (комиссия, в т.ч. с юзерских ссылок) → хвосты: AI-визуализация и мастера-лиды.
Мастер-план — `plans/MASTER-cost-first.md` (М0–М7). Рынок РФ (Гдеслон) → UK.
Стек: TS strict + Next.js + Drizzle + Zod + Inngest + self-host postgres/pgvector + Gemini +
YooKassa + PostHog (`core/architecture.md`).
Стадия: **ядро сметы М1–М3 в проде** (`remont-lab.online`), Директ (автопилот dry-run).
**Фокус — М5 «мебельный трек»** (каталог → меши на Salad → демо для партнёра) по решению
владельца 05.09 (ADR-0187): до принятия демо, затем М2–М4. Снимок — `project-state.md`.
Владелец не пишет код → приоритет самопроверяемости (тесты/CI/observability/гардрейлы).
**Говорить с владельцем просто:** без терминов, кратко, каждый пункт — с «зачем» (правило 05.09).

## Память и старт
Tier 0 = этот файл + INDEX + `.claude/rules/*.md`; Tier 2 = `.memory_bank/**` + `docs/*`.
@.memory_bank/INDEX.md
Сначала: `source-of-truth.md` (истина при конфликте) → `project-state.md` (где проект).
При компакции сохранить: активный план (slug+статус), изменённые файлы, next steps, блокнот.

## Критично
Все правила работы — реестр `.memory_bank/rules/` (свод 20.11.2026): строка на правило — `.claude/rules/00-operating-index.md`,
четыре гейта — `.claude/rules/10-decision-gates.md`. Главное: конец задачи = `/memory-check` (P-046); план first, code second (P-044);
две роли — ведущий и рабочий, владелец говорит с ведущим (P-013); сложное решение — вывод → `ask-codex` → финал (P-048); гипотезы, не аксиомы (P-012).

## Команды
`pnpm test` · `pnpm e2e` · `pnpm typecheck` · `pnpm lint` · `pnpm db:migrate` · `pnpm build` · `./deploy.sh`

## Решения человека (не Claude)
Партнёрки/Гдеслон; кэшбек; цены paid-ступеней; модель после бенча; источники прайсов; дизайн экранов; юр. вопросы.

## Path-scoped правила (.claude/rules/)
всегда: `00-operating-index` · `10-decision-gates` · `review-checklist` (остальные — указатели в реестр); по путям:
`code-standards` (ts/tsx) · `ui-rules` (app/components) · `pipeline-tracing` (ADR-0013).
