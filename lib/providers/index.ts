// Фабрики провайдеров ИИ. Сейчас обе задачи (генерация картинок и анализ фото) закрывает Gemini,
// т.к. ключ доступен и стоимость приемлема (см. decisions). Провайдер под задачу можно сменить здесь,
// не трогая вызывающий код (напр. поставить OpenAI на vision, когда появится ключ).

import { providerEnv } from "@/lib/env";
import { createGeminiProvider } from "@/lib/providers/gemini";
import { createFakeProvider } from "@/lib/providers/fake";
import type { ImageProvider, VisionProvider } from "@/lib/providers/types";

const fakeEnabled = () => process.env.REMLAB_FAKE_AI === "1";

function requireGeminiKey(): string {
  const key = providerEnv().GEMINI_API_KEY;
  if (!key) throw new Error("GEMINI_API_KEY is not set (.env)");
  return key;
}

export function getImageProvider(): ImageProvider {
  return fakeEnabled() ? createFakeProvider() : createGeminiProvider(requireGeminiKey());
}

export function getVisionProvider(): VisionProvider {
  return fakeEnabled() ? createFakeProvider() : createGeminiProvider(requireGeminiKey());
}

export type {
  ImageProvider,
  VisionProvider,
  ProviderError,
  ImageData,
  ImageGenInput,
  VisionInput,
} from "@/lib/providers/types";
