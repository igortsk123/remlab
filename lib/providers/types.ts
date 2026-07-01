// Контракты провайдеров ИИ. Реализация (Gemini/OpenAI/…) прячется за этими интерфейсами,
// чтобы менять провайдера под задачу без правок вызывающего кода (см. decisions: провайдеры сменные).

import type { Result } from "@/lib/result";

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
};

export interface ImageProvider {
  readonly id: string;
  generateImage(input: ImageGenInput): Promise<Result<ImageData, ProviderError>>;
}

export type VisionInput = {
  prompt: string;
  images?: ImageData[];
};

export interface VisionProvider {
  readonly id: string;
  generateText(prompt: string): Promise<Result<string, ProviderError>>;
  analyze(input: VisionInput): Promise<Result<string, ProviderError>>;
}
