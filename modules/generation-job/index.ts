// Оркестратор превью: анализ фото → генерация картинки → идеи → каталог → бюджет, запись в repo.
// Весь путь обёрнут в прогон трейса (runWithTrace, ADR-0013): каждый вызов LLM логируется, у прогона
// есть «номер генерации» (seq). Долгий шаг (генерация ~10–30с). Пока синхронно; вынос в фон — позже.

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

export async function runPreview(projectId: string): Promise<Project | null> {
  const project = await repo().get(projectId);
  if (!project) return null;

  const firstPhoto: Photo | undefined = project.photos[0];
  const style: StyleProfile = project.styleProfile ?? styleProfileSchema.parse({});
  const decoded = firstPhoto ? dataUrlToBase64(firstPhoto.dataUrl) : null;
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
      // Сжать+уменьшить фото ПЕРЕД LLM (экономия токенов); то, что реально ушло, и станет input-ассетом.
      const llmPhoto = decoded ? await compressForLLM({ mimeType: decoded.mimeType, base64: decoded.base64 }) : null;

      const analysis: Analysis = llmPhoto
        ? await analyzeRoom(llmPhoto.base64, llmPhoto.mimeType, project.brief)
        : { summary: "Фото не приложено — общий план обновления.", objects: [] };

      let previewImage: Photo | undefined;
      if (llmPhoto) {
        const gen = await generatePreview(llmPhoto, style, project.brief);
        if (gen.ok) {
          previewImage = {
            id: `${projectId}-preview`,
            mimeType: gen.value.mimeType,
            dataUrl: `data:${gen.value.mimeType};base64,${gen.value.base64}`,
          };
        }
      }

      const ideas = await generateIdeas(analysis, project.brief);
      return { analysis, previewImage, ideas };
    },
  );

  return repo().update(projectId, {
    status: "preview_ready",
    analysis: result.analysis,
    previewImage: result.previewImage,
    ideas: result.ideas,
    items: buildCatalog(),
    budget: estimateBudget(project.brief),
    generationSeq: ctx.seq,
    traceRunId: ctx.runId,
  });
}
