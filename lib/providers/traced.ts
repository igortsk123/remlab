// Инструментированные обёртки провайдеров — ЕДИНАЯ точка захвата лога: любой вызов LLM пишет шаг
// в активный прогон (модель, промпт, настройки, вход/выход, картинки, время, стоимость, ошибка).
// Нет активного прогона → чистый passthrough (тесты/скрипты). Так «меняется пайплайн → лог всё
// равно полный»: новый вызов модели логирует себя сам (ADR-0013).

import { randomUUID } from "node:crypto";
import { currentRun, type RunContext } from "@/lib/trace/context";
import { recordStep } from "@/lib/trace/recorder";
import { saveAsset } from "@/lib/trace/assets";
import { estimateImageCost, estimateTextCost } from "@/lib/pricing";
import type { ImageProvider, VisionProvider, ImageData, ImageGenInput, VisionInput } from "@/lib/providers/types";
import type { TracedMeta } from "@/lib/trace/types";

function toBuffer(base64: string): Buffer {
  return Buffer.from(base64, "base64");
}

async function saveImages(ctx: RunContext, imgs: ImageData[] | undefined, role: "input" | "intermediate", stepId: string): Promise<void> {
  for (const img of imgs ?? []) {
    await saveAsset(ctx, { role, mimeType: img.mimeType, bytes: toBuffer(img.base64), stepId });
  }
}

export function instrumentImageProvider(p: ImageProvider): ImageProvider {
  return {
    id: p.id,
    imageModel: p.imageModel,
    async generateImage(input: ImageGenInput) {
      const ctx = currentRun();
      if (!ctx) return p.generateImage(input);
      const stepId = randomUUID();
      await saveImages(ctx, input.referenceImages, "input", stepId);
      const t0 = Date.now();
      const r = await p.generateImage(input);
      const latencyMs = Date.now() - t0;
      if (r.ok) {
        await saveAsset(ctx, { role: "output", mimeType: r.value.mimeType, bytes: toBuffer(r.value.base64), stepId });
      }
      await recordStep(ctx, {
        id: stepId,
        stepName: input.meta?.stepName ?? "generate_image",
        kind: "image", provider: p.id, model: p.imageModel,
        promptId: input.meta?.promptId ?? null, promptVersion: input.meta?.promptVersion ?? null,
        promptText: input.prompt, params: input.meta?.params ?? null,
        inputText: null, outputText: null,
        status: r.ok ? "ok" : "error",
        errorKind: r.ok ? null : r.error.kind, errorMessage: r.ok ? null : r.error.message,
        latencyMs, costUsd: r.ok ? estimateImageCost(p.imageModel) : 0,
        startedAt: new Date(t0), finishedAt: new Date(),
      });
      return r;
    },
  };
}

export function instrumentVisionProvider(p: VisionProvider): VisionProvider {
  async function record(
    ctx: RunContext, stepName: string, prompt: string, images: ImageData[] | undefined,
    meta: TracedMeta | undefined, t0: number, r: { ok: boolean; value?: string; error?: { kind: string; message: string } },
    stepId: string,
  ): Promise<void> {
    const outText = r.ok ? (r.value ?? "") : "";
    await recordStep(ctx, {
      id: stepId, stepName, kind: "vision", provider: p.id, model: p.textModel,
      promptId: meta?.promptId ?? null, promptVersion: meta?.promptVersion ?? null,
      promptText: prompt, params: meta?.params ?? null,
      inputText: null, outputText: r.ok ? outText : null,
      status: r.ok ? "ok" : "error",
      errorKind: r.ok ? null : r.error?.kind ?? null, errorMessage: r.ok ? null : r.error?.message ?? null,
      latencyMs: Date.now() - t0, costUsd: r.ok ? estimateTextCost(p.textModel, prompt.length, outText.length) : 0,
      startedAt: new Date(t0), finishedAt: new Date(),
    });
  }
  return {
    id: p.id,
    textModel: p.textModel,
    async generateText(prompt: string, meta?: TracedMeta) {
      const ctx = currentRun();
      if (!ctx) return p.generateText(prompt, meta);
      const stepId = randomUUID();
      const t0 = Date.now();
      const r = await p.generateText(prompt, meta);
      await record(ctx, meta?.stepName ?? "generate_text", prompt, undefined, meta, t0, r.ok ? { ok: true, value: r.value } : { ok: false, error: r.error }, stepId);
      return r;
    },
    async analyze(input: VisionInput) {
      const ctx = currentRun();
      if (!ctx) return p.analyze(input);
      const stepId = randomUUID();
      await saveImages(ctx, input.images, "input", stepId);
      const t0 = Date.now();
      const r = await p.analyze(input);
      await record(ctx, input.meta?.stepName ?? "analyze", input.prompt, input.images, input.meta, t0, r.ok ? { ok: true, value: r.value } : { ok: false, error: r.error }, stepId);
      return r;
    },
  };
}
