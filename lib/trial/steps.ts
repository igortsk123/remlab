// Что показывает страница задания `/try/<id>` (план agent-trial-01, T-C): шаги по образцу блока «waiting» лендинга
// (макет v3-en-final, TG 420), таймер от загрузки, очередь и тексты ошибок по закрытому списку
// `contracts/trial.ts:trialErrorCode`. Тексты — на русском и английском (план agent-trial-08, П). Чистые функции —
// проверяет `tests/unit/trial-steps.test.ts`.

import type { TrialErrorCode, TrialJobView, TrialStage } from "@/contracts/trial";
import { ruPlural, type TrialLang } from "@/lib/trial/i18n";
import { TRIAL_UPLOAD_LIMITS } from "@/lib/trial/upload-limits";

export type StepState = "done" | "run" | "next";
export type Step = { key: string; title: string; state: StepState; atSec: number | null };

const ORDER: TrialStage[] = ["queued", "raster", "labels", "walls", "repair", "export", "done"];
// Шаги макета: стадии воркера сведены в три. `last` — индекс последней стадии шага в ORDER.
const STEPS: { key: string; title: Record<TrialLang, string>; last: number }[] = [
  { key: "received", title: { en: "Plan received", ru: "План получен" }, last: 0 },
  { key: "read", title: { en: "Rooms and sizes read", ru: "Комнаты и размеры прочитаны" }, last: 2 },
  { key: "build", title: { en: "3D ready", ru: "3D готово" }, last: 5 },
];
const stepOfStage = (i: number) => STEPS.findIndex((s) => i <= s.last);

/** Шаги для списка: готовые — с временем конца (с момента загрузки), текущий крутится, дальше — серые. */
export function stepsOf(job: TrialJobView, lang: TrialLang): Step[] {
  const t0 = Date.parse(job.createdAt);
  const startedAt = new Map<TrialStage, number>();
  for (const s of job.stages) if (!startedAt.has(s.stage)) startedAt.set(s.stage, Date.parse(s.at));
  if (job.status === "done" && !startedAt.has("done") && job.finishedAt) startedAt.set("done", Date.parse(job.finishedAt));
  const stageIdx = ORDER.indexOf(job.stage);
  // взят воркером, а первой стадии ещё нет (stage = queued) — уже «читаем»; в очереди тот же шаг, но не крутится
  const cur = job.status === "done" ? STEPS.length : Math.max(1, stepOfStage(Math.max(0, stageIdx)));
  const final = job.status === "failed" || job.status === "cancelled";
  return STEPS.map((s, i) => {
    if (i === 0) return { key: s.key, title: s.title[lang], state: "done" as const, atSec: 0 };
    const state: StepState = i < cur ? "done" : i === cur && !final && job.status !== "queued" ? "run" : "next";
    // конец шага = начало первой следующей стадии, которая была на самом деле (воркер мог стадию пропустить)
    let end: number | undefined;
    for (let k = s.last + 1; k < ORDER.length && end === undefined; k++) end = startedAt.get(ORDER[k]!);
    const atSec = state === "done" && end !== undefined ? Math.max(0, Math.round((end - t0) / 1000)) : null;
    return { key: s.key, title: s.title[lang], state, atSec };
  });
}

/** Доля готовности для полоски: 0…1. */
export function progressOf(job: TrialJobView): number {
  if (job.status === "done") return 1;
  const i = ORDER.indexOf(job.stage);
  return Math.min(0.95, (Math.max(0, i) + (job.status === "running" ? 0.5 : 0)) / ORDER.length);
}

/** Время шага «м:сс» (больше часа — «ч:мм:сс»). */
export function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(r).padStart(2, "0")}`;
}

/** Таймер в шапке карточки «мм:сс», как «01:42» в макете. */
export const timer = (sec: number): string => (sec >= 3600 ? clock(sec) : clock(sec).padStart(5, "0"));

/** Геометрия опубликована — пора в тур. Сейчас это `done`; промежуточная публикация (план agent-trial-08, З) даст
 *  `running` с `resultVersion > 0` — тур откроется сразу, мебель догрузится в нём. */
export const geometryReady = (job: TrialJobView): boolean =>
  job.bundleVersion > 0 && (job.status === "done" || job.status === "running");

/** Задание закрыто, а версии данных нет — тура не будет (T-20261110-07): страница говорит «не получилось», а не уводит в пустой тур. */
export const tourMissing = (job: TrialJobView): boolean => job.status === "done" && job.bundleVersion <= 0;

/** Строка под полоской: очередь, «машина занята» или как в макете. */
export function waitingNote(job: TrialJobView, lang: TrialLang): string {
  const ru = lang === "ru";
  if (!job.workerAlive && (job.status === "queued" || job.status === "running")) {
    return ru
      ? "Наша 3D-машина сейчас занята. План сохранён и запустится сам: страницу можно закрыть и вернуться по ссылке."
      : "Our 3D machine is busy right now. Your plan is saved and will start on its own, so you can leave this page and come back to the link.";
  }
  if (job.status === "queued") {
    const n = job.queueAhead ?? 0;
    if (n > 0) return ru ? `В очереди: перед вашим ${n} ${ruPlural(n, "план", "плана", "планов")}.` : `In the queue: ${n} ${n === 1 ? "plan" : "plans"} ahead of yours.`;
    if (job.stages.length > 0) return ru ? "Повторим через несколько секунд." : "Trying again in a few seconds.";
    return ru ? "Сейчас начнём." : "Starting in a moment.";
  }
  return ru ? "Время зависит от плана" : "Times vary by floor plan";
}

const WRONG_TYPE = { en: "We can't read this type of file. Please upload a PDF, JPG, PNG or WebP.", ru: "Такой тип файла мы не читаем. Загрузите PDF, JPG, PNG или WebP." };
const TOO_LARGE = { en: "This file is too big. The limit is 15 MB.", ru: "Файл слишком большой: можно до 15 МБ." };
const DAY_LIMIT = { en: "We've reached today's limit for new tours. Please try again tomorrow.", ru: "Новые туры на сегодня закончились. Попробуйте завтра." };
const BUILD_FAIL = { en: "Something went wrong on our side while building the 3D. Please try again.", ru: "У нас что-то пошло не так при сборке 3D. Попробуйте ещё раз." };
const INTERNAL = { en: "Something went wrong on our side. Please try again.", ru: "У нас что-то пошло не так. Попробуйте ещё раз." };

const ERRORS: Record<TrialErrorCode, Record<TrialLang, string>> = {
  pdf_unreadable: {
    en: "We couldn't open this PDF. It may be password protected or damaged. Try saving it again, or upload a picture of the plan.",
    ru: "Не получилось открыть этот PDF: возможно, он защищён паролем или повреждён. Сохраните его заново или загрузите картинку плана.",
  },
  unsupported: WRONG_TYPE,
  too_large: TOO_LARGE,
  no_plan: {
    en: "We couldn't find a floor plan in this file. Please upload a plan that shows the walls and room names.",
    ru: "В этом файле не нашлось плана квартиры. Загрузите план, на котором видны стены и названия комнат.",
  },
  budget: DAY_LIMIT,
  vlm_error: {
    en: "Something went wrong on our side while reading the plan. Please try again.",
    ru: "У нас что-то пошло не так при чтении плана. Попробуйте ещё раз.",
  },
  pipeline_error: BUILD_FAIL,
  timeout: {
    en: "This plan took too long to process. Please try again, or try a clearer copy of the plan.",
    ru: "План обрабатывался слишком долго. Попробуйте ещё раз или загрузите более чёткую копию плана.",
  },
  lease_lost: BUILD_FAIL,
  stale: { en: "This plan waited too long and was not processed. Please upload it again.", ru: "План слишком долго ждал и не был обработан. Загрузите его ещё раз." },
  internal: INTERNAL,
};
export const errorText = (code: TrialErrorCode | null, lang: TrialLang): string => ERRORS[code ?? "internal"][lang];

/** Ошибки загрузки (`app/api/trial/route.ts` и лимитер) → текст для формы. */
const UPLOAD_ERRORS: Record<string, Record<TrialLang, string>> = {
  busy: { en: "We're busy right now. Please try again in a couple of minutes.", ru: "Сейчас много загрузок. Попробуйте через пару минут." },
  daily_cap: DAY_LIMIT,
  rate_limited: {
    en: "You've uploaded a lot of plans in a row. Please try again within the hour.",
    ru: "Вы загрузили много планов подряд. Попробуйте снова в течение часа.",
  },
  too_large: TOO_LARGE,
  unsupported_type: WRONG_TYPE,
  no_file: { en: "Please choose a floor plan file first.", ru: "Сначала выберите файл с планом." },
  listing_too_long: {
    en: "The room sizes text is too long. Please keep it under 5,000 characters.",
    ru: "Текст с размерами слишком длинный: не больше 5000 знаков.",
  },
};
const UPLOAD_FAILED = {
  en: "The upload didn't go through. Please check your connection and try again.",
  ru: "Загрузка не прошла. Проверьте связь и попробуйте ещё раз.",
};
// суточный лимит с адреса: время сброса — из Retry-After (не жёстко), по-русски — по Москве, по-английски — UTC
const RESET_TZ: Record<TrialLang, string> = { ru: "Europe/Moscow", en: "UTC" };
const dayOf = (ms: number, tz: string) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, dateStyle: "short" }).format(ms);
function dayLimitText(lang: TrialLang, retryAfterSec: number, nowMs: number): string {
  const n = TRIAL_UPLOAD_LIMITS.day.limit, at = nowMs + retryAfterSec * 1000, tz = RESET_TZ[lang];
  const hhmm = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(at);
  const today = dayOf(at, tz) === dayOf(nowMs, tz);
  return lang === "ru"
    ? `Сегодня с этого адреса уже загружено ${n} ${ruPlural(n, "план", "плана", "планов")}. Попробуйте ${today ? "сегодня" : "завтра"} после ${hhmm} по Москве.`
    : `${n} plans have already been uploaded from this address today. Please try again ${today ? "today" : "tomorrow"} after ${hhmm} UTC.`;
}

// почасовой лимит адреса: через сколько минут — из Retry-After (окно фиксированное, поэтому не дольше часа)
function burstText(lang: TrialLang, retryAfterSec: number): string {
  const m = Math.max(1, Math.ceil(retryAfterSec / 60));
  return lang === "ru"
    ? `Вы загрузили много планов подряд. Попробуйте снова через ${m} ${ruPlural(m, "минуту", "минуты", "минут")}.`
    : `You've uploaded a lot of plans in a row. Please try again in ${m} ${m === 1 ? "minute" : "minutes"}.`;
}

/** Текст ошибки загрузки. `rate_limited` с Retry-After дольше короткого окна — сработал суточный лимит адреса (окна
 *  фиксированные: короткое отвечает не дольше `burst.windowSec`), тогда — когда можно снова; короче — «подряд» и через сколько
 *  минут (у суточного под конец суток это тоже верное время); без заголовка — «подряд» без числа. */
export function uploadErrorText(code: string | undefined, lang: TrialLang, retryAfterSec?: number | null, nowMs = Date.now()): string {
  if (code === "rate_limited" && retryAfterSec && retryAfterSec > 0) {
    return retryAfterSec > TRIAL_UPLOAD_LIMITS.burst.windowSec ? dayLimitText(lang, retryAfterSec, nowMs) : burstText(lang, retryAfterSec);
  }
  return ((code && Object.hasOwn(UPLOAD_ERRORS, code) ? UPLOAD_ERRORS[code] : undefined) ?? UPLOAD_FAILED)[lang];
}
