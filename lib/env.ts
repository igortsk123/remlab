// Валидация окружения через Zod (code-standards: любой внешний вход — Zod-DTO, включая env).
// Ключи опциональны на уровне схемы; наличие проверяет фабрика провайдера при использовании.

import { z } from "zod";

const providerEnvSchema = z.object({
  GEMINI_API_KEY: z.string().min(1).optional(),
  OPENAI_API_KEY: z.string().min(1).optional(),
  VERCEL_AI_GATEWAY_KEY: z.string().min(1).optional(),
  /** gateway — Gemini через шлюз Vercel (по умолчанию с 14.10, ADR-0277); gemini — прямой ключ Google. */
  AI_PROVIDER: z.enum(["gateway", "gemini"]).optional(),
});

export type ProviderEnv = z.infer<typeof providerEnvSchema>;

let cached: ProviderEnv | null = null;

export function providerEnv(): ProviderEnv {
  if (cached === null) {
    cached = providerEnvSchema.parse(process.env);
  }
  return cached;
}
