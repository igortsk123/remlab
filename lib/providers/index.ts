// Фабрики провайдеров ИИ. Сейчас обе задачи (генерация картинок и анализ фото) закрывает Gemini,
// т.к. ключ доступен и стоимость приемлема (см. decisions). Провайдер под задачу можно сменить здесь,
// не трогая вызывающий код (напр. поставить OpenAI на vision, когда появится ключ).

import { providerEnv } from "@/lib/env";
import { createGeminiProvider } from "@/lib/providers/gemini";
import { createGatewayProvider } from "@/lib/providers/gateway";
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

export type {
  ImageProvider,
  VisionProvider,
  ProviderError,
  ImageData,
  ImageGenInput,
  VisionInput,
} from "@/lib/providers/types";
