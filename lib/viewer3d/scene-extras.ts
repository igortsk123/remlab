// ТЕЛЕВИЗОР И НАСТОЛЬНЫЙ ДЕКОР — ТЕМ ЖЕ ПРАВИЛОМ, ЧТО СЕРВЕРНЫЙ КАДР (план demo-05 п.9).
// Живая сцена и /flat не рисовали ни ТВ над тумбой, ни вазу на столике, а серверный кадр рисовал (14.10): покупатель видел
// две разные комнаты. Здесь — порт 1:1 правил `tools/scout/draft_render.py` (`tv_spec`, `_hung_stand`, авто-ТВ в
// `scene_from_request`, `decor_layout`); общий эталон `tests/fixtures/scene-extras-golden.json` собирает
// `tools/assets/scene_extras_golden.py` тем же серверным кодом, и TS-тест обязан с ним совпасть.
// Чистые функции, без three.js.

/** Расстояние до экрана → диагональ (дюймы); таблица владельца 01.09 (`draft_render.TV_BY_DIST_CM`). */
export const TV_BY_DIST_CM: readonly (readonly [number, number])[] = [[150, 43], [200, 50], [250, 55], [300, 65], [350, 75], [Infinity, 85]];
/** Центр экрана на уровне глаз сидящего — норма установки. */
export const TV_SEAT_EYE_CM = 105;
/** Выше этого центра шею задирают: телевизор вешают, а не ставят. */
export const TV_MAX_CENTER_CM = 125;
/** Экран не шире этой доли тумбы (владелец 01.09: «не более длины тв-тумбы», и с полями). */
export const TV_MAX_STAND_FRAC = 0.9;
/** Низ подвесной тумбы от пола. */
export const TV_STAND_HANG_CM = 40;

export interface TvSpec {
  inch: number;
  wCm: number;
  hCm: number;
  /** Отметка низа экрана от пола. */
  elevCm: number;
  how: "на тумбе" | "на стене";
}

// до 0,1 как Python `round(x, 1)`: по точному десятичному значению числа, ровная половина — к чётной цифре
// (×10 и Math.round расходились на 95,25; toFixed на ровной половине 101,25 даёт 101,3, Python — 101,2)
const round1 = (v: number): number => {
  const exact = Math.abs(v).toFixed(60);
  const tail = exact.slice(exact.indexOf(".") + 2);
  if (/^50*$/.test(tail)) {
    const ten = Math.trunc(Math.abs(v) * 10);
    return (Math.sign(v) * (ten % 2 === 0 ? ten : ten + 1)) / 10;
  }
  return Number(v.toFixed(1));
};
// округление как у Python (`round`, банковское на .5) — иначе дюймы на границе разошлись бы с серверным кадром
const pyRound = (v: number): number => {
  const f = Math.floor(v);
  const d = v - f;
  if (Math.abs(d - 0.5) > 1e-9) return Math.round(v);
  return f % 2 === 0 ? f : f + 1;
};

/** Размер и подвес телевизора (`draft_render.tv_spec`). */
export function tvSpec(distCm: number, standWCm: number, standHCm: number, hung = false): TvSpec {
  let inch = TV_BY_DIST_CM.find(([lim]) => distCm < lim)![1];
  const diag = inch * 2.54;
  // корни — как в Python (`** 0.5`), не Math.hypot: последний знак у них разный, а он решает округление 101,25
  const k169 = Math.sqrt(16 ** 2 + 9 ** 2);
  let w = (diag * 16) / k169;
  let h = (diag * 9) / k169;
  const cap = standWCm * TV_MAX_STAND_FRAC;
  if (cap > 0 && w > cap) {
    const k = cap / w;
    w *= k;
    h *= k;
    inch = pyRound(Math.sqrt(w ** 2 + h ** 2) / 2.54);
  }
  // над подвесной тумбой телевизор не стоит никогда — только на стене (владелец 02.09)
  if (!hung && standHCm + h / 2 <= TV_MAX_CENTER_CM) {
    return { inch, wCm: round1(w), hCm: round1(h), elevCm: round1(standHCm), how: "на тумбе" };
  }
  const elev = Math.max(standHCm + 10, TV_SEAT_EYE_CM - h / 2);
  return { inch, wCm: round1(w), hCm: round1(h), elevCm: round1(elev), how: "на стене" };
}

/** Подвесная тумба — по названию товара (`draft_render._hung_stand`; высота признаком не является, урок 02.09). */
export function isHungStand(name: string | undefined, hung?: boolean): boolean {
  if (hung !== undefined) return hung;
  const n = (name ?? "").toLowerCase();
  return ["подвесн", "навесн", "настенн"].some((k) => n.includes(k));
}

/** Роль без номера экземпляра: «стул 2» → «стул», «стол обеденный» — целиком. */
export const baseRole = (role: string | undefined): string => String(role ?? "").replace(/\s+\d+$/, "").trim();

export interface ExtraItem {
  role?: string;
  x?: number;
  y?: number;
  rot?: number;
  w?: number;
  d?: number;
  h?: number;
  elev?: number;
  hung?: boolean;
  /** Название товара: у запроса страницы — в самом предмете, у варианта витрины — в `sku`. */
  name?: string;
  sku?: { name?: string };
}

export interface AutoTv {
  x: number;
  y: number;
  rot: number;
  wCm: number;
  dCm: number;
  hCm: number;
  elevCm: number;
  hung: boolean;
  inch: number;
  how: TvSpec["how"];
  /** Подъём самой тумбы (подвесная висит на 40 см) — `undefined`, если тумба стоит на полу. */
  standElevCm?: number;
}

/**
 * Авто-ТВ над тумбой (`draft_render.scene_from_request`): есть «тв-тумба» и нет своего «тв» → телевизор по расстоянию до дивана
 * (иначе кресла, иначе 300 см). Подвесная тумба поднимается на 40 см, телевизор — всегда на стене, панель 8 см; на тумбе —
 * с подставкой, глубина 22 см.
 */
export function autoTv(items: readonly ExtraItem[]): AutoTv | null {
  const stand = items.find((p) => baseRole(p.role) === "тв-тумба" && p.w);
  if (!stand || items.some((p) => baseRole(p.role) === "тв")) return null;
  const seat = items.find((p) => baseRole(p.role) === "диван") ?? items.find((p) => baseRole(p.role) === "кресло");
  const sx = stand.x ?? 0;
  const sy = stand.y ?? 0;
  const dist = seat ? Math.sqrt(((seat.x ?? 0) - sx) ** 2 + ((seat.y ?? 0) - sy) ** 2) : 300;
  const hung = isHungStand(stand.name ?? stand.sku?.name, stand.hung);
  let top = stand.h || 45;
  let standElevCm: number | undefined;
  if (hung) {
    standElevCm = TV_STAND_HANG_CM;
    top = TV_STAND_HANG_CM + top;
  }
  const s = tvSpec(dist, stand.w as number, top, hung);
  return { x: sx, y: sy, rot: stand.rot ?? 0, wCm: s.wCm, dCm: hung ? 8 : 22, hCm: s.hCm, elevCm: s.elevCm, hung,
    inch: s.inch, how: s.how, ...(standElevCm !== undefined ? { standElevCm } : {}) };
}

/** Опоры настольного декора — буквально по словам владельца 08.09: журнальный столик, иначе обеденный стол. */
export const DECOR_SUPPORTS = ["столик", "стол обеденный"] as const;
const DECOR_EDGE_CM = 4;
const DECOR_GAP_CM = 6;

export interface DecorIn {
  role?: string;
  sku?: { w?: number; d?: number; h?: number; name?: string; msid?: string };
}

export interface DecorPlaced<T extends DecorIn = DecorIn> {
  decor: T;
  x: number;
  y: number;
  rot: number;
  elev: number;
  w: number;
  d: number;
  h: number;
}

/**
 * Куда встанет настольный декор (`draft_render.decor_layout`) → (в сцене, не в сцене). Ряд по длинной оси опоры с отступом
 * 4 см от края и зазором 6 см; не влезло или опора без габаритов — предмет не рисуется (размер не придумываем, Р1).
 */
export function decorLayout<T extends DecorIn>(items: readonly ExtraItem[], decorAll: readonly T[]): { placed: DecorPlaced<T>[]; rest: T[] } {
  const sized = (d: T): boolean => !!(d.sku?.w && d.sku?.d && d.sku?.h);
  const decor = decorAll.filter(sized);
  const rest = decorAll.filter((d) => !sized(d));
  if (!decor.length) return { placed: [], rest };
  for (const role of DECOR_SUPPORTS) {
    const sup = items.find((it) => baseRole(it.role) === role && it.w && it.d && it.h);
    if (!sup) continue;
    const span = (sup.w as number) - 2 * DECOR_EDGE_CM;
    const deep = (sup.d as number) - 2 * DECOR_EDGE_CM;
    const total = decor.reduce((t, d) => t + (d.sku!.w as number), 0) + DECOR_GAP_CM * (decor.length - 1);
    if (total > span || Math.max(...decor.map((d) => d.sku!.d as number)) > deep) continue;
    const a = ((sup.rot ?? 0) * Math.PI) / 180;
    const elev = (sup.elev ?? 0) + (sup.h as number);
    let off = -total / 2;
    const placed = decor.map((d) => {
      const w = d.sku!.w as number;
      const k = off + w / 2;
      off += w + DECOR_GAP_CM;
      return { decor: d, x: (sup.x ?? 0) + k * Math.cos(a), y: (sup.y ?? 0) - k * Math.sin(a), rot: sup.rot ?? 0, elev,
        w, d: d.sku!.d as number, h: d.sku!.h as number };
    });
    return { placed, rest };
  }
  return { placed: [], rest: [...rest, ...decor] };
}
