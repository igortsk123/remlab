// Отмена/возврат действий покупателя в конфигураторе (план flat3d-sims-ux, критерий «отмена работает для выбора,
// групповой замены, перемещения, поворота и „убрать“»). Чистые функции над стеками снимков: подбор маленький
// (выбор + перестановки + убранные), хранить целиком дешевле и надёжнее, чем «обратные команды».

export interface History<T> {
  past: T[];
  future: T[];
}

/** Сколько шагов назад помним: больше человеку не нужно, а память и черновик не пухнут. */
export const HISTORY_LIMIT = 30;

export const emptyHistory = <T,>(): History<T> => ({ past: [], future: [] });

/** Новое действие: прежнее состояние — в прошлое, будущее (то, что отменяли) — сбрасывается. */
export function record<T>(h: History<T>, before: T): History<T> {
  return { past: [...h.past, before].slice(-HISTORY_LIMIT), future: [] };
}

/** Шаг назад: вернуть последнее прошлое, нынешнее — в будущее. null — отменять нечего. */
export function undo<T>(h: History<T>, now: T): { h: History<T>; value: T } | null {
  const value = h.past[h.past.length - 1];
  if (value === undefined) return null;
  return { h: { past: h.past.slice(0, -1), future: [now, ...h.future] }, value };
}

/** Шаг вперёд — обратное к `undo`. */
export function redo<T>(h: History<T>, now: T): { h: History<T>; value: T } | null {
  const value = h.future[0];
  if (value === undefined) return null;
  return { h: { past: [...h.past, now].slice(-HISTORY_LIMIT), future: h.future.slice(1) }, value };
}
