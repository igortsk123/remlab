// Доступ воркера DEV к ручкам `/api/trial/worker/*` — по образцу `lib/mesh-review/auth.ts:machineOk`, но fail-closed
// явно: нет TRIAL_WORKER_TOKEN в env → 503 (ручки закрыты, а не «пускаем всех»); неверный Bearer → 401.

import { NextResponse } from "next/server";
import { safeEqual } from "@/lib/safe-equal";
import { TRIAL_HEADERS } from "@/lib/trial/config";

export type WorkerAuth = "ok" | "unconfigured" | "denied";

export function workerAuth(h: Headers, env: Record<string, string | undefined> = process.env): WorkerAuth {
  const token = env.TRIAL_WORKER_TOKEN;
  if (!token) return "unconfigured";
  const auth = h.get("authorization") ?? "";
  return auth.startsWith("Bearer ") && safeEqual(auth.slice(7), token) ? "ok" : "denied";
}

/** `null` — можно продолжать; иначе готовый ответ 503/401. */
export function workerGuard(req: Request): Response | null {
  const a = workerAuth(req.headers);
  if (a === "ok") return null;
  return NextResponse.json(
    { ok: false, error: a === "unconfigured" ? "worker_api_closed" : "unauthorized" },
    { status: a === "unconfigured" ? 503 : 401, headers: TRIAL_HEADERS },
  );
}
