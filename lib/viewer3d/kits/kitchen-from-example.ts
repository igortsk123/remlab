// Паспорт примера кухни (onb-08, `contracts/kitchen-example.ts`) → параметры набора `KitchenSpec` (план onb-09 часть А).
// Паспортный `kitSpec` — основа; поверх него то, чего у набора раньше не было: ряд во всю паспортную длину, форма (Г),
// второй цвет фасада (верх), свои цвета набора вместо далёких (ΔE > 10) и точки мойки/варочной, при которых проходит
// рабочий треугольник (`pickWorkPoints`). Посадку в комнату (стена, вентканал, холодильник рядом) делает солвер — позже.

import type { KitchenExample } from "@/contracts/kitchen-example";
import { pickWorkPoints } from "@/lib/viewer3d/kits/kitchen-checks";
import type { KitchenSpec } from "@/lib/viewer3d/kits/kitchen-layout";
import { kitchenMaterial } from "@/lib/viewer3d/kits/kitchen-materials";

type Slot = KitchenExample["colors"]["front"];

/** Материал слота: предложенный по замеру, если он есть среди своих цветов набора, иначе ближайший из каталога. */
function materialOf(slot: Slot | undefined, fallback: string | undefined): string | undefined {
  if (!slot) return fallback;
  if (slot.proposed && kitchenMaterial(slot.proposed.id)) return slot.proposed.id;
  return fallback ?? slot.materialId;
}

export function kitchenSpecFromExample(e: KitchenExample, opts: { roomDepthCm?: number } = {}): KitchenSpec {
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
    fullRun: true,
  };
  const work = pickWorkPoints(spec);
  return work ? { ...spec, ...work } : spec;
}
