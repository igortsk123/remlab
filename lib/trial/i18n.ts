// Язык страниц пробы `/try*` (план agent-trial-08, задача П; владелец 09.11, TG 486–488): русский и английский.
// Выбор — как у живого `/demo` (`tools/scout/flat215-demo/index.html`, `LANG`): `?lang=ru|en` → сохранённый выбор
// (`localStorage['remlab-lang']`, тот же ключ) → язык браузера (у нас — заголовок Accept-Language) → язык рынка (UK — EN).
// Сохранённый выбор сервер не видит: его проверяет ранний скрипт оболочки (`components/trial/TryShell.tsx`).
// Здесь же — все строки формы, ожидания и лендинга; тексты шагов и ошибок берёт `lib/trial/steps.ts`.

export type TrialLang = "ru" | "en";
export const TRIAL_LANGS: readonly (readonly [TrialLang, string])[] = [["ru", "Русский"], ["en", "English"]];
export const LANG_KEY = "remlab-lang";
/** Язык рынка пробы (агенты UK) — для языков браузера без перевода. */
export const MARKET_LANG: TrialLang = "en";

export function parseLang(v: unknown): TrialLang | null {
  return v === "ru" || v === "en" ? v : null;
}

/** Первый поддерживаемый язык из Accept-Language (по весу q, при равном — по порядку); иначе язык рынка. */
export function langFromAccept(header: string | null | undefined): TrialLang {
  const want = (header ?? "").split(",").map((part, i) => {
    const [tag = "", ...params] = part.trim().split(";");
    const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
    return { code: tag.trim().slice(0, 2).toLowerCase(), q: q ? Number(q.slice(2)) || 0 : 1, i };
  }).filter((x) => x.code && x.q > 0).sort((a, b) => b.q - a.q || a.i - b.i);
  for (const w of want) { const l = parseLang(w.code); if (l) return l; }
  return MARKET_LANG;
}

/** Адрес с языком: остальное (путь, другие параметры, якорь) сохраняется. */
export function withLang(href: string, lang: TrialLang): string {
  const [beforeHash = "", hash] = href.split("#", 2);
  const [path = "", query = ""] = beforeHash.split("?", 2);
  const q = new URLSearchParams(query);
  q.set("lang", lang);
  return `${path}?${q.toString()}${hash !== undefined ? `#${hash}` : ""}`;
}

/** Тур задания (`/try/<id>/tour/` — страница `/demo` под план, план agent-trial-08) на выбранном языке. */
/** `k` — ключ правки агента (Р1): только в его ссылке, кривой не переносим; ссылка покупателя строится без него. */
export const tourHref = (id: string, lang: TrialLang, k?: string | null): string =>
  `/try/${encodeURIComponent(id)}/tour/?lang=${lang}${k && /^[A-Za-z0-9_-]{22}$/.test(k) ? `&k=${k}` : ""}`;

/** Русское число: 1 комната, 2 комнаты, 5 комнат. */
export function ruPlural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  return b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}

const en = {
  htmlLang: "en-GB",
  meta: {
    title: "RemLab for Agents",
    description: "Upload a PDF or photo and get a tour link for buyers.",
    jobTitle: "Your tour · RemLab for Agents",
  },
  shell: {
    how: "How it works", faq: "FAQ", example: "Example", beta: "© 2026 RemLab · Beta", privacy: "Privacy", contact: "Contact",
    langLabel: "Language",
  },
  form: {
    drop: "Drop your floor plan here", kinds: "PDF or photo", choose: "choose a file", chooseOther: "choose another file",
    sizesSummary: "Add room measurements if you have them", optional: "optional",
    sizesLabel: "Room sizes from the listing", sizesPlaceholder: "e.g. living room 4.8 m × 3.6 m",
    upload: "Upload a floor plan", uploading: "Uploading…", example: "See an example", mb: "MB", kb: "KB",
  },
  wait: {
    title: "Getting your tour ready", timerLabel: "Time since upload", progressLabel: "Progress",
    loading: "Loading…", offline: "Connection lost. Trying again…", retryNow: "Retry now",
    keepTitle: "No need to wait here", keepText: "Keep this link. The tour will be on it when it's ready.", copy: "Copy link",
  },
  msg: {
    tryAgain: "Try again", upload: "Upload a floor plan",
    errorTitle: "We can't reach the server", errorText: "Please check your connection.",
    missingTitle: "We can't find this tour", missingText: "Please check the link, or upload the plan again.",
    expiredTitle: "This tour has expired", expiredText: "We keep tours for 30 days. Upload the plan again to make a new one.",
    failedTitle: "We couldn't build this tour", cancelledText: "This upload was cancelled. Please upload the plan again.",
  },
  done: {
    title: "Your 3D is ready", opening: "Opening the tour…", open: "Open the tour", history: "How it went",
    readyIn: (t: string) => `Ready in ${t}`, rooms: (n: number) => `${n} ${n === 1 ? "room" : "rooms"}`,
    scaleTitle: "Scale not verified.", scaleText: "Room sizes may be off.",
    scaleArea: "Sizes are based on the total floor area — approximate.",
  },
  sizes: {
    title: "We couldn't find the room sizes", text: "Write what you know, in any form — we'll work it out.",
    appliedTitle: "Sizes applied", appliedText: "You can refine — write more",
    label: "Room sizes", placeholder: "e.g. living room 4.8 × 3.6 m, bedroom 3 × 3 m",
    send: "Send sizes", sending: "Sending…",
    accepted: "Got it. We'll apply the sizes once the plan is built.", applying: "Applying your sizes…",
    done: "Done — the tour is updated.", failed: "We couldn't apply the sizes. Please try again.",
    partial: "Applied. Some rooms still have no sizes — they're marked on the plan.",
    noMatch: "We couldn't match these sizes to rooms on the plan. Use the room names from the plan, e.g. “Bedroom 1 3.2 × 4”.",
    sourceGone: "The original plan is no longer stored. Please upload it again.",
    busy: "The tour is still updating. Try again in a minute.", limit: "Too many updates today. Try again tomorrow.",
    forbidden: "Only the agent's link can change the tour.", error: "Couldn't send. Please try again.",
  },
};

export type TrialText = typeof en;

const ru: TrialText = {
  htmlLang: "ru",
  meta: {
    title: "RemLab для агентов",
    description: "Загрузите PDF или фото плана и получите ссылку на тур для покупателей.",
    jobTitle: "Ваш тур · RemLab для агентов",
  },
  shell: {
    how: "Как это работает", faq: "Вопросы", example: "Пример", beta: "© 2026 RemLab · Бета", privacy: "Конфиденциальность", contact: "Контакты",
    langLabel: "Язык",
  },
  form: {
    drop: "Перетащите сюда план квартиры", kinds: "PDF или фото", choose: "выбрать файл", chooseOther: "выбрать другой файл",
    sizesSummary: "Добавьте размеры комнат, если они есть", optional: "необязательно",
    sizesLabel: "Размеры комнат из объявления", sizesPlaceholder: "например, гостиная 4,8 м × 3,6 м",
    upload: "Загрузить план", uploading: "Загружаем…", example: "Посмотреть пример", mb: "МБ", kb: "КБ",
  },
  wait: {
    title: "Готовим ваш тур", timerLabel: "Время с загрузки", progressLabel: "Ход работы",
    loading: "Загрузка…", offline: "Связь пропала. Пробуем снова…", retryNow: "Повторить сейчас",
    keepTitle: "Ждать здесь не обязательно", keepText: "Сохраните ссылку: тур появится по ней, когда будет готов.", copy: "Скопировать",
  },
  msg: {
    tryAgain: "Попробовать ещё раз", upload: "Загрузить план",
    errorTitle: "Нет связи с сервером", errorText: "Проверьте подключение к интернету.",
    missingTitle: "Тур не найден", missingText: "Проверьте ссылку или загрузите план заново.",
    expiredTitle: "Срок тура истёк", expiredText: "Мы храним туры 30 дней. Загрузите план заново, чтобы сделать новый.",
    failedTitle: "Не получилось собрать тур", cancelledText: "Эта загрузка отменена. Загрузите план заново.",
  },
  done: {
    title: "3D готово", opening: "Открываем тур…", open: "Открыть тур", history: "Как шла работа",
    readyIn: (t: string) => `Готово за ${t}`, rooms: (n: number) => `${n} ${ruPlural(n, "комната", "комнаты", "комнат")}`,
    scaleTitle: "Масштаб не подтверждён.", scaleText: "Размеры комнат могут быть неточными.",
    scaleArea: "Размеры по общей площади — примерные.",
  },
  sizes: {
    title: "Не нашли размеры комнат", text: "Напишите, что знаете, в любом виде — уточним.",
    appliedTitle: "Размеры применили", appliedText: "Можно уточнить — напишите ещё",
    label: "Размеры комнат", placeholder: "например: гостиная 4,8 на 3,6, спальня 3×3",
    send: "Отправить размеры", sending: "Отправляем…",
    accepted: "Приняли. Применим, когда план соберётся.", applying: "Применяем размеры…",
    done: "Готово — тур обновлён.", failed: "Не получилось применить размеры. Попробуйте ещё раз.",
    partial: "Применили. У части комнат размеров нет — они отмечены на плане.",
    noMatch: "Не смогли сопоставить размеры с комнатами плана. Напишите названия как на плане, например: «Спальня 1 — 3,2 на 4».",
    sourceGone: "Исходный план уже не хранится. Загрузите его заново.",
    busy: "Тур ещё обновляется. Попробуйте через минуту.", limit: "Слишком много обновлений за сутки. Попробуйте завтра.",
    forbidden: "Менять тур можно только по ссылке агента.", error: "Не удалось отправить. Попробуйте ещё раз.",
  },
};

export const TEXT: Record<TrialLang, TrialText> = { en, ru };
export const textOf = (lang: TrialLang): TrialText => TEXT[lang];
