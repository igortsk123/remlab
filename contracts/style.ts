// Стили (style cards) и извлечённый профиль стиля (CJM §6).

import { z } from "zod";

export const styleId = z.enum([
  "scandinavian", "japandi", "modern_minimalism", "modern_classic", "loft",
  "mid_century", "contemporary", "eco", "soft_minimal", "rental_friendly",
]);
export type StyleId = z.infer<typeof styleId>;

export const styleProfile = z.object({
  selectedStyleIds: z.array(styleId).default([]),
  likedStyleCards: z.array(styleId).default([]),
  dislikedStyleCards: z.array(styleId).default([]),
  palette: z.string().default("warm_neutral"),
  contrastLevel: z.enum(["low", "medium", "high"]).default("low"),
  materialPreferences: z.array(z.string()).default(["wood", "textile", "matte_surfaces"]),
  decorLevel: z.enum(["low", "medium", "high"]).default("medium"),
  budgetFeeling: z.enum(["low", "middle", "high"]).default("middle"),
});
export type StyleProfile = z.infer<typeof styleProfile>;

// Витрина карточек стиля (название + акцент + объяснение) — статичный каталог онбординга.
export type StyleCard = { id: StyleId; name: string; accent: string; note: string };

export const STYLE_CARDS: StyleCard[] = [
  { id: "scandinavian", name: "Скандинавский", accent: "светлая база, дерево, простые формы", note: "Лёгкий интерьер без визуального шума." },
  { id: "japandi", name: "Джапанди", accent: "тёплый минимализм, натуральные материалы", note: "Спокойствие и природная палитра." },
  { id: "modern_minimalism", name: "Современный минимализм", accent: "чистые линии, много воздуха", note: "Ничего лишнего, функциональность." },
  { id: "modern_classic", name: "Современная классика", accent: "мягкие формы, благородные тона", note: "Уют с ноткой элегантности." },
  { id: "loft", name: "Лофт", accent: "кирпич, металл, открытые фактуры", note: "Брутально и свободно." },
  { id: "mid_century", name: "Mid-century", accent: "дерево, тёплые цвета, ретро-мебель", note: "Тёплая ретро-эстетика 60-х." },
  { id: "eco", name: "Эко-стиль", accent: "растения, натуральные текстуры", note: "Природа в интерьере." },
  { id: "soft_minimal", name: "Soft minimal", accent: "мягкие бежевые тона, округлости", note: "Нежный и спокойный минимализм." },
];
