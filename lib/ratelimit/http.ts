// HTTP-обвязка лимитов: адрес клиента и ответ 429/503 простым текстом (план b2b-01).

import { NextResponse } from "next/server";
import { checkLimits, PRESETS, type LimitResult } from "@/lib/ratelimit";

/** Адрес клиента. Caddy без trusted_proxies ЗАМЕНЯЕТ X-Forwarded-For реальным адресом,
 *  подделать первое значение снаружи нельзя. Без заголовка (локально) — "local". */
export function clientIp(h: Headers): string {
  const first = (h.get("x-forwarded-for") ?? "").split(",")[0]?.trim();
  return first || h.get("x-real-ip") || "local";
}

const TEXT: Record<Exclude<LimitResult, { ok: true }>["reason"], string> = {
  rate: "Слишком много запросов подряд. Подождите немного и попробуйте снова.",
  daily_cap: "На сегодня лимит таких запросов исчерпан. Попробуйте завтра.",
  unavailable: "Сервис временно недоступен. Попробуйте через минуту.",
};

export function limitResponse(r: Exclude<LimitResult, { ok: true }>): Response {
  return NextResponse.json(
    { ok: false, error: "rate_limited", message: TEXT[r.reason] },
    { status: r.reason === "unavailable" ? 503 : 429, headers: { "Retry-After": String(r.retryAfterSec) } },
  );
}

/** Проверить лимит маршрута: `null` — можно продолжать, иначе готовый ответ 429/503. */
export async function guard(req: Request, preset: keyof typeof PRESETS): Promise<Response | null> {
  const r = await checkLimits(PRESETS[preset](clientIp(req.headers)));
  return r.ok ? null : limitResponse(r);
}
