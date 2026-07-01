---
tier: 1
topic: access-and-integrations
scope: Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде
tier2: ""
updated: 2026-07-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-01
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Значения секретов тут НЕ хранятся — только ГДЕ они и КАК устроен доступ.

## Провайдеры ИИ (Stage 1, M0)

### Google Gemini — активен ✅
- **Задачи:** генерация картинок И анализ фото/текст (одним ключом закрыты обе).
- **Модели:** картинки — `gemini-3.1-flash-image` (Nano Banana 2); текст/зрение — `gemini-flash-latest`.
- **Эндпоинт:** `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`,
  заголовок `X-goog-api-key`. Картинка: `generationConfig.responseModalities:["IMAGE"]`, ответ —
  `candidates[0].content.parts[].inlineData{mimeType,data(base64)}`.
- **Ключ:** `GEMINI_API_KEY` — только в `.env`/`.env.local` (gitignore), на сервере `/opt/remlab/.env`.
  Значение НЕ в git/памяти. Проверен рабочим 2026-07-01.
- **Клиент в коде:** `lib/providers/gemini.ts` (fetch, без SDK) за интерфейсами `lib/providers/types.ts`.
  Фабрики — `lib/providers/index.ts` (`getImageProvider` / `getVisionProvider`). Ошибки — `Result<T,E>`.
- **Смоук:** `pnpm smoke:providers` (реальный вызов, не в CI). Юнит на моках — `tests/unit/providers.test.ts`.

### OpenAI — «розетка» на будущее (не активен)
- Провайдер сменный: `OPENAI_API_KEY` в env → отдельный клиент можно поставить на vision в `index.ts`
  без правок вызывающего кода. В соседнем `v0-health-card` ключа OpenAI НЕТ (проверено 2026-07-01).

## Цены (ориентир, 2026)
- Картинка Gemini 3.1 Flash Image: ~$0.045 (512px) / ~$0.067 (1K) / batch −50% (~$0.034 за 1K).
- Анализ фото (vision-вход): доли цента у всех (~$0.0002–0.001/фото) — не лимитирующий фактор.
- Вывод: главный денежный рычаг Stage 1 — стоимость **генерации** картинки; резолюция под free/paid — рычаг.

**Tier 2:** нет отдельного дока; детали решения — `decisions.md` (ADR-0007), код — `lib/providers/`.
