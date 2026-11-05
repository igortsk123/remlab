// Паспорт примера кухни (onb-08, `contracts/kitchen-example.ts`) → параметры набора `KitchenSpec` (план onb-09 часть А).
// Паспортный `kitSpec` — основа; поверх него то, чего у набора раньше не было: ряд во всю паспортную длину, форма (Г, полуостров),
// второй цвет фасада (верх), свои цвета набора вместо далёких (ΔE > 10), ширины модулей и точки мойки/варочной, при которых
// проходит рабочий треугольник (`pickModules`). Ширины — из паспорта, если они складываются в ряд; иначе подбор из ряда
// 40/45/60/80 (T-20261105-18). Холодильника в колонне нет — ДОПУЩЕНИЕ: отдельно стоящий (70 см) вплотную у свободного конца
// ряда, из концов — тот, где треугольник лучше; настоящую посадку (стена, вентканал, холодильник) сделает солвер — позже.

import type { KitchenExample } from "@/contracts/kitchen-example";
import { kitchenLayout, type KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";
import { kitchenMaterial } from "@/lib/viewer3d/kits/kitchen-materials";
import { pickModules, type ModulePick } from "@/lib/viewer3d/kits/kitchen-modules";

type Slot = KitchenExample["colors"]["front"];

/** Отдельно стоящий холодильник, см ширины — его центр на 35 см за краем ряда. */
const FRIDGE_W = 70;

/** Материал слота: предложенный по замеру, если он есть среди своих цветов набора, иначе ближайший из каталога. */
function materialOf(slot: Slot | undefined, fallback: string | undefined): string | undefined {
  if (!slot) return fallback;
  if (slot.proposed && kitchenMaterial(slot.proposed.id)) return slot.proposed.id;
  return fallback ?? slot.materialId;
}

/**
 * Где может стоять отдельный холодильник вплотную к ряду (точки пути, см): свободные концы основной линии (не занятые колонной
 * или углом) и торец плеча Г (у полуострова торец в комнате — нет). Холодильник в колонне — пусто. Свободных нет — за колонной.
 */
export function freeEndFridgesCm(spec: KitchenSpec): number[] {
  const lay = kitchenLayout(spec);
  if (lay.columns.some((c) => c.fridge)) return [];
  const half = FRIDGE_W / 2;
  const colsAtEnd = (spec.columnsAt ?? "start") === "end";
  const hasCols = lay.columns.length > 0;
  const out: number[] = [];
  if (!(hasCols && !colsAtEnd) && lay.leg?.at !== "start") out.push(-half);
  if (!(hasCols && colsAtEnd) && lay.leg?.at !== "end") out.push(spec.widthCm + half);
  if (lay.leg && !spec.peninsula) out.push(lay.leg.at === "end" ? spec.widthCm + lay.leg.runCm + half : -(lay.leg.runCm + half));
  if (!out.length) out.push(colsAtEnd ? spec.widthCm + half : -half);
  return out;
}

export function kitchenSpecFromExample(e: KitchenExample, opts: { roomDepthCm?: number; fridgeAtCm?: number } = {}): KitchenSpec {
  const k = e.kitSpec;
  const door = materialOf(e.colors.front, k.doorMaterialId) as string;
  const upper = e.colors.frontUpper ? materialOf(e.colors.frontUpper, e.colors.frontUpper.materialId) : undefined;
  const spec: KitchenSpec = {
    level: k.level,
    features: [...k.features],
    doorMaterialId: door,
    ...(upper && upper !== door ? { doorUpperMaterialId: upper } : {}),
    worktopMaterialId: materialOf(e.colors.worktop, k.worktopMaterialId),
    ...(k.splashbackMaterialId ? { splashbackMaterialId: materialOf(e.colors.splashback, k.splashbackMaterialId) } : {}),
    widthCm: k.widthCm,
    depthCm: k.depthCm,
    ...(k.columnsAt ? { columnsAt: k.columnsAt } : {}),
    ...(opts.roomDepthCm !== undefined ? { roomDepthCm: opts.roomDepthCm } : {}),
    shape: e.shape,
    ...(e.shape === "corner" && k.peninsula ? { peninsula: true } : {}),
    fullRun: true,
  };
  // ширины из паспорта — только если складываются ровно в ряд основной линии (у Wickes это состав набора, не порядок)
  const lay = kitchenLayout(spec);
  const mainW = lay.corner ? lay.runW - lay.D : lay.runW;
  const base = e.modules.base;
  const fixed = base.length && Math.abs(base.reduce((a, w) => a + w, 0) - mainW) < 0.5 ? { modulesCm: [...base] } : undefined;
  const fridges = opts.fridgeAtCm !== undefined ? [opts.fridgeAtCm] : freeEndFridgesCm(spec);
  let best: { pick: ModulePick; fridgeAtCm?: number } | null = null;
  for (const fridgeAtCm of fridges.length ? fridges : [undefined]) {
    const pick = pickModules(fridgeAtCm === undefined ? spec : { ...spec, fridgeAtCm }, fixed);
    if (pick && (!best || pick.score < best.pick.score - 1e-9)) best = { pick, ...(fridgeAtCm !== undefined ? { fridgeAtCm } : {}) };
  }
  if (!best) return spec;
  const { pick, fridgeAtCm } = best;
  return {
    ...spec,
    ...(fridgeAtCm !== undefined ? { fridgeAtCm } : {}),
    modulesCm: pick.modulesCm,
    ...(pick.legModulesCm ? { legModulesCm: pick.legModulesCm } : {}),
    sinkAtCm: pick.sinkAtCm,
    hobAtCm: pick.hobAtCm,
  };
}
