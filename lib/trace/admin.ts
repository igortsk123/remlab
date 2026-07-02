// Гард админ-доступа к трейсам (содержат фото пользователей). TRACE_ADMIN_TOKEN задан → нужен
// ?token= или заголовок x-trace-token. Не задан (dev) → доступ открыт. Секрет — только в env.

import { signAssetQuery } from "@/lib/trace/sign";

export function traceAdminOk(req: Request): boolean {
  const token = process.env.TRACE_ADMIN_TOKEN;
  if (!token) return true;
  const url = new URL(req.url);
  const provided = url.searchParams.get("token") ?? req.headers.get("x-trace-token");
  return provided === token;
}

// Абсолютная ПОДПИСАННАЯ ссылка на ассет для показа владельцу (открыть в браузере). Токен НЕ раскрывается:
// подпись — односторонний HMAC. База берётся из TRACE_PUBLIC_BASE_URL, иначе из origin запроса.
export function signedAssetUrl(id: string, req: Request, now: number = Date.now()): string {
  const base = process.env.TRACE_PUBLIC_BASE_URL || new URL(req.url).origin;
  return `${base.replace(/\/$/, "")}/api/trace/asset/${id}${signAssetQuery(id, now)}`;
}
