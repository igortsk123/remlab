// Двуязычие конфигуратора. Данные (роли, названия материалов) — по-русски и по-английски прямо
// в каталоге; здесь только слова интерфейса. Язык — в адресе (?lang=en), по умолчанию русский:
// владелец проверяет по-русски, покупатель в UK — по-английски.

export type Lang = "ru" | "en";

export const UI = {
  ru: {
    modes: { walk: "Бродилка", top: "Сверху", photo: "Фото", plan: "План" },
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
    photoBtn: "Кадр с вашей расстановкой",
    photoNice: "Красивое фото · 2–4 мин",
    photoWait: "Считаем кадр, обычно 20–30 секунд",
    photoHint: "Снимок комнаты с выбранной мебелью — его можно сохранить или отправить",
    walkHint: "Идите кнопками внизу или клавишами · тяните мышью, чтобы осмотреться · нажмите на предмет, чтобы заменить или передвинуть",
    walkHintMobile: "Коснитесь пола — идти · тяните — осмотреться · предмет — заменить",
    loading: "Загружаем квартиру…",
    loadingTitle: "Исследуйте квартиру",
    loadingHint: "Можно ходить внутри, вращать вид, менять и двигать мебель",
    loadingStages: ["Загружаем планировку…", "Расставляем мебель…", "Почти готово…"],
    premium: "премиум",
    perRoom: "в этой комнате",
    noWebgl: "Браузер не поддерживает 3D. Остаются режимы «Фото» и «План».",
    photoFailed: "Кадр не получился. Попробуйте ещё раз",
    devPhoto: "Фото собирается только на сайте (на этой копии сервис кадров не подключён)",
    photoQueue: (n: number, eta: number) => `В очереди: ${n}${eta ? ` · примерно ${eta} с` : ""}`,
    photoEta: (eta: number) => `Осталось примерно ${eta} с`,
  },
  en: {
    modes: { walk: "Walk", top: "Top view", photo: "Photo", plan: "Plan" },
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
    photoBtn: "Picture of your layout",
    photoNice: "Beautiful photo · 2–4 min",
    photoWait: "Rendering, usually 20–30 seconds",
    photoHint: "A picture of the room with your furniture — save it or share it",
    walkHint: "Walk with the buttons below or the arrow keys · drag to look around · click an item to change or move it",
    walkHintMobile: "Tap the floor to walk · drag to look · tap an item to change it",
    loading: "Loading your apartment…",
    loadingTitle: "Explore the apartment",
    loadingHint: "Walk inside, turn the view, swap and move the furniture",
    loadingStages: ["Loading the layout…", "Placing the furniture…", "Almost there…"],
    premium: "premium",
    perRoom: "in this room",
    noWebgl: "This browser has no 3D support. Photo and Plan modes still work.",
    photoFailed: "The render failed. Please try again",
    devPhoto: "Rendering works on the live site only",
    photoQueue: (n: number, eta: number) => `In queue: ${n}${eta ? ` · about ${eta} s` : ""}`,
    photoEta: (eta: number) => `About ${eta} s left`,
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

/** Сумма в валюте застройщика (каталог 3D знает свою валюту, b2b-06). */
export function formatMoney(value: number, currency: "GBP" | "RUB", lang: Lang): string {
  return new Intl.NumberFormat(lang === "en" ? "en-GB" : "ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}
