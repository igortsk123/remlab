// Анонимная сессия (интерим-Auth, ADR-0002): id в httpOnly-cookie.
// ВАЖНО: cookie можно ЗАПИСЫВАТЬ только в Server Action / Route Handler, НЕ во время рендера страницы.
// Поэтому: getSessionId() (создаёт+пишет) — для действий; readSessionId() (только читает) — для страниц.

import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";

const COOKIE = "remlab_sid";

export async function getSessionId(): Promise<string> {
  const jar = await cookies();
  const existing = jar.get(COOKIE)?.value;
  if (existing) return existing;
  const sid = randomUUID();
  jar.set(COOKIE, sid, { httpOnly: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 365 });
  return sid;
}

// Только чтение — безопасно вызывать в Server Component (рендер страницы).
export async function readSessionId(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(COOKIE)?.value ?? null;
}
