/**
 * ДЕКОР НА НОСИТЕЛЕ (T-20261112-101, Codex 12.11 — `_intake/codex/2026-11-12-t101-lamp-contract-answer.md`): лампа набора стоит на
 * комоде. Место даёт решатель паспорта при сборке (`tools/scout/dependent_decor.py` → `planner/dependents.py:resolve`, место
 * `light.lamp` на `light.dresser`): в данных — исходная точка, поза в осях носителя (`local`) и норма поверхности (`fit`). Сцена
 * пересчитывает место от ТЕКУЩЕГО комода при каждом расчёте: передвинули или повернули (✥) — лампа идёт за ним; заменили — норма
 * проверяется заново; комода нет или лампа не влезает — `unplaced`: в составе и цене есть, в сцене нет.
 * Отдельная группа от вазы (`resolve.placeTabletop`): правило вазы «всё или ничего» не должно снимать лампу и наоборот.
 */
import type { Apartment, Placement } from "@/contracts/apartment";
import type { ResolvedItem } from "@/lib/configurator/resolve";
import { hungLiftCm } from "@/lib/viewer3d/scene-extras";

export const CARRIER_STRATEGY = "carrier_surface";

/** Прежняя норма поверхности (`occupancy.json` → `distances_cm.dependents.surface_decor`; данные до T-20261113-12): отступ от края и
 *  доля столешницы — к габариту всей лампы. */
export interface SurfaceFit {
  edge_inset_min_cm: number;
  edge_inset_over_half_base_cm: number;
  max_share_of_top: number;
}

/** Норма лампы (`occupancy.json` → `distances_cm.dependents.table_lamp_on_surface`, T-20261113-12): опора (основание по модели; нет —
 *  весь габарит) целиком на верху с отступом `edge_clear_cm`, абажур не шире верха и не свисает к лицу больше `shade_overhang_front_cm`.
 *  Та же формула — `planner/dependents.py:lamp_on_top`, общие векторы — `services/planner-solver/tests/lamp_fit_vectors.json`. */
export interface LampFit {
  edge_clear_cm: number;
  shade_overhang_front_cm: number;
  base_w_cm?: number;
  base_d_cm?: number;
}

export type CarrierFit = SurfaceFit | LampFit;

/** Место строки декора на носителе (`dependent_decor.lamp_row`). */
export interface CarrierPlace {
  x?: number;
  y?: number;
  bottom_cm?: number;
  slot_instance_id?: string;
  parent_slot_instance_id?: string;
  local?: { dx?: number; dy?: number };
  carrier?: { role?: string; ordinal?: number };
  fit?: Partial<SurfaceFit & LampFit>;
}

interface CarrierDecorIn {
  list_only?: boolean;
  strategy?: string;
  place?: CarrierPlace;
  sku?: { msid?: string | null; w?: number; d?: number; h?: number };
}

const pos = (n: unknown): boolean => n === undefined || (typeof n === "number" && Number.isFinite(n) && n > 0);
const isLampFit = (f: Partial<SurfaceFit & LampFit>): boolean =>
  [f.edge_clear_cm, f.shade_overhang_front_cm].every((n) => Number.isFinite(n)) && pos(f.base_w_cm) && pos(f.base_d_cm);
const fitOf = (f?: Partial<SurfaceFit & LampFit>): CarrierFit | null =>
  !f ? null
    : isLampFit(f) ? (f as LampFit)
      : [f.edge_inset_min_cm, f.edge_inset_over_half_base_cm, f.max_share_of_top].every((n) => Number.isFinite(n)) ? (f as SurfaceFit)
        : null;

/** Строка декора — лампа на носителе с моделью, размерами, носителем и нормой (иначе в 3D не идёт). */
export const isCarrierDecor = (x: CarrierDecorIn): boolean =>
  !x.list_only && x.strategy === CARRIER_STRATEGY && !!x.sku?.msid && !!x.sku.w && !!x.sku.d && !!x.sku.h
  && !!x.place?.carrier?.role && Number.isInteger(x.place.carrier.ordinal) && !!fitOf(x.place.fit)
  && [x.place.x, x.place.y, x.place.bottom_cm].every((n) => Number.isFinite(n));

/** Связь места сцены с носителем (`Slot.onCarrier`) из строки декора: id места комода — явный, не по позиции массива. Носителя в
 *  варианте нет — пустой id: лампа `unplaced`, а не в исходной точке над пустым полом. */
export function carrierLink(place: CarrierPlace, carrierSlotId: string | undefined): {
  slotId: string; dx: number; dy: number; fit: CarrierFit } | undefined {
  const fit = fitOf(place.fit);
  if (!fit) return undefined;
  return { slotId: carrierSlotId ?? "", dx: place.local?.dx ?? 0, dy: place.local?.dy ?? 0, fit };
}

/** Встаёт ли лампа `wCm×dCm` (абажур) с опорой из `fit` в точке `dx, dy` верха `carW×carD` — норма лампы (`LampFit`). */
export function lampFits(carW: number, carD: number, wCm: number, dCm: number, dx: number, dy: number, fit: LampFit): boolean {
  const bw = fit.base_w_cm ?? wCm, bd = fit.base_d_cm ?? dCm, c = fit.edge_clear_cm;
  return carW / 2 - Math.abs(dx) >= bw / 2 + c && carD / 2 - Math.abs(dy) >= bd / 2 + c && wCm <= carW
    && Math.abs(dy) + dCm / 2 <= carD / 2 + fit.shade_overhang_front_cm;
}

/**
 * Куда встанет предмет `wCm×dCm` на верх носителя `car` (поза `dx, dy` в осях носителя — x вдоль ширины, y к лицу, как
 * `dependents._world`) → место или null (не влезает по норме). Лампа (`LampFit`) — по опоре, `lampFits`; прежние данные (`SurfaceFit`) —
 * отступ max(min, половина габарита + запас) от краёв, площадь не больше доли столешницы. Подвесной комод — верх с подъёмом
 * (`hungLiftCm`, как поднимет его `build-scene`).
 */
export function onCarrier(car: Placement & { role?: string; name?: string }, wCm: number, dCm: number, dx: number, dy: number,
  fit: CarrierFit): { x: number; y: number; rot: number; elevCm: number } | null {
  if ("edge_clear_cm" in fit) {
    if (!lampFits(car.wCm, car.dCm, wCm, dCm, dx, dy, fit)) return null;
  } else {
    const base = Math.max(wCm, dCm);
    const m = Math.max(fit.edge_inset_min_cm, base / 2 + fit.edge_inset_over_half_base_cm);
    if (car.wCm / 2 - Math.abs(dx) < m || car.dCm / 2 - Math.abs(dy) < m || base > car.wCm
      || wCm * dCm > fit.max_share_of_top * car.wCm * car.dCm) return null;
  }
  const a = (car.rot * Math.PI) / 180;
  const lift = car.elevCm || hungLiftCm(car.role, car.name, undefined, car.hCm);
  return { x: car.x + dx * Math.cos(a) + dy * Math.sin(a), y: car.y - dx * Math.sin(a) + dy * Math.cos(a), rot: car.rot,
    elevCm: lift + car.hCm };
}

/** Декор на носителе встаёт на текущий носитель (после перестановок покупателя); нет носителя или не влезает — `unplaced`. */
export function placeOnCarriers(a: Apartment, items: ResolvedItem[]): void {
  const link = new Map(a.slots.filter((s) => s.onCarrier).map((s) => [s.id, s.onCarrier!]));
  if (!link.size) return;
  const bySlot = new Map(items.map((i) => [i.slotId, i]));
  for (const i of items) {
    const l = link.get(i.slotId);
    if (!l) continue;
    const car = bySlot.get(l.slotId);
    const at = car && !car.unplaced
      ? onCarrier({ ...car.placement, role: car.photoRole ?? undefined, name: car.titleRu }, i.placement.wCm, i.placement.dCm, l.dx, l.dy, l.fit)
      : null;
    if (!at) {
      i.unplaced = true;
      continue;
    }
    i.placement = { ...i.placement, ...at };
    delete i.unplaced;
  }
}
