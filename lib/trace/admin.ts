// Гард админ-доступа к трейсам (содержат фото пользователей). Токен — ТОЛЬКО заголовком
// x-trace-token (план b2b-01): в адресе он оседал в журнале Caddy, истории браузера и Referer.
// TRACE_ADMIN_TOKEN не задан: в production закрыто, в dev открыто. Секрет — только в env.

import { publicOrigin } from "@/lib/http/origin";
import { safeEqual } from "@/lib/safe-equal";
import { signAssetQuery } from "@/lib/trace/sign";

export function traceAdminOk(req: Request): boolean {
  const token = process.env.TRACE_ADMIN_TOKEN;
  if (!token) return process.env.NODE_ENV !== "production";
  return safeEqual(req.headers.get("x-trace-token") ?? "", token);
}

// Абсолютная ПОДПИСАННАЯ ссылка на ассет для показа владельцу (открыть в браузере). Токен НЕ раскрывается:
// подпись — односторонний HMAC. База — TRACE_PUBLIC_BASE_URL, иначе внешний адрес сайта (`publicOrigin`, T-20261113-10): origin
// запроса за прокси — внутренний https://0.0.0.0:3000, такая ссылка у владельца не открывалась.
export function signedAssetUrl(id: string, req: Request, now: number = Date.now()): string {
  return `${publicOrigin(req, process.env.TRACE_PUBLIC_BASE_URL)}/api/trace/asset/${id}${signAssetQuery(id, now)}`;
}
