// Анализ фото комнаты через vision-провайдера: что за объекты, что оставить/менять + уточнение стиля.
// Возвращает Result; при сбое ИИ — безопасный дефолт, чтобы flow не падал (guardrail).

import { getVisionProvider } from "@/lib/providers";
import { roomAnalysisPrompt } from "@/lib/prompts/registry";
import { analysis as analysisSchema, type Analysis, type Brief } from "@/contracts/project";
import { z } from "zod";

const rawSchema = z.object({
  summary: z.string(),
  objects: z.array(z.object({
    label: z.string(),
    // модель иногда возвращает легаси "suggest_change" — приводим к "change".
    action: z.preprocess((v) => (v === "suggest_change" ? "change" : v), z.enum(["keep", "change", "remove"])),
  })).max(12),
});

function extractJson(text: string): unknown {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < 0) return null;
  try {
    return JSON.parse(text.slice(start, end + 1));
  } catch {
    return null;
  }
}

const FALLBACK: Analysis = {
  summary: "Не удалось детально распознать фото — показываем общий план обновления.",
  objects: [
    { label: "Стены", action: "change" },
    { label: "Пол", action: "keep" },
    { label: "Освещение", action: "change" },
    { label: "Текстиль и декор", action: "change" },
  ],
};

export async function analyzeRoom(photoDataBase64: string, mimeType: string, brief: Partial<Brief>): Promise<Analysis> {
  const prompt = roomAnalysisPrompt.build({ roomType: brief.roomType, interventionLevel: brief.interventionLevel });

  const r = await getVisionProvider().analyze({
    prompt,
    images: [{ mimeType, base64: photoDataBase64 }],
    meta: { stepName: "analyze", promptId: roomAnalysisPrompt.id, promptVersion: roomAnalysisPrompt.version },
  });
  if (!r.ok) return FALLBACK;

  const parsed = rawSchema.safeParse(extractJson(r.value));
  if (!parsed.success) return FALLBACK;
  return analysisSchema.parse(parsed.data);
}
