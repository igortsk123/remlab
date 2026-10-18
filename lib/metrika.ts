// Яндекс Метрика: счётчик 110599064 (remont-lab.online, создан 2026-07-11 через Management API).
// Цели-действия (reachGoal): preview_ready, pack_unlocked. URL-цели считает MetrikaPageviews.

export const METRIKA_COUNTER_ID = 110599064;

/** Счётчик инициализирован (`app/layout.tsx`, в т.ч. после согласия в баннере) — пора слать первый хит. */
export const METRIKA_READY_EVENT = "remlab-metrika-ready";

/**
 * Адрес для Метрики: значения КЛЮЧЕЙ покупателя заменены на `*`, остальное (utm, demo, flat…) — как было.
 * Ключи: `s` — подборка менеджера, `c` — корзина, `coll` — коллекция (`app/flat/page.tsx: Search`). Кто знает значение —
 * открывает чужую корзину, поэтому во внешнюю аналитику оно не уходит: Метрика видит только «пришёл по ссылке» (`s=*`).
 * Функция САМОДОСТАТОЧНА (ни одного внешнего имени): её текст вставлен в скрипт старта счётчика `app/layout.tsx`.
 */
export function metrikaSafeUrl(url: string): string {
  const keys = ["s", "c", "coll"];
  const q = url.indexOf("?");
  if (q < 0) return url;
  const h = url.indexOf("#", q);
  const out = new URLSearchParams();
  let masked = false;
  new URLSearchParams(url.slice(q + 1, h < 0 ? undefined : h)).forEach((v, k) => {
    const hide = keys.indexOf(k) >= 0 && v !== "";
    masked = masked || hide;
    out.append(k, hide ? "*" : v);
  });
  return masked ? url.slice(0, q + 1) + out.toString() + (h < 0 ? "" : url.slice(h)) : url;
}

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
