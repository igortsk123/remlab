// Двуязычие конфигуратора. Данные (роли, названия материалов) — по-русски и по-английски прямо
// в каталоге; здесь только слова интерфейса. Язык — в адресе (?lang=en), по умолчанию русский:
// владелец проверяет по-русски, покупатель в UK — по-английски.

export type Lang = "ru" | "en";

export const UI = {
  ru: {
    modes: { d3: "3D", photo: "Фото", plan: "План" },
    rooms: "Комнаты",
    categories: "Что меняем",
    options: "Варианты",
    total: "Итого",
    base: "Квартира",
    upgrades: "Апгрейды",
    included: "входит в цену",
    save: "Сохранить подбор",
    saved: "Ссылка на подбор скопирована",
    saving: "Сохраняем…",
    photoBtn: "Сделать фото комнаты",
    photoWait: "Считаем кадр, обычно 20–30 секунд",
    photoHint: "Фото собирается тем же конвейером, что и на демо-планировщике",
    liteOn: "Включить 3D Lite",
    liteOff: "Вернуться к фото",
    walkHint: "WASD или стрелки — идти, тянуть мышью — осмотреться, клик по предмету — заменить",
    walkHintMobile: "Коснитесь пола — подойти, тяните пальцем — осмотреться, коснитесь предмета — заменить",
    loading: "Загружаем квартиру…",
    premium: "премиум",
    perRoom: "в этой комнате",
    noWebgl: "Браузер не поддерживает 3D. Остаются режимы «Фото» и «План».",
    photoOnlyLiving: "Фото пока делаем для гостиной — там настроены ракурсы",
    photoFailed: "Кадр не получился. Попробуйте ещё раз",
    devPhoto: "Фото собирается только на сайте (на этой копии сервис кадров не подключён)",
  },
  en: {
    modes: { d3: "3D", photo: "Photo", plan: "Plan" },
    rooms: "Rooms",
    categories: "Choose",
    options: "Options",
    total: "Total",
    base: "Apartment",
    upgrades: "Upgrades",
    included: "included",
    save: "Save my spec",
    saved: "Link to your spec copied",
    saving: "Saving…",
    photoBtn: "Render this room",
    photoWait: "Rendering, usually 20–30 seconds",
    photoHint: "Rendered by the same pipeline as the demo planner",
    liteOn: "Switch on 3D Lite",
    liteOff: "Back to photo",
    walkHint: "WASD or arrows to walk, drag to look around, click an item to change it",
    walkHintMobile: "Tap the floor to walk, drag to look around, tap an item to change it",
    loading: "Loading your apartment…",
    premium: "premium",
    perRoom: "in this room",
    noWebgl: "This browser has no 3D support. Photo and Plan modes still work.",
    photoOnlyLiving: "Photo is set up for the living room for now",
    photoFailed: "The render failed. Please try again",
    devPhoto: "Rendering works on the live site only",
  },
} as const;

export function t(lang: Lang): (typeof UI)["ru"] {
  return lang === "en" ? (UI.en as unknown as (typeof UI)["ru"]) : UI.ru;
}

const CAT_TITLES: Record<string, { ru: string; en: string }> = {
  flooring: { ru: "Пол", en: "Flooring" },
  kitchen: { ru: "Кухня", en: "Kitchen" },
  appliances: { ru: "Техника", en: "Appliances" },
  bathroom: { ru: "Санузел", en: "Bathroom" },
  walls: { ru: "Стены", en: "Walls" },
  furniture: { ru: "Мебель", en: "Furniture" },
  storage: { ru: "Хранение", en: "Storage" },
  lighting: { ru: "Свет", en: "Lighting" },
};

export function categoryTitle(category: string, lang: Lang): string {
  const c = CAT_TITLES[category];
  if (!c) return category;
  return lang === "en" ? c.en : c.ru;
}

export function formatGbp(value: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === "en" ? "en-GB" : "ru-RU", {
    style: "currency",
    currency: "GBP",
    maximumFractionDigits: 0,
  }).format(value);
}
