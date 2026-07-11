// Работа со ссылками сметы. Внешний переход ВСЕГДА через /go/ — это условие late-binding реф
// (ADR-0016): подмена прямой ссылки на партнёрскую = правка маршрута, чек-листы не трогаем.

export function domainFromUrl(url: string): string | null {
  try {
    const h = new URL(url).hostname.toLowerCase();
    return h.startsWith("www.") ? h.slice(4) : h;
  } catch {
    return null;
  }
}

// Маршрут реф-программы: домен магазина → шаблон реф-URL ({url} = исходная ссылка, url-encoded).
// Один домен может иметь несколько маршрутов в разных сетях — берём активный с макс. приоритетом.
export type LinkRoute = { domain: string; network: string; urlTemplate: string; priority: number; active: boolean };

export function resolveTarget(originalUrl: string, routes: LinkRoute[]): string {
  const domain = domainFromUrl(originalUrl);
  if (!domain) return originalUrl;
  const match = routes
    .filter((r) => r.active && r.domain === domain)
    .sort((a, b) => b.priority - a.priority)[0];
  if (!match) return originalUrl; // маршрута нет — отдаём прямую (реф догонит позже)
  return match.urlTemplate.replace("{url}", encodeURIComponent(originalUrl));
}
