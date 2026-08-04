---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, eval, гардрейлы, DoD
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-08-04
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-11
review_after: ""
---

# Regression Net — Tier 1 (сверено 2026-07-11)

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** flow-pipeline, health, providers, restyle-prompt, trace-sign,
  trace. Интеграция с БД — только `pg-repository.test.ts` (skipIf без `TEST_DATABASE_URL`).
  Мок моделей — fake-провайдер (`REMLAB_FAKE_AI=1`).
- **e2e:** happy path `flow.spec.ts` (через /select) + 3 smoke; error-путей НЕТ.
- **CI-гейт (`ci.yml`, S4):** postgres (pgvector/pgvector:pg17) → install → typecheck → lint →
  test → build → e2e. Шага db:migrate НЕТ (таблицу тест создаёт сам). Красный = merge запрещён.
- **Observability:** трейс каждого LLM-вызова (`traced.ts`/`lib/trace/`; costUsd/шаг,
  total_cost_usd/прогон); PostHog (`lib/analytics.ts`) — 5 из 9 событий. Sentry НЕ заводим.
- **Грабля 2026-07-11:** смена флоу (7f970ad, экран /select) без правки e2e → gate красный
  9 дней, никто не заметил. Меняешь флоу — правь e2e в том же коммите; после push смотри gate.
- **Гарантии памяти (кит Memory Bank v1.6.0, ADR-0055):** аудит `tools/memory-audit.mjs` + 4 хука
  (`session-reminder.mjs` — Stop-гейт `--block`, `precompact-guard.mjs`, `session-freshness.mjs`,
  `read-logger.mjs`) лежат **в git**. Раньше `.gitignore` прятал `tools/*`, и хуки существовали
  только на одной машине: команды хуков обёрнуты в `[ -f ... ]`, поэтому отсутствие файла — не
  ошибка, а тишина. **Хук, которого нет в репозитории, гарантией не является** — это тот же класс
  провала, что и красный gate, которого никто не смотрит.
- **Сверка память↔код:** аудит сравнивает дату коммита кода по backtick-ссылкам из доков с их
  `last_verified` (`CODE-DRIFT`). На 2026-08-04 — 9 доков-должников при формально чистом аудите;
  покрытие сверки 17/17 доков со ссылками на код. Это предупреждения: gate ими не блокируется.

## Цель (спека §12) — НЕ реализовано
- Тесты: Cost Engine/matching/work_types/гардрейлы (модулей нет); интеграционные API/миграции;
  RLS (в БД нет); e2e error-пути (плохое фото, инференс, таймаут). Статусов
  done/failed/needs_better_photo НЕТ; генерация — синхронный POST без Realtime/Inngest.
  Платежи демо.
- Гардрейлы стоимости: maxCostUsd; квота free-генераций юзер/IP; потолок + kill-switch;
  nCandidates=1 на free. Сейчас generate без лимитов.
- Eval-харнесс (§12.5): `/eval` (Python) нет; план — 30–50 золотых фото, LPIPS/SSIM + CLIP;
  интерим — ручная рубрика (§8).
- Дашборд стоимости инференса.
- v0.4: golden-формулы смет (комнаты→количества) — CI-тест (мастер).

**DoD (цель-чеклист):** typecheck/lint/тесты ✓; e2e +≥1 путь ошибки; UX всех ошибок; события
эмитятся; env задокументированы; отклонения → DECISIONS.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
