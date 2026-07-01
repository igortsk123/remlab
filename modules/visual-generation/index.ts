// Генерация визуального превью: берём ФОТО пользователя как эталон и перерисовываем ту же комнату
// в выбранном стиле (решение владельца: restyle своей комнаты, не картинка-вдохновение).

import { getImageProvider } from "@/lib/providers";
import type { Result } from "@/lib/result";
import type { ProviderError, ImageData } from "@/lib/providers";
import type { StyleProfile } from "@/contracts/style";
import type { Brief } from "@/contracts/project";
import { STYLE_CARDS, type StyleId } from "@/contracts/style";

function styleNames(ids: StyleId[]): string {
  const names = ids.map((id) => STYLE_CARDS.find((c) => c.id === id)?.name).filter(Boolean);
  return names.length ? names.join(", ") : "тёплый скандинавский минимализм";
}

export function buildPrompt(style: StyleProfile, brief: Partial<Brief>): string {
  const level = brief.interventionLevel === "light_cosmetic"
    ? "лёгкий косметический ремонт (стены, пол, свет, мебель)"
    : brief.interventionLevel === "budget_update"
      ? "недорогое обновление (акцентная стена, часть мебели, свет, текстиль)"
      : "освежение без ремонта (текстиль, свет, декор, растения)";
  return [
    "Перерисуй ЭТУ комнату с эталонного фото, СОХРАНИВ её геометрию: расположение стен, окон, дверей,",
    "планировку и перспективу. Не выдумывай новую комнату — обнови существующую.",
    `Стиль: ${styleNames(style.selectedStyleIds.length ? style.selectedStyleIds : style.likedStyleCards)}.`,
    `Палитра: ${style.palette}, контраст ${style.contrastLevel}. Уровень изменений: ${level}.`,
    "Фотореалистично, естественный дневной свет, аккуратная композиция интерьерного фото.",
  ].join(" ");
}

export async function generatePreview(
  photo: ImageData,
  style: StyleProfile,
  brief: Partial<Brief>,
): Promise<Result<ImageData, ProviderError>> {
  return getImageProvider().generateImage({
    prompt: buildPrompt(style, brief),
    referenceImages: [photo],
  });
}
