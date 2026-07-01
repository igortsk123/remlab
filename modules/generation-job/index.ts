// Оркестратор превью: анализ фото → генерация картинки → идеи → каталог → бюджет, запись в repo.
// Долгий шаг (генерация ~10–30с). Пока синхронно; вынос в фоновую очередь (Inngest) — позже.

import { repo } from "@/modules/store/repository";
import { analyzeRoom } from "@/modules/room-analysis";
import { generatePreview } from "@/modules/visual-generation";
import { generateIdeas, buildCatalog, estimateBudget } from "@/modules/ideas";
import { styleProfile as styleProfileSchema, type StyleProfile } from "@/contracts/style";
import type { Project, Photo } from "@/contracts/project";

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

  const analysis = decoded
    ? await analyzeRoom(decoded.base64, decoded.mimeType, project.brief)
    : { summary: "Фото не приложено — общий план обновления.", objects: [] };

  let previewImage: Photo | undefined;
  if (decoded) {
    const gen = await generatePreview({ mimeType: decoded.mimeType, base64: decoded.base64 }, style, project.brief);
    if (gen.ok) {
      previewImage = {
        id: `${projectId}-preview`,
        mimeType: gen.value.mimeType,
        dataUrl: `data:${gen.value.mimeType};base64,${gen.value.base64}`,
      };
    }
  }

  const ideas = await generateIdeas(analysis, project.brief);

  return repo().update(projectId, {
    status: "preview_ready",
    analysis,
    previewImage,
    ideas,
    items: buildCatalog(),
    budget: estimateBudget(project.brief),
  });
}
