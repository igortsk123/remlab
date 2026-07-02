// Оркестратор превью — ДВА этапа (интерактивный флоу, план interactive-object-selection):
//  1) runAnalyze — разбор фото (что за объекты) ПЕРЕД выбором пользователя. Не входит в «генерацию»
//     (нет runWithTrace → passthrough, без номера): это подготовка, пользователь ещё не решил.
//  2) runGenerate — по кнопке «Сгенерировать»: перерисовка комнаты ПО ВЫБОРУ пользователя
//     (objectChoices + wish + стиль) + идеи. Обёрнут в runWithTrace → это и есть «генерация» (seq).

import { repo } from "@/modules/store/repository";
import { analyzeRoom } from "@/modules/room-analysis";
import { generatePreview } from "@/modules/visual-generation";
import { generateIdeas, buildCatalog, estimateBudget } from "@/modules/ideas";
import { runWithTrace } from "@/lib/trace/recorder";
import { getPipeline } from "@/lib/pipelines/registry";
import { compressForLLM } from "@/lib/images/compress";
import { styleProfile as styleProfileSchema, type StyleProfile } from "@/contracts/style";
import type { Project, Photo, Analysis } from "@/contracts/project";

function dataUrlToBase64(dataUrl: string): { mimeType: string; base64: string } | null {
  const m = /^data:([^;]+);base64,(.+)$/s.exec(dataUrl);
  if (!m || !m[1] || !m[2]) return null;
  return { mimeType: m[1], base64: m[2] };
}

const NO_PHOTO_ANALYSIS: Analysis = {
  summary: "Фото не приложено — предложим общий план обновления.",
  objects: [
    { label: "Стены", action: "change" },
    { label: "Пол", action: "keep" },
    { label: "Освещение", action: "change" },
    { label: "Текстиль и декор", action: "change" },
  ],
};

// Этап 1: разобрать фото на объекты. Идемпотентно — если уже разобрано, возвращаем сохранённое
// (не жжём вызов модели на каждом заходе на экран выбора).
export async function runAnalyze(projectId: string): Promise<Analysis | null> {
  const project = await repo().get(projectId);
  if (!project) return null;
  if (project.analysis) return project.analysis;

  const decoded = project.photos[0] ? dataUrlToBase64(project.photos[0].dataUrl) : null;
  const analysis: Analysis = decoded
    ? await (async () => {
        const llmPhoto = await compressForLLM({ mimeType: decoded.mimeType, base64: decoded.base64 });
        return analyzeRoom(llmPhoto.base64, llmPhoto.mimeType, project.brief);
      })()
    : NO_PHOTO_ANALYSIS;

  await repo().update(projectId, {
    analysis,
    objectChoices: analysis.objects, // дефолт выбора = предложение модели; пользователь переопределит
    status: "analyzed",
  });
  return analysis;
}

// Этап 2: генерация по ВЫБОРУ пользователя. Это «генерация» с номером (runWithTrace).
export async function runGenerate(projectId: string): Promise<Project | null> {
  const project = await repo().get(projectId);
  if (!project) return null;

  const style: StyleProfile = project.styleProfile ?? styleProfileSchema.parse({});
  const decoded = project.photos[0] ? dataUrlToBase64(project.photos[0].dataUrl) : null;
  const analysisForIdeas: Analysis = project.analysis ?? NO_PHOTO_ANALYSIS;
  const pipeline = getPipeline();

  const { result, ctx } = await runWithTrace(
    {
      pipelineId: pipeline.id,
      pipelineVersion: pipeline.version,
      projectId,
      sessionId: project.sessionId,
      meta: { title: project.title, roomType: project.brief.roomType ?? null },
    },
    async () => {
      // Сжать+уменьшить фото ПЕРЕД LLM; то, что реально ушло, и станет input-ассетом.
      const llmPhoto = decoded ? await compressForLLM({ mimeType: decoded.mimeType, base64: decoded.base64 }) : null;

      let previewImage: Photo | undefined;
      if (llmPhoto) {
        const gen = await generatePreview(llmPhoto, style, project.brief, project.objectChoices, project.wish);
        if (gen.ok) {
          previewImage = {
            id: `${projectId}-preview`,
            mimeType: gen.value.mimeType,
            dataUrl: `data:${gen.value.mimeType};base64,${gen.value.base64}`,
          };
        }
      }

      const ideas = await generateIdeas(analysisForIdeas, project.brief);
      return { previewImage, ideas };
    },
  );

  return repo().update(projectId, {
    status: "preview_ready",
    previewImage: result.previewImage,
    ideas: result.ideas,
    items: buildCatalog(),
    budget: estimateBudget(project.brief),
    generationSeq: ctx.seq,
    traceRunId: ctx.runId,
  });
}
