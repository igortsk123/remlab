// Анонимная сессия (интерим-Auth, ADR-0002): id в httpOnly-cookie.
// ВАЖНО: cookie можно ЗАПИСЫВАТЬ только в Server Action / Route Handler, НЕ во время рендера страницы.
// Поэтому: getSessionId() (создаёт+пишет) — для действий; readSessionId() (только читает) — для страниц.

import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";

const COOKIE = "remlab_sid";
const MAX_AGE = 60 * 60 * 24 * 30; // 30 дней (решение владельца, launch-p2); продлевается при активности

export async function getSessionId(): Promise<string> {
  const jar = await cookies();
  const existing = jar.get(COOKIE)?.value;
  const sid = existing ?? randomUUID();
  // Продление при активности: каждый server action сдвигает срок ещё на 30 дней.
  jar.set(COOKIE, sid, { httpOnly: true, sameSite: "lax", path: "/", maxAge: MAX_AGE });
  return sid;
}

// Только чтение — безопасно вызывать в Server Component (рендер страницы).
export async function readSessionId(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(COOKIE)?.value ?? null;
}
