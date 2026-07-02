// Фабрики провайдеров ИИ. Сейчас обе задачи (генерация картинок и анализ фото) закрывает Gemini,
// т.к. ключ доступен и стоимость приемлема (см. decisions). Провайдер под задачу можно сменить здесь,
// не трогая вызывающий код (напр. поставить OpenAI на vision, когда появится ключ).

import { providerEnv } from "@/lib/env";
import { createGeminiProvider } from "@/lib/providers/gemini";
import { createFakeProvider } from "@/lib/providers/fake";
import { instrumentImageProvider, instrumentVisionProvider } from "@/lib/providers/traced";
import type { ImageProvider, VisionProvider } from "@/lib/providers/types";

const fakeEnabled = () => process.env.REMLAB_FAKE_AI === "1";

function requireGeminiKey(): string {
  const key = providerEnv().GEMINI_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY is not set (.env)");
  return key;
}

// Провайдеры оборачиваются в инструментированную версию: каждый вызов LLM логируется в активный
// прогон (ADR-0013). Нет прогона → passthrough (обёртка ничего не пишет).
export function getImageProvider(): ImageProvider {
  const base = fakeEnabled() ? createFakeProvider() : createGeminiProvider(requireGeminiKey());
  return instrumentImageProvider(base);
}

export function getVisionProvider(): VisionProvider {
  const base = fakeEnabled() ? createFakeProvider() : createGeminiProvider(requireGeminiKey());
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
