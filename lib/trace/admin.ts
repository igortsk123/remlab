// Гард админ-доступа к трейсам (содержат фото пользователей). TRACE_ADMIN_TOKEN задан → нужен
// ?token= или заголовок x-trace-token. Не задан (dev) → доступ открыт. Секрет — только в env.

export function traceAdminOk(req: Request): boolean {
  const token = process.env.TRACE_ADMIN_TOKEN;
  if (!token) return true;
  const url = new URL(req.url);
  const provided = url.searchParams.get("token") ?? req.headers.get("x-trace-token");
  return provided === token;
}

// Суффикс токена для ссылок на ассеты (чтобы ссылка работала при включённом гарде).
export function tokenQuery(): string {
  const token = process.env.TRACE_ADMIN_TOKEN;
  return token ? `?token=${encodeURIComponent(token)}` : "";
}
