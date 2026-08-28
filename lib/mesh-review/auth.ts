// Доступ к проверке ориентации мешей (/lab/mesh-review) — fail-closed (Codex q25:
// существующий trace/admin.ts — плохой образец, он fail-open и берёт токен из query).
// Два независимых секрета: MESH_REVIEW_SECRET — вход владельца (кука HttpOnly, HMAC-подпись),
// MESH_REVIEW_MACHINE_TOKEN — DEV-конвейер (Bearer). Нет секрета в env → 503, не «пускаем всех».

import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies, headers } from "next/headers";

export const COOKIE_NAME = "mesh_review";

function secret(): string | null {
  return process.env.MESH_REVIEW_SECRET || null;
}

export function cookieValue(): string | null {
  const s = secret();
  if (!s) return null;
  return createHmac("sha256", s).update("mesh-review-ok").digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

export function loginOk(candidate: string): boolean {
  const s = secret();
  return !!s && safeEqual(candidate, s);
}

/** Кука владельца валидна? (для страницы и браузерных ручек) */
export async function reviewerOk(): Promise<boolean> {
  const expected = cookieValue();
  if (!expected) return false;
  const got = (await cookies()).get(COOKIE_NAME)?.value ?? "";
  return got !== "" && safeEqual(got, expected);
}

/** Машинный токен DEV-конвейера валиден? */
export async function machineOk(): Promise<boolean> {
  const token = process.env.MESH_REVIEW_MACHINE_TOKEN;
  if (!token) return false;
  const auth = (await headers()).get("authorization") ?? "";
  return auth.startsWith("Bearer ") && safeEqual(auth.slice(7), token);
}

/** POST из браузера принимаем только со своего origin (CSRF в дополнение к SameSite=Strict). */
export async function originOk(): Promise<boolean> {
  const h = await headers();
  const origin = h.get("origin");
  if (!origin) return true; // same-origin fetch без Origin (например curl владельца с кукой) — пропускаем, кука подписана
  const host = h.get("host") ?? "";
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
