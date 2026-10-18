// Живой demo-data.json витрины (план b2b-02/b2b-06): одна загрузка на 5 минут на процесс.
// Нужен серверу, чтобы НЕ верить тексту со страницы: имя варианта и товаров в сигнале менеджеру
// берётся, только если оно есть в данных витрины (иначе любой с ссылкой писал бы менеджеру что угодно).

export type DemoNames = { variants: Set<string>; items: Set<string> };
type Raw = { variants?: { id?: string; style?: string; style_id?: string; room_id?: string; title?: string; items?: { sku?: { name?: string } }[] }[];
  sets?: unknown; variant_aliases?: Record<string, string> };

/** id стиля витрины для адреса и корзины (demo-16): данные сборки (`style_id`), у старой сборки — по названию стиля. */
export const STYLE_IDS: Record<string, string> = { сканди: "scandi", современный: "modern", минимализм: "minimal", лофт: "loft",
  неоклассика: "neoclassic", джапанди: "japandi" };

/** Стиль и комната опубликованного варианта витрины; устаревший номер — по истории номеров (`variant_aliases`, стиль). */
export function variantKey(raw: Raw | null, variantId: string): { styleId: string; roomId: string } | null {
  const vs = raw?.variants ?? [];
  const sid = (v: NonNullable<Raw["variants"]>[number]) => v.style_id || STYLE_IDS[String(v.style ?? "").trim().toLowerCase()] || "";
  const v = vs.find((x) => x.id === variantId);
  if (v) return { styleId: sid(v), roomId: v.room_id || "living" };
  const st = raw?.variant_aliases?.[variantId];
  const a = st ? vs.find((x) => x.style === st) : undefined;
  return a ? { styleId: sid(a), roomId: a.room_id || "living" } : null;
}

const TTL_MS = 5 * 60_000;
const cache = new Map<string, { at: number; data: Raw | null }>();

export function absoluteUrl(src: string): string {
  if (/^https?:\/\//.test(src)) return src;
  const base = process.env.APP_URL || "https://remont-lab.online";
  return `${base.replace(/\/$/, "")}${src.startsWith("/") ? "" : "/"}${src}`;
}

export async function loadDemoRaw(src: string, now = Date.now()): Promise<Raw | null> {
  const url = absoluteUrl(src);
  const hit = cache.get(url);
  if (hit && now - hit.at < TTL_MS) return hit.data;
  let data: Raw | null = null;
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8_000) });
    data = r.ok ? ((await r.json()) as Raw) : null;
  } catch {
    data = null;
  }
  // неудачу помним 30 секунд, а не 5 минут: одна осечка витрины не должна давать «попробуйте позже» надолго
  cache.set(url, { at: data ? now : now - TTL_MS + 30_000, data });
  return data;
}

const norm = (s: string) => s.trim().toLowerCase();

export function demoNames(raw: Raw | null): DemoNames | null {
  if (!raw?.variants) return null;
  const variants = new Set<string>();
  const items = new Set<string>();
  for (const v of raw.variants) {
    for (const t of [v.style, v.title]) if (t) variants.add(norm(t));
    for (const it of v.items ?? []) if (it.sku?.name) items.add(norm(it.sku.name));
  }
  // замены берутся из лент товаров (`sets`/`feeds`): собираем все имена, что встречаются в данных
  const walk = (x: unknown): void => {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") {
      const o = x as Record<string, unknown>;
      if (typeof o.name === "string" && (o.price !== undefined || o.url !== undefined)) items.add(norm(o.name));
      Object.values(o).forEach(walk);
    }
  };
  walk(raw);
  return { variants, items };
}

/** Оставить только то, что есть в данных витрины. Нет данных — текста нет вовсе (сумма остаётся). */
export function keepKnown(names: DemoNames | null, variant?: string, items?: string[]): { variant?: string; items?: string[] } {
  if (!names) return { variant: undefined, items: undefined };
  return {
    variant: variant && names.variants.has(norm(variant)) ? variant : undefined,
    items: (items ?? []).filter((n) => names.items.has(norm(n))).slice(0, 10),
  };
}
