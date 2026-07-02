// Реестр промптов (ADR-0013). Один источник правды для текстов промптов: версионируемые,
// чтобы «под каждый сценарий свой промпт» и чистое сравнение тестов. Меняешь текст → бампни version.
// Трейс пишет promptId+version+рендер, поэтому по номеру генерации видно, КАКОЙ промпт был.

import { STYLE_CARDS, type StyleId, type StyleProfile } from "@/contracts/style";
import type { Brief } from "@/contracts/project";
import type { Analysis } from "@/contracts/project";

export type PromptRef = { id: string; version: string };
export function promptRef(p: { id: string; version: string }): PromptRef {
  return { id: p.id, version: p.version };
}

function styleNames(ids: StyleId[]): string {
  const names = ids.map((id) => STYLE_CARDS.find((c) => c.id === id)?.name).filter(Boolean);
  return names.length ? names.join(", ") : "тёплый скандинавский минимализм";
}

// Анализ фото комнаты (vision).
export const roomAnalysisPrompt = {
  id: "room-analysis",
  version: "v1",
  build(v: { roomType?: string; interventionLevel?: string }): string {
    return [
      "Ты — ассистент по обновлению интерьера. Проанализируй фото комнаты.",
      `Тип комнаты: ${v.roomType ?? "жилая"}. Уровень вмешательства: ${v.interventionLevel ?? "refresh"}.`,
      "Верни СТРОГО JSON без пояснений в формате:",
      '{"summary":"1-2 предложения о комнате на русском","objects":[{"label":"Диван","action":"keep"},{"label":"Шторы","action":"suggest_change"}]}',
      "action = keep (оставить) или suggest_change (предложить изменить). 4–7 объектов.",
    ].join("\n");
  },
};

// Перерисовка (restyle) комнаты в стиле — генерация картинки.
export const restylePrompt = {
  id: "restyle",
  version: "v1",
  build(v: { style: StyleProfile; brief: Partial<Brief> }): string {
    const level = v.brief.interventionLevel === "light_cosmetic"
      ? "лёгкий косметический ремонт (стены, пол, свет, мебель)"
      : v.brief.interventionLevel === "budget_update"
        ? "недорогое обновление (акцентная стена, часть мебели, свет, текстиль)"
        : "освежение без ремонта (текстиль, свет, декор, растения)";
    const styles = v.style.selectedStyleIds.length ? v.style.selectedStyleIds : v.style.likedStyleCards;
    return [
      "Перерисуй ЭТУ комнату с эталонного фото, СОХРАНИВ её геометрию: расположение стен, окон, дверей,",
      "планировку и перспективу. Не выдумывай новую комнату — обнови существующую.",
      `Стиль: ${styleNames(styles)}.`,
      `Палитра: ${v.style.palette}, контраст ${v.style.contrastLevel}. Уровень изменений: ${level}.`,
      "Фотореалистично, естественный дневной свет, аккуратная композиция интерьерного фото.",
    ].join(" ");
  },
};

// Идеи обновления (текст).
export const ideasPrompt = {
  id: "ideas",
  version: "v1",
  build(v: { analysis: Analysis; brief: Partial<Brief> }): string {
    return [
      "Дай 4–5 конкретных идей, как обновить комнату, недорого и с максимальным визуальным эффектом.",
      `Комната: ${v.brief.roomType ?? "жилая"}. Что заметил ИИ: ${v.analysis.summary}`,
      'Верни СТРОГО JSON: {"ideas":[{"title":"...","detail":"одно предложение"}]}',
    ].join("\n");
  },
};
