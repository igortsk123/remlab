// HTTP-обвязка ручек пробы: единые заголовки (no-store, no-referrer) и чтение JSON-тела с потолком по байтам.

import { NextResponse } from "next/server";
import type { z } from "zod";
import { TRIAL_HEADERS } from "@/lib/trial/config";
import { TOKEN_RE } from "@/lib/token";

export const trialJson = (body: unknown, status = 200, extra: Record<string, string> = {}): Response =>
  NextResponse.json(body, { status, headers: { ...TRIAL_HEADERS, ...extra } });

export const fail = (status: number, error: string, extra: Record<string, string> = {}): Response =>
  trialJson({ ok: false, error }, status, extra);

/** id задания — ключ ссылки: только формат `lib/token.ts:TOKEN_RE`, иначе как «нет такого». */
export const validId = (id: string): boolean => TOKEN_RE.test(id);

/** Тело целиком, но не больше `max` байт (по реально пришедшим). null — превышение или обрыв. */
export async function readLimited(req: Request, max: number): Promise<string | null> {
  if (!req.body) return "";
  const reader = req.body.getReader();
  const parts: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > max) { await reader.cancel(); return null; }
      parts.push(value);
    }
  } catch {
    return null;
  }
  return Buffer.concat(parts).toString("utf8");
}

/** JSON по схеме: Response — готовый отказ (413/400), иначе данные. */
export async function parseBody<S extends z.ZodType>(req: Request, schema: S, max = 64 * 1024): Promise<z.infer<S> | Response> {
  const text = await readLimited(req, max);
  if (text === null) return fail(413, "too_large");
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { return fail(400, "bad_json"); }
  const p = schema.safeParse(raw);
  return p.success ? p.data : fail(400, "bad_request");
}
