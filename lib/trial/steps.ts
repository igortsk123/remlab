// Что показывает страница задания `/try/<id>` (план agent-trial-01, T-C): шаги по образцу блока «waiting» лендинга
// (макет v3-en-final, TG 420), таймер от загрузки, очередь и тексты ошибок по закрытому списку
// `contracts/trial.ts:trialErrorCode`. Чистые функции — проверяет `tests/unit/trial-steps.test.ts`.

import type { TrialErrorCode, TrialJobView, TrialStage } from "@/contracts/trial";

export type StepState = "done" | "run" | "next";
export type Step = { key: string; title: string; state: StepState; atSec: number | null };

const ORDER: TrialStage[] = ["queued", "raster", "labels", "walls", "repair", "export", "done"];
// Шаги макета: стадии воркера сведены в три. `last` — индекс последней стадии шага в ORDER.
const STEPS: { key: string; title: string; last: number }[] = [
  { key: "received", title: "Plan received", last: 0 },
  { key: "read", title: "Rooms and sizes read", last: 2 },
  { key: "build", title: "3D ready", last: 5 },
];
const stepOfStage = (i: number) => STEPS.findIndex((s) => i <= s.last);

/** Шаги для списка: готовые — с временем конца (с момента загрузки), текущий крутится, дальше — серые. */
export function stepsOf(job: TrialJobView): Step[] {
  const t0 = Date.parse(job.createdAt);
  const startedAt = new Map<TrialStage, number>();
  for (const s of job.stages) if (!startedAt.has(s.stage)) startedAt.set(s.stage, Date.parse(s.at));
  if (job.status === "done" && !startedAt.has("done") && job.finishedAt) startedAt.set("done", Date.parse(job.finishedAt));
  const stageIdx = ORDER.indexOf(job.stage);
  // взят воркером, а первой стадии ещё нет (stage = queued) — уже «читаем»; в очереди тот же шаг, но не крутится
  const cur = job.status === "done" ? STEPS.length : Math.max(1, stepOfStage(Math.max(0, stageIdx)));
  const final = job.status === "failed" || job.status === "cancelled";
  return STEPS.map((s, i) => {
    if (i === 0) return { key: s.key, title: s.title, state: "done" as const, atSec: 0 };
    const state: StepState = i < cur ? "done" : i === cur && !final && job.status !== "queued" ? "run" : "next";
    // конец шага = начало первой следующей стадии, которая была на самом деле (воркер мог стадию пропустить)
    let end: number | undefined;
    for (let k = s.last + 1; k < ORDER.length && end === undefined; k++) end = startedAt.get(ORDER[k]!);
    const atSec = state === "done" && end !== undefined ? Math.max(0, Math.round((end - t0) / 1000)) : null;
    return { key: s.key, title: s.title, state, atSec };
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

/** Строка под полоской: очередь, «машина занята» или как в макете. */
export function waitingNote(job: TrialJobView): string {
  if (!job.workerAlive && (job.status === "queued" || job.status === "running")) {
    return "Our 3D machine is busy right now. Your plan is saved and will start on its own, so you can leave this page and come back to the link.";
  }
  if (job.status === "queued") {
    if (job.queueAhead && job.queueAhead > 0) return `In the queue: ${job.queueAhead} ${job.queueAhead === 1 ? "plan" : "plans"} ahead of yours.`;
    return job.stages.length > 0 ? "Trying again in a few seconds." : "Starting in a moment.";
  }
  return "Times vary by floor plan";
}

const ERRORS: Record<TrialErrorCode, string> = {
  pdf_unreadable: "We couldn't open this PDF. It may be password protected or damaged. Try saving it again, or upload a picture of the plan.",
  unsupported: "We can't read this type of file. Please upload a PDF, JPG, PNG or WebP.",
  too_large: "This file is too big. The limit is 15 MB.",
  no_plan: "We couldn't find a floor plan in this file. Please upload a plan that shows the walls and room names.",
  budget: "We've reached today's limit for new tours. Please try again tomorrow.",
  vlm_error: "Something went wrong on our side while reading the plan. Please try again.",
  pipeline_error: "Something went wrong on our side while building the 3D. Please try again.",
  timeout: "This plan took too long to process. Please try again, or try a clearer copy of the plan.",
  lease_lost: "Something went wrong on our side while building the 3D. Please try again.",
  stale: "This plan waited too long and was not processed. Please upload it again.",
  internal: "Something went wrong on our side. Please try again.",
};
export const errorText = (code: TrialErrorCode | null): string => ERRORS[code ?? "internal"];

/** Ошибки загрузки (`app/api/trial/route.ts` и лимитер) → текст для формы. */
const UPLOAD_ERRORS: Record<string, string> = {
  busy: "We're busy right now. Please try again in a couple of minutes.",
  daily_cap: "We've reached today's limit for new tours. Please try again tomorrow.",
  rate_limited: "You've uploaded several plans in a row. Please wait about 10 minutes and try again.",
  too_large: "This file is too big. The limit is 15 MB.",
  unsupported_type: "We can't read this type of file. Please upload a PDF, JPG, PNG or WebP.",
  no_file: "Please choose a floor plan file first.",
  listing_too_long: "The room sizes text is too long. Please keep it under 5,000 characters.",
};
export const uploadErrorText = (code: string | undefined): string =>
  (code && UPLOAD_ERRORS[code]) || "The upload didn't go through. Please check your connection and try again.";
