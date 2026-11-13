import { NextResponse } from "next/server";
import { z } from "zod";
import { COOKIE_NAME, cookieValue, loginOk, originOk } from "@/lib/mesh-review/auth";
import { loginTarget } from "@/lib/mesh-review/login-target";

// Ссылка-вход (владелец 28.08: «без кода доступа»): GET ?key=<секрет> ставит куку и
// уводит на страницу. Секрет остаётся обязательным — он просто зашит в закладку владельца;
// совсем без секрета нельзя: решения пишут ориентации в конвейер.
// Редирект — ОТНОСИТЕЛЬНЫЙ Location из списка (lib/mesh-review/login-target.ts): хост из req.url за прокси внутренний.
export async function GET(req: Request): Promise<Response> {
  const value = cookieValue();
  if (!value) return NextResponse.json({ error: "review disabled" }, { status: 503 });
  const q = new URL(req.url).searchParams;
  const key = q.get("key") ?? "";
  if (!key || !loginOk(key)) return NextResponse.json({ error: "нет" }, { status: 401 });
  const res = new NextResponse(null, { status: 302, headers: { location: loginTarget(q.get("to")) } });
  res.cookies.set(COOKIE_NAME, value, {
    httpOnly: true,
    secure: true,
    sameSite: "lax", // редирект после кросс-навигации из мессенджера/закладки должен донести куку
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}

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
