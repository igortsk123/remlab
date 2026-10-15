// ЛЕНТЫ ЗАМЕН ВИТРИНЫ → ВАРИАНТЫ ПРЕДМЕТА В /flat (план demo-05 п.9). Окно демо даёт заменить предмет из ленты своей роли
// (`tools/scout/flat215-demo/index.html:feedFor`), а в /flat у предмета была одна опция — «Варианты» открывали пустую полосу.
// Здесь та же лента и тот же фильтр по стилю; в /flat — ближайшие по размеру (место в расстановке уже выбрано под предмет).
// Чистые функции, без three.js.

/** Товар ленты витрины (`flat215_demo.py`: feeds[роль]). */
export type FeedItem = {
  name?: string;
  w?: number;
  d?: number;
  h?: number;
  price?: number;
  img?: string;
  url?: string;
  shop?: string;
  style?: string;
  styles?: string[];
  sid?: string;
  msid?: string;
  src?: string;
  pack?: number;
  yaw?: number;
};

/** Сколько вариантов на предмет (кроме текущего): полоса выбора в /flat — не каталог. */
export const FEED_LIMIT = 11;

/** Лента роли для стиля варианта — правило окна (`feedFor`): свои товары набора + товары, подходящие стилю; пусто — вся. */
export function feedForStyle(all: readonly FeedItem[], style: string | undefined): FeedItem[] {
  if (!style) return [...all];
  const mine = all.filter((p) => (p.src === "set" && (!p.style || p.style === style))
    || (p.src !== "set" && (p.styles ? p.styles.includes(style) : !p.style || p.style === style)));
  return mine.length ? mine : [...all];
}

/**
 * Варианты замены места: с моделью, фото и размерами, не тот же товар, ближайшие по ширине и глубине к месту.
 * `exclude` — ключ текущего товара (`sid` или название).
 */
export function alternatives(feed: readonly FeedItem[], place: { w: number; d: number }, exclude: Set<string>, limit = FEED_LIMIT): FeedItem[] {
  const seen = new Set<string>();
  return feed
    .filter((p) => p.msid && p.img && p.w && p.d && p.h && !exclude.has(p.sid ?? "") && !exclude.has(p.name ?? ""))
    .filter((p) => {
      const k = p.sid ?? p.name ?? "";
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .map((p) => ({ p, gap: Math.abs((p.w as number) - place.w) + Math.abs((p.d as number) - place.d) }))
    .sort((a, b) => a.gap - b.gap || (a.p.price ?? 0) - (b.p.price ?? 0))
    .slice(0, limit)
    .map(({ p }) => p);
}
