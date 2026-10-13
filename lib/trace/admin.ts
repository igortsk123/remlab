// Гард админ-доступа к трейсам (содержат фото пользователей). Токен — ТОЛЬКО заголовком
// x-trace-token (план b2b-01): в адресе он оседал в журнале Caddy, истории браузера и Referer.
// TRACE_ADMIN_TOKEN не задан: в production закрыто, в dev открыто. Секрет — только в env.

import { safeEqual } from "@/lib/safe-equal";
import { signAssetQuery } from "@/lib/trace/sign";

export function traceAdminOk(req: Request): boolean {
  const token = process.env.TRACE_ADMIN_TOKEN;
  if (!token) return process.env.NODE_ENV !== "production";
  return safeEqual(req.headers.get("x-trace-token") ?? "", token);
}

// Абсолютная ПОДПИСАННАЯ ссылка на ассет для показа владельцу (открыть в браузере). Токен НЕ раскрывается:
// подпись — односторонний HMAC. База берётся из TRACE_PUBLIC_BASE_URL, иначе из origin запроса.
export function signedAssetUrl(id: string, req: Request, now: number = Date.now()): string {
  const base = process.env.TRACE_PUBLIC_BASE_URL || new URL(req.url).origin;
  return `${base.replace(/\/$/, "")}/api/trace/asset/${id}${signAssetQuery(id, now)}`;
}
