// Провайдер Google Gemini (текст+зрение и генерация изображений) через REST, без SDK.
// Картинки: gemini-3.1-flash-image (Nano Banana 2). Текст/зрение: gemini-flash-latest.
// Ключ — из env (GEMINI_API_KEY), в код не зашивается.

import { ok, err, type Result } from "@/lib/result";
import type {
  ImageProvider,
  VisionProvider,
  ProviderError,
  ImageData,
  ImageGenInput,
  VisionInput,
} from "@/lib/providers/types";

const BASE_URL = "https://generativelanguage.googleapis.com/v1beta";
const IMAGE_MODEL = "gemini-3.1-flash-image"; // Nano Banana 2
const TEXT_MODEL = "gemini-flash-latest";
const TIMEOUT_MS = 60_000;

type GeminiPart = { text?: string; inlineData?: { mimeType?: string; data?: string } };
type GeminiResponse = { candidates?: Array<{ content?: { parts?: GeminiPart[] } }> };

function inlinePart(img: ImageData): GeminiPart {
  return { inlineData: { mimeType: img.mimeType, data: img.base64 } };
}

async function call(
  apiKey: string,
  model: string,
  parts: GeminiPart[],
  imageOut: boolean,
): Promise<Result<GeminiResponse, ProviderError>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE_URL}/models/${model}:generateContent`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-goog-api-key": apiKey },
      body: JSON.stringify({
        contents: [{ parts }],
        ...(imageOut ? { generationConfig: { responseModalities: ["IMAGE"] } } : {}),
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      return err({ kind: "http", message: `Gemini HTTP ${res.status}`, status: res.status });
    }
    return ok((await res.json()) as GeminiResponse);
  } catch (e) {
    const aborted = e instanceof Error && e.name === "AbortError";
    return err({ kind: aborted ? "timeout" : "network", message: String(e) });
  } finally {
    clearTimeout(timer);
  }
}

function firstText(data: GeminiResponse): string | null {
  for (const p of data.candidates?.[0]?.content?.parts ?? []) {
    if (typeof p.text === "string" && p.text.length > 0) return p.text;
  }
  return null;
}

function firstImage(data: GeminiResponse): ImageData | null {
  for (const p of data.candidates?.[0]?.content?.parts ?? []) {
    const d = p.inlineData;
    if (d?.data && d.mimeType) return { mimeType: d.mimeType, base64: d.data };
  }
  return null;
}

export function createGeminiProvider(apiKey: string): ImageProvider & VisionProvider {
  return {
    id: "gemini",
    imageModel: IMAGE_MODEL,
    textModel: TEXT_MODEL,
    async generateText(prompt: string) {
      const r = await call(apiKey, TEXT_MODEL, [{ text: prompt }], false);
      if (!r.ok) return r;
      const text = firstText(r.value);
      return text === null ? err({ kind: "parse", message: "no text in response" }) : ok(text);
    },
    async analyze(input: VisionInput) {
      const parts: GeminiPart[] = [{ text: input.prompt }, ...(input.images ?? []).map(inlinePart)];
      const r = await call(apiKey, TEXT_MODEL, parts, false);
      if (!r.ok) return r;
      const text = firstText(r.value);
      return text === null ? err({ kind: "parse", message: "no text in response" }) : ok(text);
    },
    async generateImage(input: ImageGenInput) {
      const parts: GeminiPart[] = [
        { text: input.prompt },
        ...(input.referenceImages ?? []).map(inlinePart),
      ];
      const r = await call(apiKey, IMAGE_MODEL, parts, true);
      if (!r.ok) return r;
      const img = firstImage(r.value);
      return img === null ? err({ kind: "parse", message: "no image in response" }) : ok(img);
    },
  };
}
