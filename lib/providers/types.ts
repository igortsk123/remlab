// Контракты провайдеров ИИ. Реализация (Gemini/OpenAI/…) прячется за этими интерфейсами,
// чтобы менять провайдера под задачу без правок вызывающего кода (см. decisions: провайдеры сменные).

import type { Result } from "@/lib/result";
import type { TracedMeta } from "@/lib/trace/types";

export type ProviderErrorKind = "config" | "network" | "http" | "parse" | "timeout";

export type ProviderError = {
  kind: ProviderErrorKind;
  message: string;
  status?: number;
};

export type ImageData = { mimeType: string; base64: string };

export type ImageGenInput = {
  prompt: string;
  /** Эталонные изображения (фото комнаты и т.п.) — для editing/consistency. */
  referenceImages?: ImageData[];
  /** Обогащение трейса (реальный провайдер игнорирует; читает инструментированная обёртка). */
  meta?: TracedMeta;
};

export interface ImageProvider {
  readonly id: string;
  /** Идентификатор модели генерации картинок (для лога «какая LLM»). */
  readonly imageModel: string;
  generateImage(input: ImageGenInput): Promise<Result<ImageData, ProviderError>>;
}

export type VisionInput = {
  prompt: string;
  images?: ImageData[];
  meta?: TracedMeta;
};

export interface VisionProvider {
  readonly id: string;
  /** Идентификатор текстовой/vision-модели (для лога «какая LLM»). */
  readonly textModel: string;
  generateText(prompt: string, meta?: TracedMeta): Promise<Result<string, ProviderError>>;
  analyze(input: VisionInput): Promise<Result<string, ProviderError>>;
}
