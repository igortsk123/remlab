// Генерация визуального превью: берём ФОТО пользователя как эталон и перерисовываем ту же комнату
// в выбранном стиле (решение владельца: restyle своей комнаты, не картинка-вдохновение).

import { getImageProvider } from "@/lib/providers";
import { restylePrompt } from "@/lib/prompts/registry";
import type { Result } from "@/lib/result";
import type { ProviderError, ImageData } from "@/lib/providers";
import type { StyleProfile } from "@/contracts/style";
import type { Brief, DetectedObject } from "@/contracts/project";

export async function generatePreview(
  photo: ImageData,
  style: StyleProfile,
  brief: Partial<Brief>,
  choices?: DetectedObject[],
  wish?: string,
): Promise<Result<ImageData, ProviderError>> {
  return getImageProvider().generateImage({
    prompt: restylePrompt.build({ style, brief, choices, wish }),
    referenceImages: [photo],
    meta: { stepName: "restyle", promptId: restylePrompt.id, promptVersion: restylePrompt.version },
  });
}
