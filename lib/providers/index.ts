// Фабрики провайдеров ИИ. Сейчас обе задачи (генерация картинок и анализ фото) закрывает Gemini,
// т.к. ключ доступен и стоимость приемлема (см. decisions). Провайдер под задачу можно сменить здесь,
// не трогая вызывающий код (напр. поставить OpenAI на vision, когда появится ключ).

import { providerEnv } from "@/lib/env";
import { createGeminiProvider } from "@/lib/providers/gemini";
import { createGatewayProvider, createGatewayTextProvider } from "@/lib/providers/gateway";
import { createFakeProvider } from "@/lib/providers/fake";
import { instrumentImageProvider, instrumentVisionProvider } from "@/lib/providers/traced";
import type { ImageProvider, VisionProvider } from "@/lib/providers/types";

const fakeEnabled = () => process.env.REMLAB_FAKE_AI === "1";

// ПРОВАЙДЕР ПО УМОЛЧАНИЮ — GEMINI ЧЕРЕЗ ШЛЮЗ VERCEL (владелец 14.10, ADR-0277): прямой ключ Google отключён.
// `AI_PROVIDER=gemini` возвращает прямой путь, если появится новый ключ.
function realProvider(): ImageProvider & VisionProvider {
  const env = providerEnv();
  if (env.AI_PROVIDER === "gemini") {
    if (!env.GEMINI_API_KEY) throw new Error("GEMINI_API_KEY is not set (.env)");
    return createGeminiProvider(env.GEMINI_API_KEY);
  }
  if (!env.VERCEL_AI_GATEWAY_KEY) throw new Error("VERCEL_AI_GATEWAY_KEY is not set (.env)");
  return createGatewayProvider(env.VERCEL_AI_GATEWAY_KEY);
}

// Провайдеры оборачиваются в инструментированную версию: каждый вызов LLM логируется в активный
// прогон (ADR-0013). Нет прогона → passthrough (обёртка ничего не пишет).
export function getImageProvider(): ImageProvider {
  const base = fakeEnabled() ? createFakeProvider() : realProvider();
  return instrumentImageProvider(base);
}

export function getVisionProvider(): VisionProvider {
  const base = fakeEnabled() ? createFakeProvider() : realProvider();
  return instrumentVisionProvider(base);
}

/**
 * ИЗВЛЕЧЕНИЕ ПОЛЕЙ ТОВАРА ПО ССЫЛКЕ — через шлюз Vercel (T-20261023-12, владелец 23.10: прямой ключ OpenAI пуст). Модель та
 * же, что была на прямом ключе (`gpt-4o-mini`, у шлюза — `openai/gpt-4o-mini`, та же цена), иначе поведение извлечения
 * поменялось бы без замера; `EXTRACT_MODEL` — другая модель шлюза. Ответ — строго JSON, срок 12 с (ждёт страница расчёта).
 * Ключ читается при каждом вызове (не из кэша `providerEnv`): нет ключа — ошибка, вызывающий пишет её в лог.
 */
export const EXTRACT_MODEL_DEFAULT = "openai/gpt-4o-mini";
export function getExtractProvider(): VisionProvider {
  if (fakeEnabled()) return instrumentVisionProvider(createFakeProvider());
  const key = process.env.VERCEL_AI_GATEWAY_KEY;
  if (!key) throw new Error("VERCEL_AI_GATEWAY_KEY is not set (.env)");
  const model = process.env.EXTRACT_MODEL || EXTRACT_MODEL_DEFAULT;
  return instrumentVisionProvider(createGatewayTextProvider(key, model, { json: true, timeoutMs: 12_000 }));
}

export type {
  ImageProvider,
  VisionProvider,
  ProviderError,
  ImageData,
  ImageGenInput,
  VisionInput,
} from "@/lib/providers/types";
