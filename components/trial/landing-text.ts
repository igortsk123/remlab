// Тексты лендинга `/try` на двух языках (план agent-trial-08, П). Английский — макет v3-en-final, согласованный владельцем
// (TG 420), слово в слово; русский — перевод того же смысла. Цены примера — в фунтах на обоих языках: каталог пробы — UK.

import type { TrialLang } from "@/lib/trial/i18n";

type Pair = readonly [string, string];

const en = {
  hero: {
    eyebrow: "For estate agents and developers · Beta",
    h1: "Turn a floor plan into a furnished 3D tour in minutes",
    lead: "Upload a PDF or photo and get a tour link for buyers.",
    stats: [["Minutes", "to a 3D link"], ["Free", "during the beta"], ["No sign-up", "no app, no card"]] as Pair[],
    beta: "For now we furnish living rooms and bedrooms.",
    stripLabel: "One flat, from floor plan to AI image",
    strip: [
      { alt: "Floor plan of a 2-bed flat", cap: "Floor plan" },
      { alt: "The same flat as a grey 3D model", cap: "3D", t: "first" },
      { alt: "Its living room, furnished in 3D", cap: "Furniture", t: "added next", tag: "Walk round" },
      { alt: "AI image of the same living room", cap: "AI image", t: "added later" },
    ] as { alt: string; cap: string; t?: string; tag?: string }[],
    aiBadge: "AI visualisation, not a photo",
  },
  how: {
    h2: "How it works",
    steps: [["Upload the plan", "PDF or photo."], ["We build the 3D", "We flag sizes we can't confirm."],
      ["We furnish it", "Living room and bedrooms."], ["Send the link", "It opens in the browser."]] as Pair[],
  },
  cmp: {
    h2: "Minutes, not days", old: "Made-to-order 3D",
    rows: [["First result", "Often quoted as 24 to 48 hours", "Minutes"], ["To get started", "Quote, call, brief", "Upload a plan"],
      ["Furniture", "Chosen by the studio", "With prices"], ["Buyers get", "Still images or an app", "A browser link"]] as (readonly [string, string, string])[],
    foot: "Studio timings: from their own websites, November 2026.",
  },
  example: {
    h2: "What you get for each listing", flat: "2-bed · 77.2 m²", alt: "Living room, AI image",
    room: "Living room · 14.4 m²", sum: "12 items · guide total £2,091",
    items: [["Three-seat sofa, grey fabric", "sofa"], ["Coffee table, walnut effect", "coffee table"], ["Floor lamp, white", "lighting"],
      ["TV unit, oak and grey", "storage"]] as Pair[],
    gets: [
      { title: "Two links", p: [["Yours:", "see it as your client will."], ["For buyers:", "starts with a style quiz."]] as Pair[] },
      { title: "Easy to share", p: [["", "Into the listing, an email or WhatsApp."]] as Pair[] },
      { title: "AI images are labelled", p: [["", "Even when downloaded."]] as Pair[] },
      { title: "Furniture with prices", p: [["", "The same pieces as in the tour."]] as Pair[] },
    ],
  },
  waiting: {
    h2: "While we finish the tour", lead: "The 3D opens first, furniture and the image follow.",
    steps: [["Plan received", "floorplan-flat-215.pdf"], ["Rooms and sizes read", "7 rooms · 77.2 m²"], ["3D ready", ""],
      ["Furnishing living room and bedrooms", ""], ["AI image of the living room", ""]] as Pair[],
    note: "Times vary by floor plan", ready: "Your links are ready", open: "Open your link", buyer: "Buyer link",
    phTitle: "AI image loading…", phText: "it'll appear here",
    mailTitle: "Rather not wait?", mailText: "We'll email you the links.", mailPh: "you@agency.co.uk", mailLabel: "Email", mailBtn: "Email me",
  },
  faq: {
    h2: "Questions agents ask",
    items: [
      ["How accurate are the sizes?", "From the plan and your measurements. Sizes we're unsure of are flagged. Not for measuring."],
      ["What furniture is shown?", "From our catalogue, priced in pounds. Styles can be switched."],
      ["Which rooms are furnished?", "Living rooms and bedrooms. Up to two floors."],
      // срок — владелец 10.11 (TG 744): план и тур живут 30 дней, в этот срок план можно поправить (`lib/trial/config.ts:trialFileHours`)
      ["What happens to my floor plan?", "We keep your plan and tour for 30 days, so you can correct the plan. We share neither."],
    ] as Pair[],
  },
  final: { h2: "Try it on your next listing", upload: "Upload a floor plan", example: "See an example" },
};

export type LandingText = typeof en;

const ru: LandingText = {
  hero: {
    eyebrow: "Для агентов и застройщиков · Бета",
    // «3D‑тур» — неразрывный дефис (U+2011): на телефоне строка не рвётся на «3D-» / «тур»
    h1: "План квартиры — в 3D‑тур с мебелью за несколько минут",
    lead: "Загрузите PDF или фото плана и получите ссылку на тур для покупателей.",
    // «Без регистрации» не влезает в треть ширины телефона — та же мысль короче
    stats: [["Минуты", "до ссылки на 3D"], ["Бесплатно", "на время беты"], ["Сразу", "без регистрации и карты"]],
    beta: "Пока расставляем мебель в гостиных и спальнях.",
    stripLabel: "Одна квартира: от плана до AI-картинки",
    strip: [
      { alt: "План квартиры с двумя спальнями", cap: "План" },
      { alt: "Та же квартира — серая 3D-модель", cap: "3D", t: "сразу" },
      { alt: "Её гостиная с мебелью в 3D", cap: "Мебель", t: "следом", tag: "Пройтись" },
      { alt: "AI-картинка той же гостиной", cap: "AI-картинка", t: "позже" },
    ],
    aiBadge: "AI-визуализация, не фото",
  },
  how: {
    h2: "Как это работает",
    steps: [["Загрузите план", "PDF или фото."], ["Мы строим 3D", "Отмечаем размеры, в которых не уверены."],
      ["Расставляем мебель", "Гостиная и спальни."], ["Отправьте ссылку", "Открывается в браузере."]],
  },
  cmp: {
    h2: "Минуты, а не дни", old: "3D на заказ",
    rows: [["Первый результат", "Обычно обещают 24–48 часов", "Минуты"], ["Чтобы начать", "Смета, звонок, ТЗ", "Загрузить план"],
      ["Мебель", "Подбирает студия", "С ценами"], ["Покупатель получает", "Картинки или приложение", "Ссылку в браузере"]],
    foot: "Сроки студий — с их собственных сайтов, ноябрь 2026.",
  },
  example: {
    h2: "Что вы получаете для каждого объявления", flat: "2 спальни · 77,2 м²", alt: "Гостиная, AI-картинка",
    room: "Гостиная · 14,4 м²", sum: "12 предметов · ориентировочно £2 091",
    items: [["Диван трёхместный, серая ткань", "диван"], ["Журнальный столик под орех", "столик"], ["Торшер, белый", "свет"],
      ["ТВ-тумба, дуб и серый", "хранение"]],
    gets: [
      { title: "Две ссылки", p: [["Ваша:", "посмотреть так, как увидит клиент."], ["Для покупателей:", "начинается с опроса о стиле."]] },
      { title: "Легко поделиться", p: [["", "В объявление, письмо или WhatsApp."]] },
      { title: "AI-картинки подписаны", p: [["", "Даже после скачивания."]] },
      { title: "Мебель с ценами", p: [["", "Те же предметы, что в туре."]] },
    ],
  },
  waiting: {
    h2: "Пока мы доделываем тур", lead: "Сначала откроется 3D, мебель и картинка появятся следом.",
    steps: [["План получен", "floorplan-flat-215.pdf"], ["Комнаты и размеры прочитаны", "7 комнат · 77,2 м²"], ["3D готово", ""],
      ["Расставляем мебель в гостиной и спальнях", ""], ["AI-картинка гостиной", ""]],
    note: "Время зависит от плана", ready: "Ваши ссылки готовы", open: "Открыть вашу ссылку", buyer: "Ссылка для покупателя",
    phTitle: "AI-картинка загружается…", phText: "появится здесь",
    mailTitle: "Не хотите ждать?", mailText: "Пришлём ссылки на почту.", mailPh: "you@agency.ru", mailLabel: "Почта", mailBtn: "Прислать",
  },
  faq: {
    h2: "Что спрашивают агенты",
    items: [
      ["Насколько точны размеры?", "По плану и вашим замерам. Размеры, в которых мы не уверены, отмечены. Не для обмеров."],
      ["Какая мебель показана?", "Из нашего каталога, с ценами в фунтах. Стиль можно сменить."],
      ["Какие комнаты обставляются?", "Гостиные и спальни. До двух этажей."],
      ["Что будет с моим планом?", "План и тур храним 30 дней: в это время план можно поправить. Никому их не передаём."],
    ],
  },
  final: { h2: "Попробуйте на следующем объявлении", upload: "Загрузить план", example: "Посмотреть пример" },
};

export const landingText = (lang: TrialLang): LandingText => (lang === "ru" ? ru : en);
