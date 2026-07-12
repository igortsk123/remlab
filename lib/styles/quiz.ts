// Данные и подсчёт для игры «Узнай свой вкус» (раздел /styles).
// ⚠️ Картинки карточек — плейсхолдеры (палитра-градиент из swatch): реальные фото интерьеров
// добавим позже (content-later). Механика игры при этом полная.

export type StyleId = "scandi" | "japandi" | "loft" | "minimal" | "classic" | "provence";

export type StyleInfo = {
  id: StyleId;
  name: string;
  blurb: string;
  // Палитра-плейсхолдер (2 цвета для градиента карточки), пока нет реальных фото.
  swatch: [string, string];
};

// Порядок ключей задаёт тай-брейк при равенстве лайков.
export const STYLES: Record<StyleId, StyleInfo> = {
  scandi: {
    id: "scandi",
    name: "Скандинавский",
    blurb: "Светлые стены, много воздуха, дерево и простые формы. Уютно и недорого.",
    swatch: ["#eef1f4", "#c7d2da"],
  },
  japandi: {
    id: "japandi",
    name: "Джапанди",
    blurb: "Тёплые спокойные тона, натуральные материалы, ничего лишнего.",
    swatch: ["#e9e2d6", "#b9a893"],
  },
  loft: {
    id: "loft",
    name: "Лофт",
    blurb: "Кирпич, бетон, металл и открытые конструкции. Брутально и стильно.",
    swatch: ["#cfc7bf", "#7d6f63"],
  },
  minimal: {
    id: "minimal",
    name: "Минимализм",
    blurb: "Чистые линии, скрытое хранение, ни одной лишней вещи.",
    swatch: ["#f2f0ec", "#c9c4bc"],
  },
  classic: {
    id: "classic",
    name: "Классика",
    blurb: "Молдинги, симметрия, благородные цвета и мягкий тёплый свет.",
    swatch: ["#e7ddcb", "#b79b74"],
  },
  provence: {
    id: "provence",
    name: "Прованс",
    blurb: "Пастель, состаренное дерево, цветочные мотивы и лёгкость.",
    swatch: ["#efe7dd", "#c9b6a0"],
  },
};

export const STYLE_LIST: StyleInfo[] = Object.values(STYLES);

export type QuizCard = { id: string; style: StyleId; caption: string };

// Карточки перемешаны по стилям, чтобы результат зависел от выбора, а не от порядка.
export const QUIZ_CARDS: QuizCard[] = [
  { id: "q1", style: "scandi", caption: "Белые стены, светлый дуб, зелень у окна" },
  { id: "q2", style: "loft", caption: "Кирпичная стена, чёрный металл, лампы Эдисона" },
  { id: "q3", style: "japandi", caption: "Тёплый беж, низкая мебель, натуральный лён" },
  { id: "q4", style: "minimal", caption: "Гладкие фасады без ручек, ничего лишнего" },
  { id: "q5", style: "classic", caption: "Молдинги на стенах, симметрия, тёплый свет" },
  { id: "q6", style: "provence", caption: "Пастельные стены, состаренное дерево, цветы" },
  { id: "q7", style: "scandi", caption: "Плед, свечи, простые полки из дерева" },
  { id: "q8", style: "japandi", caption: "Бумажный светильник, керамика, спокойные тона" },
  { id: "q9", style: "loft", caption: "Открытые трубы, бетонный пол, кожаный диван" },
];

// Считаем доминирующий стиль по лайкнутым карточкам. Нет лайков → null (покажем нейтральный экран).
export function tallyStyle(likedStyles: StyleId[]): StyleId | null {
  if (likedStyles.length === 0) return null;
  const counts = new Map<StyleId, number>();
  for (const s of likedStyles) counts.set(s, (counts.get(s) ?? 0) + 1);
  let best: StyleId | null = null;
  let bestN = 0;
  for (const id of Object.keys(STYLES) as StyleId[]) {
    const n = counts.get(id) ?? 0;
    if (n > bestN) {
      bestN = n;
      best = id;
    }
  }
  return best;
}
