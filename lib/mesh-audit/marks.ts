// Правила нажатий «ок»/«брак» на /lab/mesh-check (T-20261112-118). Чистые функции: их гоняет vitest, repo-marks.ts только исполняет.
// «Брак» — та же очередь переделки, что «переделать» на /lab/mesh-audit (решение → мост DEV → инбокс; платный перегон — только
// обычной волной мешей с её потолком). Отметка человека и состояние переделки разные вещи (Codex 12.11): «брак» сохраняется
// всегда, решение создаётся, только если переделка ещё не идёт; повторное нажатие снимает отметку всегда, а решение отменяет,
// пока его не забрала волна (иначе отметка снята, переделка идёт — reason queued_kept, вкладка предупреждает).

import { MAX_MANUAL_REDO, type Verdict } from "./rules";

export type Press = "ok" | "bad";
export type Mark = "ok" | "bad";

export interface MarkState {
  generationKey: string;
  status: string;
  manualAttempts: number;
  mark: string | null;
}

export type PressPlan =
  | { applied: true; log: Mark | "clear"; next: Mark | null; decide?: Verdict; cancel?: true; reason?: "queued_kept" }
  | { applied: false; reason: "stale" | "state_conflict"; message: string };

const CANCELLABLE = new Set(["redo_requested", "replace_needed"]); // как rules.checkCancel: в волну ещё не ушло
const ACTIVE_REWORK = new Set(["redo_requested", "redo_queued", "replace_needed"]); // решение уже есть, второго не нужно

/** Снятие «брака»: отменить решение, если можно; ушло в волну — переделка идёт дальше. */
function unBad(item: MarkState): { cancel?: true; reason?: "queued_kept" } {
  if (CANCELLABLE.has(item.status)) return { cancel: true };
  if (item.status === "redo_queued") return { reason: "queued_kept" };
  return {};
}

/** expected — какую отметку видела вкладка (null — «не проверено»): другая вкладка успела нажать раньше — не применяем молча. */
export function planPress(item: MarkState, generationKey: string, press: Press, expected: Mark | null): PressPlan {
  if (item.generationKey !== generationKey) return { applied: false, reason: "stale", message: "модель уже заменена, обновите страницу" };
  if ((item.mark ?? null) !== expected) return { applied: false, reason: "state_conflict", message: "отметку уже поменяли в другой вкладке" };

  if (press === item.mark) {
    return { applied: true, log: "clear", next: null, ...(press === "bad" ? unBad(item) : {}) };
  }
  if (press === "bad") {
    if (ACTIVE_REWORK.has(item.status)) return { applied: true, log: "bad", next: "bad" };
    const decide: Verdict = item.manualAttempts < MAX_MANUAL_REDO ? "redo" : "replace_needed";
    return { applied: true, log: "bad", next: "bad", decide };
  }
  return { applied: true, log: "ok", next: "ok", ...(item.mark === "bad" ? unBad(item) : {}) };
}

/** «Проверено» = есть отметка по текущему поколению (сбрасывается новым поколением). */
export function isChecked(item: { mark: string | null }): boolean {
  return item.mark === "ok" || item.mark === "bad";
}

export function checkStateLine(item: {
  status: string;
  manualAttempts: number;
  mark: string | null;
  redoneAt: string | null;
  reworkError: string | null;
}): { text: string; tone: "bad" | "info" } | null {
  const n = `${item.manualAttempts} из ${MAX_MANUAL_REDO}`;
  switch (item.status) {
    case "redo_requested":
      return { text: `брак · уйдёт на переделку ${n}`, tone: "bad" };
    case "redo_queued":
      return { text: `на переделке ${n}`, tone: "bad" };
    case "redo_blocked":
      return { text: `переделка не удалась: ${item.reworkError ?? "см. конвейер"}`, tone: "bad" };
    case "replace_needed":
      return { text: "нужна замена товара или фото", tone: "bad" };
  }
  if (item.redoneAt && !item.mark) return { text: `сделана заново (${n}), посмотрите ещё раз`, tone: "info" };
  return null;
}
