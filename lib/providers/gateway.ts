// Gemini через шлюз Vercel AI Gateway (владелец 14.10: «делай через vercel»; ADR-0277). Тот же интерфейс, что у
// прямого Gemini (`lib/providers/gemini.ts`), но запрос — OpenAI-совместимый `chat/completions` шлюза: картинки
// приходят в `message.images` (data URL). Прямой ключ Gemini отключён Google 14.10. Ключ — `VERCEL_AI_GATEWAY_KEY`.

import { ok, err, type Result } from "@/lib/result";
import type { ImageProvider, VisionProvider, ProviderError, ImageData, ImageGenInput, VisionInput } from "@/lib/providers/types";

const URL_ = "https://ai-gateway.vercel.sh/v1/chat/completions";
const IMAGE_MODEL = "google/gemini-3.1-flash-image"; // Nano Banana 2, как у прямого провайдера
const TEXT_MODEL = "google/gemini-2.5-flash";
const TIMEOUT_MS = 90_000;

type Part = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
type GatewayMessage = { content?: string | null; images?: { type: string; image_url?: { url?: string } }[] };
type GatewayResponse = { choices?: { message?: GatewayMessage }[] };

const imagePart = (img: ImageData): Part => ({ type: "image_url", image_url: { url: `data:${img.mimeType};base64,${img.base64}` } });

async function call(key: string, model: string, parts: Part[], imageOut: boolean, extra: Record<string, unknown> = {},
  timeoutMs = TIMEOUT_MS): Promise<Result<GatewayResponse, ProviderError>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(URL_, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({ model, messages: [{ role: "user", content: parts }], ...(imageOut ? { modalities: ["text", "image"] } : {}), ...extra }),
      signal: controller.signal,
    });
    if (!res.ok) return err({ kind: "http", message: `Gateway HTTP ${res.status}`, status: res.status });
    return ok((await res.json()) as GatewayResponse);
  } catch (e) {
    const aborted = e instanceof Error && e.name === "AbortError";
    return err({ kind: aborted ? "timeout" : "network", message: String(e) });
  } finally {
    clearTimeout(timer);
  }
}

export function firstGatewayText(data: GatewayResponse): string | null {
  const t = data.choices?.[0]?.message?.content;
  return typeof t === "string" && t.length > 0 ? t : null;
}

export function firstGatewayImage(data: GatewayResponse): ImageData | null {
  for (const im of data.choices?.[0]?.message?.images ?? []) {
    const m = (im.image_url?.url ?? "").match(/^data:([^;]+);base64,(.+)$/);
    if (m) return { mimeType: m[1]!, base64: m[2]! };
  }
  return null;
}

export function createGatewayProvider(key: string): ImageProvider & VisionProvider {
  const text = async (parts: Part[]) => {
    const r = await call(key, TEXT_MODEL, parts, false);
    if (!r.ok) return r;
    const t = firstGatewayText(r.value);
    return t === null ? err({ kind: "parse" as const, message: "no text in response" }) : ok(t);
  };
  return {
    id: "gemini-gateway",
    imageModel: IMAGE_MODEL,
    textModel: TEXT_MODEL,
    generateText: (prompt: string) => text([{ type: "text", text: prompt }]),
    analyze: (input: VisionInput) => text([{ type: "text", text: input.prompt }, ...(input.images ?? []).map(imagePart)]),
    async generateImage(input: ImageGenInput) {
      const r = await call(key, IMAGE_MODEL, [{ type: "text", text: input.prompt }, ...(input.referenceImages ?? []).map(imagePart)], true);
      if (!r.ok) return r;
      const img = firstGatewayImage(r.value);
      return img === null ? err({ kind: "parse", message: "no image in response" }) : ok(img);
    },
  };
}

/**
 * ТЕКСТ ЛЮБОЙ МОДЕЛЬЮ ШЛЮЗА (T-20261023-12, владелец 23.10: прямой ключ OpenAI пуст и пополняться не будет — всё через шлюз).
 * Извлечение полей товара по ссылке (`lib/calc/link-parse-ai.ts`): модель `openai/…`, ответ строго JSON, температура 0, свой
 * короткий срок — страница расчёта ждёт ответа. Картинок нет: `analyze` шлёт только текст промпта.
 */
export function createGatewayTextProvider(key: string, model: string, opts: { json?: boolean; timeoutMs?: number } = {}): VisionProvider {
  const extra = { temperature: 0, ...(opts.json ? { response_format: { type: "json_object" } } : {}) };
  const text = async (prompt: string) => {
    const r = await call(key, model, [{ type: "text", text: prompt }], false, extra, opts.timeoutMs ?? TIMEOUT_MS);
    if (!r.ok) return r;
    const t = firstGatewayText(r.value);
    return t === null ? err({ kind: "parse" as const, message: "no text in response" }) : ok(t);
  };
  return { id: "gateway", textModel: model, generateText: (prompt: string) => text(prompt), analyze: (input: VisionInput) => text(input.prompt) };
}
