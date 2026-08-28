import { NextResponse } from "next/server";
import { z } from "zod";
import { COOKIE_NAME, cookieValue, loginOk, originOk } from "@/lib/mesh-review/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Вход владельца: секрет → подписанная кука. Секрета в env нет → 503 (fail-closed).
export async function POST(req: Request): Promise<Response> {
  const value = cookieValue();
  if (!value) return NextResponse.json({ error: "review disabled" }, { status: 503 });
  if (!(await originOk())) return NextResponse.json({ error: "bad origin" }, { status: 403 });
  const parsed = z.object({ secret: z.string().min(1) }).safeParse(await req.json().catch(() => null));
  if (!parsed.success || !loginOk(parsed.data.secret)) {
    return NextResponse.json({ error: "нет" }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_NAME, value, {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
