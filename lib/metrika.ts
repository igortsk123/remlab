// Яндекс Метрика: счётчик 110599064 (remont-lab.online, создан 2026-07-11 через Management API).
// Цели-действия (reachGoal): preview_ready, pack_unlocked. URL-цели считает MetrikaPageviews.

export const METRIKA_COUNTER_ID = 110599064;

/** Счётчик инициализирован (`app/layout.tsx`, в т.ч. после согласия в баннере) — пора слать первый хит. */
export const METRIKA_READY_EVENT = "remlab-metrika-ready";

/**
 * Адрес для Метрики: КЛЮЧИ покупателя заменены на `*`, остальное (utm, demo, flat…) — как было.
 * Ключи в параметрах: `s` — подборка менеджера, `c` — корзина, `coll` — коллекция (`app/flat/page.tsx: Search`).
 * Ключи в пути: `/e/<id>` — смета (`app/e/[id]/page.tsx`, правится по одному id), `/p/<id>/…` — проект
 * (`app/p/[id]/*`, без проверки владельца), `/go/<eid>/<iid>` — переход из сметы (`app/go/[eid]/[iid]/route.ts`).
 * Публичные сегменты (`/calc/<вид>`, `/embed/<партнёр>/<квартира>`) не трогаем. Кто знает значение — открывает
 * чужую корзину/смету, поэтому во внешнюю аналитику оно не уходит: Метрика видит только `s=*`, `/e/*`.
 * Принимает и путь, и полный адрес (реферер); хост не проверяет. Изменился адрес → он «с ключом» (карта кликов
 * и Вебвизор выключаются: `app/layout.tsx`, `components/MetrikaPageviews.tsx`).
 * Функция САМОДОСТАТОЧНА (ни одного внешнего имени): её текст вставлен в скрипт старта счётчика `app/layout.tsx`.
 */
export function metrikaSafeUrl(url: string): string {
  const keys = ["s", "c", "coll"];
  const end = url.search(/[?#]/);
  const pathEnd = end < 0 ? url.length : end;
  const scheme = url.indexOf("://");
  const start = scheme < 0 ? 0 : url.indexOf("/", scheme + 3);
  let masked = false;
  let path = url.slice(0, pathEnd);
  if (start >= 0 && start < pathEnd) {
    const segs = url.slice(start, pathEnd).split("/");
    const head = segs[1] || "";
    const n = head === "go" ? 2 : head === "e" || head === "p" ? 1 : 0; // сколько сегментов за префиксом — ключ
    for (let i = 2; i < 2 + n && i < segs.length; i++) {
      if (segs[i] !== "" && segs[i] !== "*") { segs[i] = "*"; masked = true; }
    }
    path = url.slice(0, start) + segs.join("/");
  }
  let rest = url.slice(pathEnd); // "?…#…", "#…" или ""
  if (rest.charAt(0) === "?") {
    const h = rest.indexOf("#");
    const out = new URLSearchParams();
    let hidden = false;
    new URLSearchParams(rest.slice(1, h < 0 ? undefined : h)).forEach((v, k) => {
      const hide = keys.indexOf(k) >= 0 && v !== "";
      hidden = hidden || hide;
      out.append(k, hide ? "*" : v);
    });
    if (hidden) { rest = "?" + out.toString() + (h < 0 ? "" : rest.slice(h)); masked = true; }
  }
  return masked ? path + rest : url;
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
