// Чистые правила страницы проверки вырезок /lab/cutout-check (T-20261119-104): нажатие «ок»/«не ок», версия комментария, фильтры, надписи RU/EN.
// Без БД и сети — их гоняет vitest; серверный слой (repo.ts) только исполняет. Страницы — те же 20 карточек, что у /lab/mesh-check.

export { PAGE_SIZE, pageCount, clampPage } from "@/lib/mesh-audit/rules";

export type Mark = "ok" | "bad";
export type CheckFilter = "all" | "todo" | "bad";
export const FILTERS: readonly CheckFilter[] = ["all", "todo", "bad"];

export function parseFilter(raw: string | undefined): CheckFilter {
  return FILTERS.find((f) => f === raw) ?? "all";
}

export type PressPlan =
  | { applied: true; log: Mark | "clear"; next: Mark | null }
  | { applied: false; reason: "stale" | "state_conflict"; message: string };

/** Одна кнопка «не ок»: нет отметки = «ок». press=bad ставит отметку, повтор снимает; press=ok («вернуть в ок») всегда снимает.
 * expected — какую отметку видела вкладка (null — без отметки): другая вкладка успела раньше — не применяем молча. */
export function planPress(item: { generationKey: string; mark: string | null }, generationKey: string, press: Mark, expected: Mark | null): PressPlan {
  if (item.generationKey !== generationKey) return { applied: false, reason: "stale", message: "вырезка уже заменена, обновите страницу" };
  if ((item.mark ?? null) !== expected) return { applied: false, reason: "state_conflict", message: "отметку уже поменяли в другой вкладке" };
  if (press === "bad" && item.mark !== "bad") return { applied: true, log: "bad", next: "bad" };
  return { applied: true, log: "clear", next: null };
}

/** «Просмотрено» (карточка побыла на экране ≥ 1 с): записываем один раз; вырезка заменена — только отказ. */
export function viewVerdict(item: { generationKey: string; viewedAt: Date | string | null }, generationKey: string): "apply" | "stale" | "already" {
  if (item.generationKey !== generationKey) return "stale";
  return item.viewedAt ? "already" : "apply";
}

/** Сколько секунд карточка должна быть на экране, чтобы считаться просмотренной (владелец: без кликов). */
export const VIEW_MS = 1000;

/** Версия комментария: принять или только записать в журнал (вырезка заменена / версия старее принятой). */
export function noteVerdict(item: { generationKey: string; noteSeq: number | null }, n: { generationKey: string; seq: number }): "apply" | "stale" | "older" {
  if (item.generationKey !== n.generationKey) return "stale";
  if (item.noteSeq !== null && n.seq <= item.noteSeq) return "older";
  return "apply";
}

/** Просмотрена = побыла на экране или владелец сам нажал «не ок». */
export function isChecked(item: { mark: string | null; viewedAt?: string | Date | null }): boolean {
  return item.mark === "bad" || item.mark === "ok" || !!item.viewedAt;
}

export interface Counts {
  total: number;
  checked: number;
  bad: number;
}

export function countMarks(rows: readonly { mark: string | null; viewedAt?: string | Date | null }[]): Counts {
  return { total: rows.length, checked: rows.filter(isChecked).length, bad: rows.filter((r) => r.mark === "bad").length };
}

/** Надписи парой RU/EN (владелец 12.11, TG 1341): везде показываем обе, русская — основная. */
export const L = {
  title: { ru: "Проверка вырезок", en: "Cutout check" },
  undo: { ru: "вернуть в ок", en: "back to OK" },
  photo: { ru: "Фото магазина", en: "Shop photo" },
  cutChecker: { ru: "Вырезка · шахматка", en: "Cutout · checkerboard" },
  cutDark: { ru: "Вырезка · тёмный фон", en: "Cutout · dark" },
  ok: { ru: "Ок", en: "OK" },
  bad: { ru: "Не ок", en: "Not OK" },
  badOn: { ru: "Не ок · нажмите, чтобы снять", en: "Not OK · tap to undo" },
  note: { ru: "Что не так? (необязательно)", en: "What is wrong? (optional)" },
  rule: { ru: "Всё, что не нажато, считается «ок»", en: "Anything you do not tap counts as OK" },
  all: { ru: "все", en: "all" },
  todo: { ru: "непросмотренные", en: "not viewed" },
  badFilter: { ru: "не ок", en: "not OK" },
  checked: { ru: "просмотрено", en: "viewed" },
  of: { ru: "из", en: "of" },
  next: { ru: "следующие 20", en: "next 20" },
  prev: { ru: "назад", en: "back" },
  empty: { ru: "Здесь пусто", en: "Nothing here" },
  zoomHint: { ru: "нажмите, чтобы увеличить", en: "tap to enlarge" },
  noPic: { ru: "нет картинки", en: "no image" },
} as const;

export type Pair = { ru: string; en: string };
