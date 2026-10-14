// Чужой сайт не должен писать в наши ручки из браузера посетителя (план b2b-07 п.3, разбор Codex 14.10):
// `frame-ancestors` разрешает только ПОКАЗ рамкой, а POST из чужого источника — отдельный вопрос. Страница демо, 3D и
// рамка встраивания живут на нашем источнике, поэтому Origin у их запросов — наш. Нет Origin (сервер, curl) — пропускаем.

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
