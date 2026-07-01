// Анонимная сессия (интерим-Auth, ADR-0002): id в httpOnly-cookie. Позже заменим на реальный Auth.

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
