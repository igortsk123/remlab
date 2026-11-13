// Чужой сайт не должен писать в наши ручки из браузера посетителя (план b2b-07 п.3, разбор Codex 14.10):
// `frame-ancestors` разрешает только ПОКАЗ рамкой, а POST из чужого источника — отдельный вопрос. Страница демо, 3D и
// рамка встраивания живут на нашем источнике, поэтому Origin у их запросов — наш. Нет Origin (сервер, curl) — пропускаем.

export const SITE_ORIGIN = "https://remont-lab.online";
const OWN_HOST = /^([a-z0-9-]+\.)*remont-lab\.online$/i;
const LOCAL_HOST = /^(localhost|127\.0\.0\.1)(:\d+)?$/i;

/** Внешний адрес сайта для абсолютных ссылок, которые человек откроет в браузере (T-20261113-10). За прокси `req.url` —
 *  внутренний адрес (https://0.0.0.0:3000), поэтому: переменная окружения (`envBase` места вызова, затем APP_URL), иначе хост из
 *  заголовков прокси — только свой домен (remont-lab.online и поддомены, всегда https; вне production ещё localhost), любой другой
 *  хост (0.0.0.0, подставленный чужой) — адрес сайта. */
export function publicOrigin(req: Request, envBase?: string): string {
  const env = envBase || process.env.APP_URL;
  if (env) return env.replace(/\/$/, "");
  const first = (h: string | null) => (h ?? "").split(",")[0]?.trim() ?? "";
  const host = first(req.headers.get("x-forwarded-host")) || first(req.headers.get("host")) || new URL(req.url).host;
  if (OWN_HOST.test(host)) return `https://${host.toLowerCase()}`;
  if (process.env.NODE_ENV !== "production" && LOCAL_HOST.test(host)) return `http://${host}`;
  return SITE_ORIGIN;
}

/** true — запрос пришёл из браузера с ЧУЖОГО источника (Origin есть и его хост не наш). */
export function foreignOrigin(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? new URL(req.url).host;
  try {
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}
