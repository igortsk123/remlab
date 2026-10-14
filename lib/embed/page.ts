// Встраивание демо на сайт застройщика (план b2b-07, разбор Codex 14.10). Чистые функции: заголовок «кто может
// показать нас рамкой» и вставка режима встраивания в HTML демо.

/** frame-ancestors: мы сами + домены партнёра из реестра (`contracts/partner.ts:frameDomains`, уже проверены схемой). */
export function embedCsp(frameDomains: readonly string[]): string {
  return ["frame-ancestors 'self'", ...frameDomains].join(" ");
}

const SAFE = /^[a-z0-9-]{2,40}$/;

/**
 * HTML демо → страница встраивания. `<base href="/demo/">` — первым в `<head>`, ДО любых адресов: относительные
 * `demo-data.json`, `img/…` грузятся из витрины. `window.__EMBED` включает в демо режим встраивания (высота и события
 * наружу, адрес не переписывается, 3D — в новой вкладке); `__sendFlat` — квартира из адреса встраивания.
 */
export function injectEmbed(html: string, p: { partner: string; flat: string; lang: "ru" | "en" }): string {
  if (!SAFE.test(p.partner) || !SAFE.test(p.flat)) throw new Error("bad id");
  const cfg = JSON.stringify({ partner: p.partner, flat: p.flat, lang: p.lang });
  const inject = `<base href="/demo/"><script>window.__EMBED=${cfg};window.__sendFlat=${JSON.stringify(p.flat)};</script>`;
  const m = html.match(/<head[^>]*>/i);
  if (!m || m.index === undefined) throw new Error("no head");
  const at = m.index + m[0].length;
  return html.slice(0, at) + inject + html.slice(at);
}
