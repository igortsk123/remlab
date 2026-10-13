// Ограничение частоты и дневной потолок платных вызовов (план b2b-01, ADR-0256).
// Фиксированное окно: ключ + начало окна → счётчик. Правила проверяются по порядку, первое
// превышенное останавливает проверку. Сбой хранилища: платное — закрыто (лучше отказать, чем
// платить вслепую), бесплатное — открыто (лимитер не должен ронять сайт).

import { counterStore, type CounterStore } from "@/lib/ratelimit/store";

export type Rule = { key: string; limit: number; windowSec: number };
export type LimitResult =
  | { ok: true }
  | { ok: false; reason: "rate" | "daily_cap" | "unavailable"; retryAfterSec: number };

const DAY = 86_400;
const envInt = (name: string, dflt: number): number => {
  const v = Number(process.env[name]);
  return Number.isFinite(v) && v > 0 ? Math.floor(v) : dflt;
};

/** Наборы правил по маршрутам. `paid` — внешние деньги (ИИ, прокси): при сбое закрыто. */
export const PRESETS = {
  parseLink: (ip: string) => ({
    paid: true,
    rules: [
      { key: `parse-link:ip:${ip}`, limit: 10, windowSec: 60 },
      { key: `parse-link:ip-day:${ip}`, limit: 60, windowSec: DAY },
      { key: "paid:parse-link", limit: envInt("PAID_DAILY_CAP_PARSE", 500), windowSec: DAY },
    ],
  }),
  generate: (ip: string) => ({
    paid: true,
    rules: [
      { key: `gen:ip:${ip}`, limit: 5, windowSec: 60 },
      { key: `gen:ip-day:${ip}`, limit: 30, windowSec: DAY },
      { key: "paid:gen", limit: envInt("PAID_DAILY_CAP_GEN", 200), windowSec: DAY },
    ],
  }),
  flatConfig: (ip: string) => ({ paid: false, rules: [{ key: `flat-config:ip:${ip}`, limit: 20, windowSec: 60 }] }),
  lead: (ip: string) => ({ paid: false, rules: [{ key: `lead:ip:${ip}`, limit: 5, windowSec: 600 }] }),
  share: (ip: string) => ({ paid: false, rules: [{ key: `share:ip:${ip}`, limit: 20, windowSec: 600 }] }), // офис за одним адресом
  // Ссылки менеджера (b2b-02): карточку и события шлёт страница покупателя, менеджерские ручки — его страница.
  sendRead: (ip: string) => ({ paid: false, rules: [{ key: `send-read:ip:${ip}`, limit: 60, windowSec: 60 }] }),
  sendEvent: (ip: string) => ({ paid: false, rules: [{ key: `send-event:ip:${ip}`, limit: 120, windowSec: 600 }] }),
  manager: (ip: string) => ({ paid: false, rules: [{ key: `manager:ip:${ip}`, limit: 120, windowSec: 600 }] }),
} satisfies Record<string, (ip: string) => { paid: boolean; rules: Rule[] }>;

export function windowStart(nowMs: number, windowSec: number): Date {
  const w = windowSec * 1000;
  return new Date(Math.floor(nowMs / w) * w);
}

export async function checkLimits(
  set: { paid: boolean; rules: Rule[] },
  nowMs: number = Date.now(),
  store: CounterStore = counterStore(),
): Promise<LimitResult> {
  try {
    for (const r of set.rules) {
      const start = windowStart(nowMs, r.windowSec);
      const n = await store.hit(r.key, start);
      if (n > r.limit) {
        const retryAfterSec = Math.max(1, Math.ceil((start.getTime() + r.windowSec * 1000 - nowMs) / 1000));
        return { ok: false, reason: r.key.startsWith("paid:") ? "daily_cap" : "rate", retryAfterSec };
      }
    }
    if (Math.random() < 0.01) await store.prune(new Date(nowMs - 2 * DAY * 1000));
    return { ok: true };
  } catch {
    return set.paid ? { ok: false, reason: "unavailable", retryAfterSec: 60 } : { ok: true };
  }
}
