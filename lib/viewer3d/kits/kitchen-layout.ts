// Раскладка кухни — ЧИСТАЯ функция (без three.js): где нижний ряд, колонны, модули, мойка, варочная, холодильник,
// вентканал, второе плечо Г и остров. Её рисует `kits/kitchen.ts` и проверяет `kits/kitchen-checks.ts` — кадр и нормы
// считаются по одним и тем же числам (план onb-09: без координат точек треугольник не проверить).
//
// ОСИ — как у набора: начало — центр линии на полу, X — вдоль линии, Z — от задней стены (−D/2) в комнату (+D/2).
// ПУТЬ ВДОЛЬ РЯДА `s`, см: 0…W — основная линия слева направо. У Г путь продолжается по второму плечу от угла: больше W
// (угол в конце линии) или меньше 0 (угол в начале), модуль за модулем вдоль боковой стены.

import { splitUnits } from "@/lib/viewer3d/kits/common";

export interface KitchenSpec {
  level: "base" | "practical" | "comfort" | "premium";
  features: string[];
  doorMaterialId?: string;
  /** Фасад верхних шкафов, если он другой (двухцветная кухня: низ «бетон», верх «дуб»); нет — как низ. */
  doorUpperMaterialId?: string;
  worktopMaterialId?: string;
  splashbackMaterialId?: string;
  widthCm: number;
  depthCm: number;
  /** Глубина комнаты от задней стены линии до противоположной, см. Остров ставится только если он влезает. */
  roomDepthCm?: number;
  /**
   * С какого конца линии ставить колонны до потолка. Их место — ДАЛЬШЕ ОТ ДВЕРИ: у входа
   * они перекрывают вид на всю кухню (кадр 29.09) и мешают пройти.
   */
  columnsAt?: "start" | "end";
  /** Форма: прямая (по умолчанию) или Г — второе плечо вдоль боковой стены. Остров — отдельно, признаком `island`. */
  shape?: "straight" | "corner";
  /** Длина второго плеча Г от задней стены, см (вместе с углом). По умолчанию `CORNER_LEG_CM`. */
  cornerLegCm?: number;
  /** У какого конца линии угол. По умолчанию — напротив колонн: колонна в углу не открывается. */
  cornerAt?: "start" | "end";
  /**
   * Ряд на всю ширину (`widthCm`) — так у примера из магазина: его длина паспортная. Нет — доля стены по уровню, как
   * у вариантов застройщика (Base 62 %, Practical 84 %). Г всегда во всю ширину: иначе ряд не дойдёт до угла.
   */
  fullRun?: boolean;
  /** Центр мойки на пути вдоль ряда, см (может стоять на втором плече Г). Нет — середина линии. */
  sinkAtCm?: number;
  /** Центр варочной на основной линии, см. Нет — у вентканала, если он задан, иначе через модуль от мойки. */
  hobAtCm?: number;
  /** Отдельно стоящий холодильник (не в колонне): центр на оси ряда, см; может быть за краем линии (< 0 или > W). */
  fridgeAtCm?: number;
  /** Вентканал на стене за рядом, см по пути. Вытяжка — к нему; варочная тоже, если `hobAtCm` не задан. */
  ventAtCm?: number;
  /**
   * Ширины нижних модулей основной линии слева направо, см (без углового квадрата Г): из паспорта или подбор из ряда
   * `MODULE_SERIES_CM` (`kits/kitchen-modules.ts`). Нет — ряд делится поровну (~60 см), как у вариантов застройщика.
   * Не хватило до длины ряда — остаток < 40 см закрывает добор (панель без ручки), ≥ 40 — делится поровну.
   */
  modulesCm?: number[];
  /** То же для второго плеча Г — от угла к торцу. */
  legModulesCm?: number[];
  /**
   * Ширины верхних шкафов основной линии слева направо, см, БЕЗ места под вытяжку: вытяжка (60) — точно над варочной,
   * модули по порядку слева и справа от неё. Не сходятся ровно — верх делится поровну, как без них.
   */
  upperModulesCm?: number[];
  /** `fridgeAtCm` — допущение (холодильника нет в составе, место ещё не задала посадка): проверки помечают это. */
  fridgeAssumed?: boolean;
  /** Плечо Г — полуостров: без верхних шкафов и фартука, торец и спина открыты в комнату (у Wickes на фото). */
  peninsula?: boolean;
}

/**
 * СОСТАВ ПО УРОВНЮ: с ценой должна расти ФУНКЦИЯ, а не только цвет фасадов (владелец 29.09: «кухня когда меняешь на
 * премиум лучше побогаче… по функциональнее»). Base — короткая линия и открытая полка; Practical — линия почти во всю
 * стену и верхние шкафы; Comfort — полная линия + колонна до потолка; Premium — две колонны, полки и подсветка.
 * Острова в уровне нет (onb-09, Codex 05.11): в узкой кухне его не поставить — он только признаком `island`.
 */
export const KITCHEN_LEVELS = {
  base: { run: 0.62, uppers: 0, columns: 0, shelves: false, lighting: false },
  practical: { run: 0.84, uppers: 0.62, columns: 0, shelves: false, lighting: false },
  comfort: { run: 1.0, uppers: 1.0, columns: 1, shelves: true, lighting: true },
  premium: { run: 1.0, uppers: 1.0, columns: 2, shelves: true, lighting: true },
} as const;

export const COLUMN_W = 60;
/** Место под вытяжку в ряду верхних шкафов, см. */
export const HOOD_W = 60;
export const UPPER_D = 35;
/** Второе плечо Г по умолчанию, см от задней стены — оценка (у паспортов магазина длины плеча нет). */
export const CORNER_LEG_CM = 150;
/** Рабочий проход перед линией (один повар), см — NKBA, ADR-0330 п.7; по нему ставится остров. */
export const WORK_AISLE_CM = 107;
/** Проход за островом, см — NKBA (walkway), ADR-0330 п.7. */
export const WALKWAY_CM = 91;
const ISLAND_D = 90;

export interface Pt {
  x: number;
  z: number;
}

export interface KitchenSlot {
  /** Центр модуля в его ряду: у основной линии — X набора, у плеча — координата вдоль плеча (кадр плеча, см. `leg`). */
  along: number;
  w: number;
  /** Путь вдоль ряда, см (центр модуля). */
  s: number;
  leg: boolean;
  /** Середина фасада в осях набора — отсюда меряют треугольник (NKBA: «center-front»). */
  front: Pt;
}

export interface KitchenLeg {
  at: "start" | "end";
  /** Длина плеча от задней стены, см. */
  lengthCm: number;
  /** Модули за углом, см (`lengthCm − D`). */
  runCm: number;
  /** Кадр плеча: начало — край основной линии у угла, X плеча — вдоль боковой стены, лицо — в комнату. */
  origin: Pt;
  yaw: number;
  /** Где кадр плеча начинается и кончается по своей X (у угла в начале линии — отрицательные). */
  x0: number;
  x1: number;
}

export interface KitchenLayout {
  W: number;
  D: number;
  front: number;
  back: number;
  level: (typeof KITCHEN_LEVELS)[KitchenSpec["level"]];
  columns: { x: number; fridge: boolean }[];
  tallW: number;
  colX0: number;
  /** Нижний ряд основной линии (вместе с угловым квадратом у Г). */
  runX0: number;
  runW: number;
  /** Угловой квадрат D×D на основной линии (у Г): корпус без фасада, его закрывает плечо. */
  corner: { x0: number; x1: number } | null;
  /** Модули с фасадами: сначала основная линия, затем плечо. */
  slots: KitchenSlot[];
  /** Доборы — узкие панели без ручки, где модули ряда не дошли до его длины (`along` — центр, как у модуля). */
  fillers: { along: number; w: number; leg: boolean }[];
  /** Индексы в `slots`; −1 — нет. */
  sink: number;
  hob: number;
  dish: number;
  oven: number;
  wine: number;
  /** Духовка во второй колонне (Premium); иначе — под варочной в нижнем ряду. */
  ovenInColumn: boolean;
  /** Верхние шкафы основной линии: ширина от `runX0`, см (0 — их нет). */
  uppersW: number;
  /** Верхние шкафы по `upperModulesCm` (центр по X и ширина); null — паспортных нет или не сошлись: верх поровну. */
  upperSlots: { x: number; w: number }[] | null;
  leg: KitchenLeg | null;
  island: { x: number; z: number; w: number; d: number } | null;
  /** Остров просили, но он не влезает — барная стойка на торце линии. */
  bar: boolean;
  points: { sink: Pt | null; hob: Pt | null; fridge: Pt | null; vent: Pt | null };
}

/** Точка на пути вдоль ряда: `edge` — лицо модулей (где стоит повар) или стена за ними (вентканал). */
function pathPoint(lay: Pick<KitchenLayout, "W" | "D" | "front" | "back" | "leg">, s: number, edge: "front" | "wall"): Pt {
  const { W, D, front, back, leg } = lay;
  if (leg && leg.at === "end" && s > W) return { x: edge === "front" ? W / 2 - D : W / 2, z: front + (s - W) };
  if (leg && leg.at === "start" && s < 0) return { x: edge === "front" ? -W / 2 + D : -W / 2, z: front - s };
  return { x: -W / 2 + s, z: edge === "front" ? front : back };
}

/** Ширины модулей ряда длиной `len`: заданные (пока влезают), остаток < 40 — добор, ≥ 40 — поровну; не заданы — поровну. */
function fitModules(len: number, given: number[] | undefined): { widths: number[]; filler: number } {
  if (!given?.length) return { widths: splitUnits(len, 60), filler: 0 };
  const widths: number[] = [];
  let sum = 0;
  for (const w of given) {
    if (sum + w > len + 0.01) break;
    widths.push(w);
    sum += w;
  }
  const rest = len - sum;
  if (rest >= 40) return { widths: [...widths, ...splitUnits(rest, 60)], filler: 0 };
  return { widths, filler: rest > 0.5 ? rest : 0 };
}

/**
 * Верх по ширинам: отрезки слева и справа от вытяжки (или весь ряд без неё) заполняются модулями по порядку; каждый отрезок
 * должен закрыться ровно (±0,5 см), и все модули — встать. Иначе null.
 */
function fitUppers(x0: number, len: number, hoodX: number | null, widths: number[]): { x: number; w: number }[] | null {
  const segs: [number, number][] = hoodX === null ? [[x0, x0 + len]] : [[x0, hoodX - HOOD_W / 2], [hoodX + HOOD_W / 2, x0 + len]];
  if (segs.some(([a, b]) => b < a - 0.5)) return null;
  const out: { x: number; w: number }[] = [];
  let i = 0;
  for (const [a, b] of segs) {
    let cur = a;
    while (cur < b - 0.5) {
      const w = widths[i];
      if (w === undefined) return null;
      out.push({ x: cur + w / 2, w });
      cur += w;
      i += 1;
    }
    if (Math.abs(cur - b) > 0.5) return null;
  }
  return i === widths.length ? out : null;
}

function nearest(slots: KitchenSlot[], s: number, allowed: (i: number) => boolean): number {
  let best = -1;
  slots.forEach((sl, i) => {
    if (!allowed(i)) return;
    if (best < 0 || Math.abs(sl.s - s) < Math.abs((slots[best] as KitchenSlot).s - s)) best = i;
  });
  return best;
}

export function kitchenLayout(spec: KitchenSpec): KitchenLayout {
  const W = spec.widthCm;
  const D = spec.depthCm;
  const front = D / 2;
  const back = -D / 2;
  const has = (f: string): boolean => spec.features.includes(f);
  const level = KITCHEN_LEVELS[spec.level];

  const nCols = has("tall-unit") ? Math.max(1, level.columns) : level.columns;
  const tallW = nCols * COLUMN_W;
  const atEnd = (spec.columnsAt ?? "start") === "end";
  const corner = spec.shape === "corner";
  const full = spec.fullRun === true || corner;
  const runW = full ? W - tallW : Math.max(120, (W - tallW) * level.run);
  const runX0 = atEnd ? -W / 2 : -W / 2 + tallW; // ряд слева или справа от колонн
  const colX0 = atEnd ? -W / 2 + runW : -W / 2; // начало блока колонн
  const columns = Array.from({ length: nCols }, (_, c) => ({ x: colX0 + COLUMN_W / 2 + c * COLUMN_W, fridge: c === 0 && has("fridge") }));

  // Г: угол — напротив колонн (колонна в углу не открывается), плечо — вдоль боковой стены
  let leg: KitchenLeg | null = null;
  let cornerBox: KitchenLayout["corner"] = null;
  if (corner) {
    const wanted = spec.cornerAt ?? (atEnd ? "start" : "end");
    const at = nCols > 0 ? (atEnd ? "start" : "end") : wanted;
    const lengthCm = Math.max(D + 40, spec.cornerLegCm ?? CORNER_LEG_CM);
    const runCm = lengthCm - D;
    leg = at === "end"
      ? { at, lengthCm, runCm, origin: { x: W / 2 - D / 2, z: front }, yaw: -Math.PI / 2, x0: 0, x1: runCm }
      : { at, lengthCm, runCm, origin: { x: -W / 2 + D / 2, z: front }, yaw: Math.PI / 2, x0: -runCm, x1: 0 };
    cornerBox = at === "end" ? { x0: runX0 + runW - D, x1: runX0 + runW } : { x0: runX0, x1: runX0 + D };
  }

  // модули основной линии (без углового квадрата), затем плеча
  const slots: KitchenSlot[] = [];
  const fillers: KitchenLayout["fillers"] = [];
  const mainX0 = cornerBox && leg?.at === "start" ? runX0 + D : runX0;
  const mainW = cornerBox ? runW - D : runW;
  let cursor = mainX0;
  const mainRow = fitModules(mainW, spec.modulesCm);
  for (const w of mainRow.widths) {
    const x = cursor + w / 2;
    slots.push({ along: x, w, s: x + W / 2, leg: false, front: { x, z: front } });
    cursor += w;
  }
  if (mainRow.filler) fillers.push({ along: cursor + mainRow.filler / 2, w: mainRow.filler, leg: false });
  const mainN = slots.length;
  if (leg) {
    let u = 0;
    const legRow = fitModules(leg.runCm, spec.legModulesCm);
    for (const w of legRow.widths) {
      const c = u + w / 2;
      const s = leg.at === "end" ? W + c : -c;
      slots.push({ along: leg.at === "end" ? c : -c, w, s, leg: true, front: pathPoint({ W, D, front, back, leg }, s, "front") });
      u += w;
    }
    if (legRow.filler) {
      const c = u + legRow.filler / 2;
      fillers.push({ along: leg.at === "end" ? c : -c, w: legRow.filler, leg: true });
    }
  }
  const isMain = (i: number): boolean => i >= 0 && i < mainN;

  // мойка и варочная: заданы точками — к ближайшему модулю; нет — как раньше (мойка в середине, варочная через модуль)
  let sink = spec.sinkAtCm !== undefined ? nearest(slots, spec.sinkAtCm, () => true) : Math.min(mainN - 1, Math.max(0, Math.floor(mainN / 2)));
  let hob: number;
  if (spec.hobAtCm !== undefined) hob = nearest(slots, spec.hobAtCm, (i) => isMain(i) && i !== sink);
  else if (spec.ventAtCm !== undefined) hob = nearest(slots, spec.ventAtCm, isMain);
  else hob = Math.max(0, sink - 2 >= 0 ? sink - 2 : sink + 2);
  if (spec.sinkAtCm === undefined && spec.hobAtCm === undefined && spec.ventAtCm !== undefined && Math.abs(sink - hob) < 2) {
    // варочная ушла к вентканалу — мойку отодвигаем на модуль, иначе между ними нет рабочего места
    const mid = (mainN - 1) / 2;
    const free = slots.map((_, i) => i).filter((i) => isMain(i) && Math.abs(i - hob) >= 2);
    if (free.length) sink = free.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a));
  }
  const sameRun = (i: number): boolean => i >= 0 && i < slots.length && (slots[i] as KitchenSlot).leg === (slots[sink] as KitchenSlot | undefined)?.leg;
  const custom = spec.sinkAtCm !== undefined || spec.hobAtCm !== undefined || spec.ventAtCm !== undefined;
  let dish = -1;
  let wine = -1;
  if (!custom) {
    // прежние правила — кадры старых вариантов не меняются
    dish = has("dishwasher") ? Math.min(mainN - 1, sink + 1) : -1;
    wine = has("wine-cooler") ? Math.max(0, sink - 1) : -1;
  } else {
    const nextTo = (skip: number[]): number => [sink + 1, sink - 1].find((i) => sameRun(i) && i !== hob && !skip.includes(i)) ?? -1;
    if (has("dishwasher")) dish = nextTo([]);
    if (has("wine-cooler")) wine = nextTo([dish]);
  }
  // ДУХОВКА: во второй колонне (Premium), иначе под варочной — колонна под холодильник духовку не прячет (onb-09)
  const ovenInColumn = has("oven") && nCols >= 2;
  const oven = has("oven") && !ovenInColumn ? Math.max(0, hob) : -1;

  const wantUppers = level.uppers > 0 || has("uppers");
  const uppersW = !wantUppers ? 0 : full ? runW : runW * Math.max(level.uppers, has("uppers") ? 0.62 : 0);
  const hobSlot = slots[hob];
  const hoodX = has("hood") && hobSlot ? hobSlot.along : null;
  const upperSlots = spec.upperModulesCm?.length && uppersW > 0 ? fitUppers(runX0, uppersW, hoodX, spec.upperModulesCm) : null;

  // ОСТРОВ ТОЛЬКО ЕСЛИ ВЛЕЗАЕТ: перед линией рабочий проход, за островом — проход (нормы ADR-0330 п.7).
  // В кухне глубиной 1,8 м он упирался в противоположную стену (кадр 29.09).
  const roomDepth = spec.roomDepthCm ?? D * 3;
  const wantIsland = has("island");
  const islandFits = roomDepth >= D + WORK_AISLE_CM + ISLAND_D + WALKWAY_CM;
  const iw = Math.min(180, W * 0.6);
  const island = wantIsland && islandFits ? { x: 0, z: front + WORK_AISLE_CM + ISLAND_D / 2, w: iw, d: ISLAND_D } : null;

  const base = { W, D, front, back, leg };
  const at = (i: number): Pt | null => (slots[i] ? (slots[i] as KitchenSlot).front : null);
  const fridgeCol = columns.find((c) => c.fridge);
  const points = {
    sink: at(sink),
    hob: has("hob") ? at(hob) : null,
    fridge: fridgeCol ? { x: fridgeCol.x, z: front } : spec.fridgeAtCm !== undefined ? pathPoint(base, spec.fridgeAtCm, "front") : null,
    vent: spec.ventAtCm !== undefined ? pathPoint(base, spec.ventAtCm, "wall") : null,
  };

  return {
    W, D, front, back, level, columns, tallW, colX0, runX0, runW, corner: cornerBox, slots, fillers,
    sink, hob, dish, oven, wine, ovenInColumn, uppersW, upperSlots, leg, island, bar: wantIsland && !islandFits, points,
  };
}
