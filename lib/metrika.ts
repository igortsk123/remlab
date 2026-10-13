// Яндекс Метрика: счётчик 110599064 (remont-lab.online, создан 2026-07-11 через Management API).
// Цели-действия (reachGoal): preview_ready, pack_unlocked. URL-цели считает MetrikaPageviews.

export const METRIKA_COUNTER_ID = 110599064;

declare global {
  interface Window {
    ym?: (counterId: number, method: string, ...args: unknown[]) => void;
  }
}

/** Можно ли слать событие сейчас (b2b-04): не на страницах менеджера/отчёта и, в английском режиме, только после
 *  согласия. Проверка на КАЖДОЕ событие: переход RU→EN без перезагрузки не должен продолжать слать данные. */
export function metrikaAllowed(): boolean {
  if (typeof window === "undefined" || typeof window.ym !== "function") return false;
  const p = window.location.pathname;
  if (p.startsWith("/manager") || p.startsWith("/partner")) return false;
  let stored: string | null = null, ok: string | null = null;
  try { stored = localStorage.getItem("remlab-lang"); ok = localStorage.getItem("remlab-cookies"); } catch { /* без хранилища — по адресу */ }
  const q = new URLSearchParams(window.location.search).get("lang");
  const en = q ? q === "en" : stored === "en";
  return !en || ok === "yes";
}

export function trackGoal(goal: string): void {
  if (metrikaAllowed()) window.ym?.(METRIKA_COUNTER_ID, "reachGoal", goal);
}
