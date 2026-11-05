// Проверки кухни по нормам — ЧИСТЫЕ функции над раскладкой `kitchen-layout.ts` (план onb-09, ADR-0330 п.7):
// рабочий треугольник «мойка — варочная — холодильник» и проходы. Причина отказа — словами, для отчёта посадки.
// Нормы продуктовые (NKBA Kitchen Planning Guidelines 2022, https://kb.nkba.org/uploads/2022/05/Kitchen-Planning-Guidelines.pdf):
// сторона треугольника 120–270 см, сумма ≤ 790 см; рабочий проход 107 см (один повар) / 122 см (двое), проход 91 см.
// Вытяжка у вентканала — ПРЕДУПРЕЖДЕНИЕ, не отказ: порог 300 см по стене, НОРМА НЕ ПОДТВЕРЖДЕНА (ведущий 05.11, T-20261105-18) —
// гипотеза до данных застройщика (вентканала на схеме №180 нет); длинный короб к каналу возможен, он только хуже тянет.

import { WALKWAY_CM, kitchenLayout, type KitchenLayout, type KitchenSlot, type KitchenSpec, type Pt } from "@/lib/viewer3d/kits/kitchen-layout";

export const KITCHEN_NORMS = {
  triangleSideMinCm: 120,
  triangleSideMaxCm: 270,
  triangleSumMaxCm: 790,
  aisleOneCookCm: 107,
  aisleTwoCooksCm: 122,
  walkwayCm: WALKWAY_CM,
  /** НОРМА НЕ ПОДТВЕРЖДЕНА: гипотеза, превышение — предупреждение (`warnings`), не причина отказа. */
  ventMaxCm: 300,
  /** Модуль под варочной — не уже 60 (под ней духовка 60), под мойкой — не уже 45 (чаша и сифон). */
  hobModuleMinCm: 60,
  sinkModuleMinCm: 45,
} as const;

export interface TriangleCheck {
  /** null — треугольник не определён (нет одной из точек): это не «нарушение», а «нечего мерить». */
  ok: boolean | null;
  sides: { sinkHob: number; hobFridge: number; fridgeSink: number } | null;
  sumCm: number | null;
  problems: string[];
}

export interface AisleCheck {
  where: "front" | "behind-island" | "leg-end";
  gapCm: number;
  needCm: number;
  ok: boolean;
}

export interface KitchenReport {
  ok: boolean;
  triangle: TriangleCheck;
  aisles: AisleCheck[];
  /** `ok: false` — вытяжка дальше порога: это предупреждение, `ok` отчёта от него не зависит. */
  vent: { distanceCm: number; ok: boolean } | null;
  problems: string[];
  /** Замечания без отказа: сейчас — далёкий вентканал (порог — гипотеза). */
  warnings: string[];
}

const dist = (a: Pt, b: Pt): number => Math.round(Math.hypot(a.x - b.x, a.z - b.z));

/** Треугольник по трём точкам (середины фасадов). Любой отсутствующей точки — `ok: null` с причиной. */
export function checkTriangle(p: { sink: Pt | null; hob: Pt | null; fridge: Pt | null }): TriangleCheck {
  const missing = [!p.sink && "мойки", !p.hob && "варочной", !p.fridge && "холодильника"].filter(Boolean);
  if (!p.sink || !p.hob || !p.fridge) {
    return { ok: null, sides: null, sumCm: null, problems: [`треугольник не мерили: нет ${missing.join(", ")}`] };
  }
  const sides = { sinkHob: dist(p.sink, p.hob), hobFridge: dist(p.hob, p.fridge), fridgeSink: dist(p.fridge, p.sink) };
  const sumCm = sides.sinkHob + sides.hobFridge + sides.fridgeSink;
  const N = KITCHEN_NORMS;
  const names: Record<keyof typeof sides, string> = { sinkHob: "мойка — варочная", hobFridge: "варочная — холодильник", fridgeSink: "холодильник — мойка" };
  const problems: string[] = [];
  for (const k of Object.keys(sides) as (keyof typeof sides)[]) {
    if (sides[k] < N.triangleSideMinCm) problems.push(`${names[k]} ${sides[k]} см — меньше ${N.triangleSideMinCm}`);
    if (sides[k] > N.triangleSideMaxCm) problems.push(`${names[k]} ${sides[k]} см — больше ${N.triangleSideMaxCm}`);
  }
  if (sumCm > N.triangleSumMaxCm) problems.push(`сумма сторон ${sumCm} см — больше ${N.triangleSumMaxCm}`);
  return { ok: problems.length === 0, sides, sumCm, problems };
}

/**
 * Проходы в глубину комнаты: перед линией (до стены напротив или до острова) — рабочий; за островом и у торца плеча Г —
 * проход. `roomDepthCm` — от задней стены линии до противоположной; нет — проходы не мерим.
 */
export function checkAisles(lay: KitchenLayout, roomDepthCm: number | undefined, cooks: 1 | 2 = 1): AisleCheck[] {
  if (roomDepthCm === undefined) return [];
  const N = KITCHEN_NORMS;
  const work = cooks === 2 ? N.aisleTwoCooksCm : N.aisleOneCookCm;
  const wallZ = lay.back + roomDepthCm; // противоположная стена в осях набора
  const out: AisleCheck[] = [];
  const add = (where: AisleCheck["where"], gapCm: number, needCm: number): void => {
    out.push({ where, gapCm: Math.round(gapCm), needCm, ok: gapCm >= needCm });
  };
  if (lay.island) {
    add("front", lay.island.z - lay.island.d / 2 - lay.front, work);
    add("behind-island", wallZ - (lay.island.z + lay.island.d / 2), N.walkwayCm);
  } else {
    add("front", wallZ - lay.front, work);
  }
  if (lay.leg) add("leg-end", wallZ - (lay.back + lay.leg.lengthCm), N.walkwayCm);
  return out;
}

/** Вытяжка (над варочной, у стены) — до вентканала по прямой. */
export function checkVent(lay: KitchenLayout): { distanceCm: number; ok: boolean } | null {
  const { hob, vent } = lay.points;
  if (!hob || !vent) return null;
  const distanceCm = dist({ x: hob.x, z: lay.back }, vent);
  return { distanceCm, ok: distanceCm <= KITCHEN_NORMS.ventMaxCm };
}

/** Все проверки набора сразу. `ok` — нет нарушений; неизмеренный треугольник нарушением не считается. */
export function checkKitchen(spec: KitchenSpec, opts: { cooks?: 1 | 2 } = {}): KitchenReport {
  const lay = kitchenLayout(spec);
  const triangle = checkTriangle(lay.points);
  const aisles = checkAisles(lay, spec.roomDepthCm, opts.cooks ?? 1);
  const vent = checkVent(lay);
  const where = { front: "перед линией", "behind-island": "за островом", "leg-end": "у торца плеча" } as const;
  const problems = [
    ...(triangle.ok === false ? triangle.problems : []),
    ...aisles.filter((a) => !a.ok).map((a) => `проход ${where[a.where]} ${a.gapCm} см — меньше ${a.needCm}`),
  ];
  const warnings = vent && !vent.ok ? [`вытяжка в ${vent.distanceCm} см от вентканала — дальше ${KITCHEN_NORMS.ventMaxCm} (норма не подтверждена)`] : [];
  return { ok: problems.length === 0, triangle, aisles, vent, problems, warnings };
}

/**
 * Где поставить мойку и варочную, чтобы треугольник прошёл: перебор модулей (варочная — на основной линии, не в крайнем
 * модуле у колонны или стены; между ней и мойкой — хотя бы модуль; под варочной модуль ≥ 60, под мойкой ≥ 45 — если такие
 * есть). Холодильника нет — только эти правила и вентканал. `score` — штраф лучшей пары (0 — всё по нормам), им же
 * `kits/kitchen-modules.ts` сравнивает наборы ширин модулей.
 */
export function scoreWorkPoints(spec: KitchenSpec): { score: number; sinkAtCm: number; hobAtCm: number } | null {
  const lay = kitchenLayout(spec);
  const main = lay.slots.map((s, i) => ({ s, i })).filter((x) => !x.s.leg);
  if (main.length < 2) return null;
  const N = KITCHEN_NORMS;
  const withHob = spec.features.includes("hob"); // без варочной её место ничего не значит — штрафы только за мойку
  const roomy = (sink: KitchenSlot, hob: KitchenSlot): boolean => sink.w >= N.sinkModuleMinCm && (!withHob || hob.w >= N.hobModuleMinCm);
  const anyRoomy = lay.slots.some((a) => main.some((b) => a !== b.s && roomy(a, b.s)));
  const mid = (main.length - 1) / 2;
  let best: { score: number; sinkAtCm: number; hobAtCm: number } | null = null;
  for (const sink of lay.slots.map((s, i) => ({ s, i }))) {
    for (const hob of main) {
      if (hob.i === sink.i) continue;
      if (anyRoomy && !roomy(sink.s, hob.s)) continue;
      const trial = kitchenLayout({ ...spec, sinkAtCm: sink.s.s, hobAtCm: hob.s.s });
      const tri = checkTriangle(trial.points);
      const vent = checkVent(trial);
      let score = 0;
      if (tri.sides) {
        for (const v of Object.values(tri.sides)) {
          score += Math.max(0, N.triangleSideMinCm - v) + Math.max(0, v - N.triangleSideMaxCm);
        }
        score += Math.max(0, (tri.sumCm ?? 0) - N.triangleSumMaxCm);
        score *= 10;
      }
      if (withHob && !sink.s.leg && Math.abs(sink.i - hob.i) < 2) score += 500; // нет рабочего места между мойкой и плитой
      const hobPos = main.findIndex((m) => m.i === hob.i);
      if (withHob && (hobPos === 0 || hobPos === main.length - 1)) score += 200; // варочная в крайнем модуле — у колонны/стены
      if (vent) score += vent.distanceCm;
      if (!sink.s.leg) score += Math.abs(main.findIndex((m) => m.i === sink.i) - mid); // при равенстве — мойка ближе к середине
      if (!best || score < best.score) best = { score, sinkAtCm: sink.s.s, hobAtCm: hob.s.s };
    }
  }
  return best;
}

/** Точки мойки и варочной для `KitchenSpec` (см. `scoreWorkPoints`). */
export function pickWorkPoints(spec: KitchenSpec): { sinkAtCm: number; hobAtCm: number } | null {
  const best = scoreWorkPoints(spec);
  return best && { sinkAtCm: best.sinkAtCm, hobAtCm: best.hobAtCm };
}
