// ЛЕНТЫ ЗАМЕН ВИТРИНЫ → ВАРИАНТЫ ПРЕДМЕТА В /flat (план demo-05 п.9). Окно демо даёт заменить предмет из ленты своей роли
// (`tools/scout/flat215-demo/index.html:feedFor`), а в /flat у предмета была одна опция — «Варианты» открывали пустую полосу.
// Здесь та же лента и тот же фильтр по стилю; в /flat — ближайшие по размеру (место в расстановке уже выбрано под предмет),
// разные модели раньше цветов, диван — той же формы (demo-18 п.1).
// Чистые функции, без three.js.

/** Товар ленты витрины (`flat215_demo.py`: feeds[роль]). */
export type FeedItem = {
  name?: string;
  /** Английское название сборки (demo-31) — для британской маски английского демо. */
  name_en?: string;
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
  /** Подкраска цветового варианта (`flat215_demo.annotate_tint`). */
  tint?: number[];
  /** Диван: угловой (правило расстановщика `tools/scout/sofa_shape.py`); нет поля — прямой. */
  corner?: boolean;
  /** Угловой диван: оттоманка слева/справа названа в имени; нет поля — сторона любая (сцена зеркалит модель). */
  corner_left?: boolean;
};

/**
 * Место замены: размер, модель текущего товара (`msid`) и форма дивана из расстановки. Ковёр (`rug`, demo-18 п.2) ложится вдоль
 * длинной стороны места — сравниваем длинную с длинной; `minLong` — длинная сторона не короче дивана (контракт зонного ковра,
 * `tools/scout/demo_fill.py:rug_fits`).
 */
export type FeedPlace = { w: number; d: number; model?: string; corner?: boolean; cornerLeft?: boolean; rug?: boolean; minLong?: number };

const longShort = (w: number, d: number): [number, number] => [Math.max(w, d), Math.min(w, d)];

/** Расхождение размеров товара и места: сумма по сторонам; у ковра — длинная с длинной, короткая с короткой. */
function sizeGap(p: FeedItem, place: FeedPlace): number {
  if (!place.rug) return Math.abs((p.w as number) - place.w) + Math.abs((p.d as number) - place.d);
  const [a, b] = longShort(p.w as number, p.d as number);
  const [c, d] = longShort(place.w, place.d);
  return Math.abs(a - c) + Math.abs(b - d);
}

/** Предмет расстановки витрины — столько, сколько нужно месту замены. */
export type PlaceItem = { role?: string; w?: number; d?: number; corner?: boolean; corner_left?: boolean; sku?: { msid?: string } };

/**
 * Место замены предмета варианта — одно правило для моста /flat, отчёта сборки (`tools/flat3d/swap-report.mjs`) и теста 2.20:
 * у ковра — длинная сторона не короче дивана той же расстановки (`minLong`), у дивана — форма места.
 */
export function placeOf(it: PlaceItem, items: readonly PlaceItem[]): FeedPlace {
  const place: FeedPlace = { w: it.w ?? 0, d: it.d ?? 0, model: it.sku?.msid, corner: !!it.corner, cornerLeft: !!it.corner_left };
  if (!String(it.role ?? "").startsWith("ковёр")) return place;
  const sofa = items.find((x) => x.role === "диван")?.w;
  return { ...place, rug: true, ...(sofa ? { minLong: sofa } : {}) };
}

/** Сколько вариантов на предмет (кроме текущего): полоса выбора в /flat — не каталог. */
export const FEED_LIMIT = 11;

/**
 * Лента роли для стиля варианта — правило окна (`feedFor`): товары, подходящие стилю (`styles`: стиль своего набора и стили, где
 * товар прошёл отбор пула — `flat215_demo.glue`); товар чужого набора без балла этого стиля не виден; пусто — вся.
 */
export function feedForStyle(all: readonly FeedItem[], style: string | undefined): FeedItem[] {
  if (!style) return [...all];
  const mine = all.filter((p) => (p.styles ? p.styles.includes(style) : !p.style || p.style === style));
  return mine.length ? mine : [...all];
}

/**
 * Замена той же формы (demo-18 п.1): форму места сцена берёт из расстановки, а не из товара (`fromDemo.ts`), поэтому прямой
 * диван на угловом месте рисовался бы углом. Угловой с названной стороной — только на место с той же стороной.
 */
export function sameShape(p: FeedItem, place: FeedPlace): boolean {
  if (!!p.corner !== !!place.corner) return false;
  return !place.corner || p.corner_left === undefined || p.corner_left === !!place.cornerLeft;
}

/**
 * Все годные замены места по порядку: с моделью, фото и размерами, той же формы, не тот же товар. Порядок — ближайшие по
 * ширине и глубине, но СПЕРВА по одному товару на модель (`msid`), потом цвета тех же моделей и текущей (приёмка 16.10
 * п.11а, demo-18 п.1: одиннадцать цветов одной модели выглядели как «замена не сработала»).
 * `exclude` — ключ текущего товара (`sid` или название).
 */
export function candidates(feed: readonly FeedItem[], place: FeedPlace, exclude: Set<string>): FeedItem[] {
  const seen = new Set<string>();
  const near = feed
    .filter((p) => p.msid && p.img && p.w && p.d && p.h && !exclude.has(p.sid ?? "") && !exclude.has(p.name ?? "") && sameShape(p, place)
      && (!place.minLong || Math.max(p.w, p.d) >= place.minLong))
    .filter((p) => {
      const k = p.sid ?? p.name ?? "";
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .map((p) => ({ p, gap: sizeGap(p, place) }))
    .sort((a, b) => a.gap - b.gap || (a.p.price ?? 0) - (b.p.price ?? 0))
    .map(({ p }) => p);
  const models = new Set<string>(place.model ? [place.model] : []);
  const first: FeedItem[] = [];
  const colours: FeedItem[] = [];
  for (const p of near) {
    if (models.has(p.msid as string)) colours.push(p);
    else {
      models.add(p.msid as string);
      first.push(p);
    }
  }
  return [...first, ...colours];
}

/** Варианты замены места — первые `limit` годных (`candidates`): полоса выбора в /flat. */
export function alternatives(feed: readonly FeedItem[], place: FeedPlace, exclude: Set<string>, limit = FEED_LIMIT): FeedItem[] {
  return candidates(feed, place, exclude).slice(0, limit);
}
