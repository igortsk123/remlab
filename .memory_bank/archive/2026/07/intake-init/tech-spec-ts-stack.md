# Итоговая техническая спека для Claude Code
## AI-помощник по ремонту квартиры — TS-стек, соло-разработка через Claude Code

> **Аудитория и режим.** Владелец проекта — один человек, сильный в архитектуре и БД, **не пишет код**, всё реализует через Claude Code. Главный приоритет — НЕ скорость кода, а **минимум движущихся частей + сетка, которая ловит регрессии и ошибки автоматически** (тесты, CI, observability, eval, гардрейлы).
> **Слои документов.** Продуктовый слой — в `cjm-ux-v0.2.md`. **Этот документ — инженерный слой.**
> **Вне scope.** Юридические/комплаенс-вопросы решаются владельцем отдельно (ставить TODO, не блокироваться).
> **Как читать:** всё ниже — **гипотезы с допущениями, а не аксиомы**. 🎯 гипотеза · 🧩 что спорно · 🔍 проверить · 🔁 fallback · ✅ done-when.

---

## §0. Как Claude Code должен работать в этом репозитории (operating manual)

1. **Гипотезы, не аксиомы.** Любой контракт/схема/выбор — переформулируй допущение, проверь, при несоответствии отклонись и запиши почему в `docs/DECISIONS.md` (ADR: контекст → решение → последствия).
2. **Маленькие вертикальные срезы.** Один срез = одна пользовательская способность от UI до БД, с тестами и observability. Готов только когда проходит §12.2 (DoD).
3. **Тест рядом с кодом.** Unit на чистую логику + e2e на затронутый поток. Нет e2e на критический поток → срез не готов.
4. **Перед «готово» — весь гейт** (§12.3): typecheck + lint + unit + integration + e2e + build.
5. **Никогда не оставляй внешний вызов без обёртки** (модель/БД/платёж): типизированный результат, ретрай через Inngest, заданное user-facing состояние ошибки (§12.8).
6. **Скоропортящееся — сверяй перед wiring** (id моделей, лимиты, цены): открой актуальную доку (§17).
7. **Спрашивай владельца только по списку человеческих решений** (§16). Остальное — сам + ADR.
8. **Каждый PR/срез = зелёный CI + обновлённый `CLAUDE.md`/ADR** при отклонениях.

🎯 Корневой `CLAUDE.md`: ссылки на этот файл и CJM; правило «гипотезы, не аксиомы»; команды (`pnpm test/e2e/typecheck/lint/db:migrate`); DoD (§12.2); список человеческих решений (§16); правило «не реализуй юридическую логику».

---

## §1. Стек (финальный, TS-first)

🎯 Один TS end-to-end: соло + не-кодер → два рантайма = два деплоя и класс ошибок, которые владелец не читает. Сквозные типы (Zod) убирают рассинхрон фронт↔бэк.

| Слой | Дефолт | Fallback |
|---|---|---|
| Язык | **TypeScript (strict)** | — |
| Пакетменеджер | **pnpm** | npm |
| Фреймворк | **Next.js (App Router)** full-stack | разнести фронт/бэк позже |
| Данные/BaaS | **Supabase**: Postgres+pgvector, Auth, Storage, Realtime | Neon + Clerk + S3 |
| ORM/миграции | **Drizzle** (нативный pgvector, raw SQL) | Prisma |
| Контракты | **Zod** на каждой границе API | — |
| Фоновые джобы | **Inngest** (durable, ретраи, concurrency) | Trigger.dev |
| Статус джобы → клиент | **Supabase Realtime** | polling строки job |
| Инференс | **Vertex AI** (Gemini/Nano Banana) + **fal**/**Replicate** за провайдер-интерфейсом | смена провайдера |
| Эмбеддинги | хостед CLIP → pgvector | self-host позже |
| Платежи | **YooKassa** (REST + webhook) | CloudPayments |
| Error tracking | **Sentry** (`@sentry/nextjs`) | Highlight.io |
| Аналитика | **PostHog** (события + флаги + replay) | — |
| Тесты | **Vitest** + **Playwright** | — |
| CI | **GitHub Actions** (блокирующий гейт) | — |
| Хостинг | **Vercel** + Inngest | long-running контейнер (Railway/Render) |

> 📌 Наш деплой отличается от дефолта хостинга: **self-host в docker-compose на Hetzner** (Next.js + postgres+pgvector контейнером), Caddy+LE. См. `_intake/history/deploy-and-decisions.md` / `.memory_bank/deployment.md`.

🧩 **Критический gotcha:** длинный инференс (30–45 с) НЕЛЬЗЯ запускать внутри обычного Next.js route (таймаут). Паттерн: API-route создаёт job-строку → событие в Inngest → возвращает `job_id`; клиент подписывается через Realtime/polling. Тяжёлую работу исполняет Inngest-функция (durable, ретраи).

---

## §2. Структура репозитория

🎯 Один Next.js-проект. Python — только изолированный `/eval`, НЕ деплоится.

```
/app          # Next.js App Router: (marketing) лендинг, (flow) 7-экранный flow, (workspace), /api
/modules      # ЯДРО: room-analysis, visual-generation, product-matching, cost-engine,
              #        catalog, payments, export, generation-job. Каждый = папка + index.ts (контракт) + impl + тесты
/db           # Drizzle: schema.ts, migrations/, seed/
/contracts    # Zod-схемы (single source of truth I/O)
/lib          # провайдеры (inference, embeddings), db client, sentry, posthog
/inngest      # Inngest functions + client
/e2e          # Playwright
/eval         # Python: eval-харнесс (LPIPS/SSIM/CLIP), не в рантайме
/docs         # spec, CJM, DECISIONS.md (ADR)
CLAUDE.md
```

🧩 Модули общаются ТОЛЬКО через `index.ts` → можно выдрать модуль в сервис позже.

---

## §3. Контракты модулей (Zod-first)

### 3.1. `visual_generation` (двухрежимный) [ЯДРО]
```ts
export const VisualGenInput = z.object({
  baseImageUrl: z.string().url(),
  mode: z.enum(["free", "compose"]),          // free=generate-then-match, compose=catalog-constrained
  styleProfile: StyleProfileSchema,
  keepObjects: z.array(z.string()),
  replaceZones: z.array(z.string()),
  catalogItemRefs: z.array(z.object({          // ТОЛЬКО mode="compose"
    productId: z.string(), referenceImageUrl: z.string().url(), targetZone: z.string(),
  })).default([]),
  nCandidates: z.number().int().min(1).max(4).default(1),
  maxCostUsd: z.number(),                       // ГАРДРЕЙЛ на вызов (§12.6)
});
export const VisualGenOutput = z.object({
  candidates: z.array(z.object({ url: z.string().url(), structureScore: z.number().nullable(), styleScore: z.number().nullable() })),
  modelUsed: z.string(), costUsd: z.number(), latencyMs: z.number().int(),
});
```
🧩 `nCandidates>1` на free дорого — на free держать 1.

### 3.2. `room_analysis`
```ts
export const RoomAnalysisOutput = z.object({
  detectedRoomType: z.string(),
  qualityScore: z.number(),                    // <порог -> просим перефото
  qualityIssues: z.array(z.string()),
  objects: z.array(z.object({
    type: z.string(), confidence: z.number(),
    suggestedAction: z.enum(["keep","replace","optional"]),
    bbox: z.tuple([z.number(),z.number(),z.number(),z.number()]).nullable(),
  })),
  structureHints: z.record(z.unknown()),       // окно/радиатор/балкон как "не трогать"
});
```
🧩 Возможно один VLM-вызов, отдельный детектор (Grounding DINO/SAM) НЕ нужен.

### 3.3. `product_matching` (двухрежимный)
```ts
export const ProductMatchInput = z.object({
  mode: z.enum(["post_hoc","catalog_constrained"]),
  queryImageUrl: z.string().url().nullable(),  // post_hoc: кроп зоны рендера
  styleProfile: StyleProfileSchema, category: z.string(),
  hardFilters: z.object({
    priceMin: z.number().int().nullable(), priceMax: z.number().int().nullable(),
    city: z.string().nullable(), mustBeAvailable: z.boolean().default(true),
    fitDimensions: z.record(z.number()).nullable(),
  }),
});
// Output: items[] с rankScore и explanation "почему подобран"
```
🧩 Веса ранжирования — в КОНФИГ. monetization-boost capped (комиссия не перебивает релевантность).

### 3.4. `cost_engine` (детерминированный, НЕ модель) [Stage 1B]
```ts
export const CostEstimateInput = z.object({
  cityId: z.string(), roomType: z.string(), areaM2: z.number().nullable(),
  interventionLevel: z.enum(["refresh","budget_update","light_cosmetic"]),
  confirmedScope: z.array(WorkItemSchema), materialLevel: z.enum(["econom","mid","comfort"]),
});
export const CostEstimateOutput = z.object({
  totalMin: z.number().int(), totalMax: z.number().int(),
  lines: z.array(EstimateLineSchema), confidence: z.enum(["low","mid","high"]),
  assumptions: z.array(z.string()), missingDataForHigherConfidence: z.array(z.string()),
});
```
🧩 Жёсткое правило: число считает движок по rate-таблицам; модель НЕ возвращает сумму. Идеальная цель для unit-тестов.

### 3.5. Прочее
- `catalog`: ingest → normalize → dedup → enrich → embed → approve → publish + freshness-чек.
- `payments`: createPayment(YooKassa) → webhook → идемпотентный `room_pack_unlocked`.
- `export`: printable HTML room pack → PDF.
- `generation-job`: Inngest-функция room_analysis → visual_generation → product_matching; пишет cost/latency; ретраи; статусы в job-строку.

---

## §4. Модель данных / миграции (Drizzle/Postgres)

> Денормализация ради чтения workspace; индексы (city, status, paid, embeddings); снапшоты цен. **RLS с первого дня** — регресс-защита от утечки чужих данных.

Основные таблицы: `users, properties, rooms, room_projects, result_versions, style_profiles, uploaded_images, detected_objects, generation_jobs, generated_images, products, product_embeddings (vector(768)), price_snapshots, product_previews, cities, work_types, work_rates, material_categories, material_rates, room_type_coefficients, intervention_level_coefficients, complexity_coefficients, cost_estimates, estimate_lines, payments`.

Индексы: hnsw/ivfflat на `image_embedding`; btree `(category_normalized, price_current, availability)`.
🧩 Размерность `vector(768)` — под эмбеддер; HNSW vs IVFFlat — по объёму каталога. Миграции обратимые (down).
> Полная схема полей — в исходной спеке (§4) и в `cjm-ux-v0.2.md` §13.

---

## §5. Жизненный цикл генерации (async)
1. POST `/api/generate` → Zod → `generation_jobs`(queued) → `inngest.send("generation/requested")` → `{jobId}`.
2. Клиент подписывается на строку job (Realtime / polling каждые 2 с).
3. Inngest-функция (durable, `step`): quality-check → (needs_better_photo стоп) → room_analysis → visual_generation (maxCostUsd, ретраи) → product_matching → запись `generated_images`, status=done, cost/latency. На ошибке после N ретраев → failed + Sentry.
4. Идемпотентность по status — повторное событие не плодит генерации.

```ts
export const generation = inngest.createFunction(
  { id: "generation", concurrency: { limit: 5 }, retries: 3 },
  { event: "generation/requested" },
  async ({ event, step }) => {
    const job = await step.run("load-job", () => loadJob(event.data.jobId));
    const q = await step.run("quality", () => checkQuality(job));
    if (!q.ok) return setStatus(job, "needs_better_photo");
    const analysis = await step.run("analyze", () => analyzeRoom(job));
    const gen = await step.run("generate", () => generate(job, analysis));
    const products = await step.run("match", () => matchProducts(job, gen));
    return step.run("finalize", () => finalize(job, gen, products));
  }
);
```

---

## §6. Auth и жизненный цикл пользователя
guest (anonymous sign-in) → registered (линковка anonymous→email/OAuth, данные гостя НЕ теряются) → paid (`room_projects.paid_status` после webhook). RLS: юзер видит только своё; тест RLS — часть e2e.
🔍 https://supabase.com/docs/guides/auth/auth-anonymous
> В нашем self-host: Auth решается по мере фич (интерим — простой anonymous session id; полноценный Supabase Auth либо GoTrue-контейнер позже). Зафиксировать в ADR.

## §7. Платежи
YooKassa: createPayment → confirmation → webhook `payment.succeeded` → идемпотентно `paid_status` + `room_pack_unlocked`. Идемпотентность по `provider_payment_id`. Sandbox.

## §8. Выбор модели генерации + протокол самопроверки
| Роль | Дефолт | Запасной |
|---|---|---|
| Free (дёшево/быстро) | Seedream 4.5 (`fal-ai/bytedance/seedream/v4.5/edit`) | FLUX.2 [dev] Turbo |
| Paid (контроль/консистентность) | Nano Banana Pro (Gemini 3 Pro Image, Vertex) | Seedream 4.5 |
| Опц. self-host | Qwen-Image-Edit-2511 | — |

🧩 Важна **content consistency** (сохранить комнату/объект) → Seedream/Nano Banana лидируют, GPT-Image НЕ дефолт.
Маски/depth почти не нужны (instruction-модели сами сохраняют структуру); точечный SAM on-demand — только для пиксельной сохранности объекта в paid.
**Протокол самопроверки (до wiring):** 30–50 реальных русских фото → бриф «оставь {объект}, обнови {зоны} в стиле {X}» → рубрика: геометрия ≥80%, keep-объект ≥75%, стиль ≥70%, реализм ≥4.0/5, латентность <45с (paid), стоимость/кадр держит маржу. Результаты → DECISIONS.

## §9. Связка картинка↔товар
Гибрид: free=generate-then-match (вдохновение), paid=compose по 1–3 hero + generate-then-match по остальным. Метрика: воспринимаемое совпадение «товар по ссылке ≈ товар на картинке» по hero (цель заметно выше рыночного потолка ~60%).

## §10. Каталог и ingest
Старт — курируемый каталог 800–1500 SKU. Пайплайн: ingest → normalize → dedup (source_shop+external_id + перцептивный хэш) → enrich → embed (CLIP→pgvector) → manual approve → publish → freshness-чек (Inngest cron). Обещания «размер/наличие» только где есть данные; иначе warning.

## §11. Cost Engine (детерминированный)
Движок по rate-таблицам считает диапазон; модель только определяет scope и объясняет. Seed: ~8 work_types × 3 города + ~15–20 материалов × 3 города (Москва/СПб/+регион). Результат: диапазон + что включено + что меняет сумму + confidence (low/mid/high).

---

## §12. РЕГРЕСС-ЗАЩИТА (главный раздел для соло-не-кодера)

**12.1 Тесты:** Unit (Vitest) на чистую логику (Cost Engine, ранжирование, мапперы, style_profile→prompt, гардрейлы); Integration (Vitest + тестовая БД) на API/RLS/миграции/Zod, внешние — мокать; e2e (Playwright) критические потоки + пути ошибок (happy path; generation lifecycle; paywall; failure paths). Нет e2e на затронутый поток → срез не готов.

**12.2 Definition of Done:** typecheck ✓, lint ✓, unit+integration ✓, e2e (+≥1 путь ошибки) ✓, все состояния ошибки имеют UX, события PostHog/Sentry эмитятся, нет секретов/новые env задокументированы, миграция обратима и на чистой БД, отклонения в DECISIONS.

**12.3 CI-гейт (GitHub Actions):** postgres pgvector service → checkout → pnpm install → typecheck → lint → db:migrate → test → build → playwright install → e2e. Красный гейт = merge запрещён.

**12.4 Observability:** Sentry (все ошибки фронт/бэк/Inngest с job_id/user_id/mode); структурные логи на каждый внешний вызов (провайдер, модель, latency, cost, успех/ошибка); трейс generation_job; PostHog события всего flow; дашборд стоимости инференса.

**12.5 Eval-харнесс (Python, /eval, не в рантайме):** золотой набор 30–50 фото + брифы; авто-прокси LPIPS/SSIM по «оставленным» зонам + CLIP-сходство к стилю; cron + перед сменой модели/промпта; отчёт было/стало. MVP-интерим: ручная рубрика §8.3 + CLIP хостед.

**12.6 Гардрейлы стоимости [Stage 1]:** maxCostUsd на вызов; квота бесплатных генераций на юзера/IP; Inngest concurrency.limit; дневной потолок + kill-switch (PostHog флаг); nCandidates=1 на free.

**12.7 Golden-path smoke:** быстрый Playwright happy-path с моками после каждого изменения (локально + CI).

**12.8 Ошибки:** внешние вызовы → типизированный `Result<T,E>`; ретраи через Inngest step; на каждое состояние — заданный UX (needs_better_photo, generation_failed, payment_failed, product_unavailable); не показывать сырой стек.

**12.9 Анти-дрейф контрактов:** Zod-схемы в `/contracts` — единственный источник I/O; типы `z.infer`; фронт и бэк импортируют одни схемы.

---

## §13. Env и конфиг
Секреты только в env (не в коде); `.env.example` в репо. Минимум: `DATABASE_URL`, `SUPABASE_*` (если используется), `INNGEST_*`, `FAL_KEY`, `GOOGLE_VERTEX_*`, `REPLICATE_API_TOKEN`, `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `SENTRY_DSN`, `POSTHOG_KEY`. Конфиг моделей/лимитов/весов — в env/конфиг, не в код.

## §14. Порядок сборки
- **Stage 0 — спайки:** латентность/регион инференса (из EU!); реальность фидов; cost-data (rates 3 города); mini-bench модели (§8.3). → ADR.
- **Stage 1 — каркас:** Next.js + БД + Drizzle + миграции + RLS + Auth (guest→registered) + лендинг + UX-оболочка 7 экранов + PostHog + Sentry + CI e2e happy-path (моки).
- **Stage 2 — генерация free:** generation-job (Inngest + Realtime/polling) + room_analysis + visual_generation(free) + гардрейлы + протокол §8.3.
- **Stage 3 — каталог + matching:** ingest + pgvector + product_matching(post_hoc) + ограниченный free-preview.
- **Stage 4 — paywall + платежи:** YooKassa + webhook + разблокировка + e2e paywall.
- **Stage 5 — compose-from-catalog (paid hero):** visual_generation(compose) + reference-image + метрика.
- **Stage 1B — Cost Engine:** движок + seed + unit-тесты + confidence.
- **Сквозное (§12) — с Stage 1.**

## §16. Решения человека (владельца)
1. Граница free/paid и цена room pack; модель монетизации. 2. Сколько hero в paid. 3. Финальный выбор модели после бенча §8.3. 4. Источники каталога и расценок. 5. Дизайн-направление экранов. 6. Юридические/комплаенс-вопросы (вне scope).

## §17. Ссылки (сверять перед wiring)
Next.js https://nextjs.org/docs • Supabase https://supabase.com/docs • Realtime https://supabase.com/docs/guides/realtime • Drizzle https://orm.drizzle.team/ • Zod https://zod.dev/ • Inngest https://www.inngest.com/docs • Vitest https://vitest.dev/ • Playwright https://playwright.dev/ • Sentry https://docs.sentry.io/platforms/javascript/guides/nextjs/ • PostHog https://posthog.com/docs • pgvector https://github.com/pgvector/pgvector • YooKassa https://yookassa.ru/developers/ • Vertex AI https://cloud.google.com/vertex-ai • fal https://fal.ai/models • Replicate https://replicate.com/docs • Seedream https://seed.bytedance.com/en/seedream4_5 • SAM2 https://github.com/facebookresearch/sam2

> ⚠️ Часть id моделей и лимитов перешороптится — открывай актуальную доку перед использованием и обновляй этот файл.

---
**Всё выше — гипотезы. Переформулируй, проверь, оспорь слабое, отклоняйся обоснованно — фиксируй в `docs/DECISIONS.md`.**
