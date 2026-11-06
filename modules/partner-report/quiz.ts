// Блок «Знакомство» отчёта застройщику (план onb-12, ADR-0265 + ADR-0330 п.4): счётчики опроса из `page_counters` за окно отчёта,
// по квартире. Только числа по значениям словарей (`contracts/quiz.ts`) — без людей и ссылок. Квартира без событий опроса строки
// не получает; нет ни одной — в отчёте нет и блока (`buildReport`).

import { quizChildAge, quizColour, quizHousehold, quizKids, quizStyle } from "@/contracts/quiz";

export type QuizCount = { id: string; n: number };
export type QuizRow = {
  apartmentId: string;
  open: number; done: number; skip: number; styleChange: number;
  photo: QuizCount[]; result: QuizCount[]; chosen: QuizCount[];
  household: QuizCount[]; child: QuizCount[]; kids: QuizCount[]; colour: QuizCount[];
};

type Group = "photo" | "result" | "chosen" | "household" | "child" | "kids" | "colour";
type Step = "open" | "done" | "skip" | "styleChange";
const STEP: Record<string, Step> = { quiz_open: "open", quiz_done: "done", quiz_skip: "skip", style_change: "styleChange" };
const GROUP: Record<string, { group: Group; ids: readonly string[] }> = {
  quiz_photo: { group: "photo", ids: quizStyle.options }, quiz_result: { group: "result", ids: quizStyle.options },
  quiz_chosen: { group: "chosen", ids: quizStyle.options }, quiz_household: { group: "household", ids: quizHousehold.options },
  quiz_child: { group: "child", ids: quizChildAge.options }, quiz_kids: { group: "kids", ids: quizKids.options },
  quiz_colour: { group: "colour", ids: quizColour.options },
};

/** Счётчик опроса — действие (`quiz_open` …) или ответ словаря (`quiz_photo:loft` …); незнакомое значение — не опрос. */
export function quizPart(kind: string): { step: Step } | { group: Group; id: string } | null {
  const step = STEP[kind];
  if (step) return { step };
  const i = kind.indexOf(":"), g = i > 0 ? GROUP[kind.slice(0, i)] : undefined, id = kind.slice(i + 1);
  return g && g.ids.includes(id) ? { group: g.group, id } : null;
}

/**
 * Порядок строк: стили — как на витрине квартиры (`showcase`, порядок вкладок), стиль вне витрины — только если его выбирали;
 * витрина неизвестна — по словарю и только выбранные. Остальное — по словарю, все значения (ноль — тоже ответ).
 */
function ordered(group: Group, counts: Map<string, number>, showcase?: string[]): QuizCount[] {
  const dict = Object.values(GROUP).find((g) => g.group === group)!.ids;
  const n = (id: string) => counts.get(id) ?? 0;
  if (group === "photo" || group === "result" || group === "chosen") {
    const shown = showcase?.filter((id) => dict.includes(id)) ?? [];
    return [...shown, ...dict.filter((id) => !shown.includes(id) && n(id) > 0)].map((id) => ({ id, n: n(id) }));
  }
  return dict.map((id) => ({ id, n: n(id) }));
}

export function buildQuiz(counters: { apartmentId: string; kind: string; n: number }[], showcase: Record<string, string[]> = {}): QuizRow[] {
  const acc = new Map<string, { steps: Record<string, number>; groups: Record<Group, Map<string, number>> }>();
  for (const c of counters) {
    const p = quizPart(c.kind);
    if (!p) continue;
    const a = acc.get(c.apartmentId) ?? acc.set(c.apartmentId, { steps: {}, groups: { photo: new Map(), result: new Map(), chosen: new Map(),
      household: new Map(), child: new Map(), kids: new Map(), colour: new Map() } }).get(c.apartmentId)!;
    if ("step" in p) a.steps[p.step] = (a.steps[p.step] ?? 0) + c.n;
    else a.groups[p.group].set(p.id, (a.groups[p.group].get(p.id) ?? 0) + c.n);
  }
  return [...acc.entries()].sort(([x], [y]) => x.localeCompare(y)).map(([apartmentId, a]) => ({
    apartmentId, open: a.steps.open ?? 0, done: a.steps.done ?? 0, skip: a.steps.skip ?? 0, styleChange: a.steps.styleChange ?? 0,
    photo: ordered("photo", a.groups.photo, showcase[apartmentId]), result: ordered("result", a.groups.result, showcase[apartmentId]),
    chosen: ordered("chosen", a.groups.chosen, showcase[apartmentId]), household: ordered("household", a.groups.household),
    child: ordered("child", a.groups.child), kids: ordered("kids", a.groups.kids), colour: ordered("colour", a.groups.colour),
  }));
}
