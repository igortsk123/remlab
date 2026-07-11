// Яндекс Метрика: счётчик 110599064 (remont-lab.online, создан 2026-07-11 через Management API).
// Цели-действия (reachGoal): preview_ready, pack_unlocked. URL-цели считает MetrikaPageviews.

export const METRIKA_COUNTER_ID = 110599064;

declare global {
  interface Window {
    ym?: (counterId: number, method: string, ...args: unknown[]) => void;
  }
}

export function trackGoal(goal: string): void {
  if (typeof window !== "undefined" && typeof window.ym === "function") {
    window.ym(METRIKA_COUNTER_ID, "reachGoal", goal);
  }
}
