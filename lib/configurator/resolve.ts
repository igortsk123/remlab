// Чистое ядро конфигуратора: выбор → разрешённая сцена + цена + претензии.
// Без БД, сети и three.js — это гоняет vitest (`tests/unit/configurator-resolve.test.ts`),
// а все три режима показа (3D, план, фото) строятся ТОЛЬКО поверх результата `resolveScene`.

import type { Apartment, Placement, Slot, SlotCategory } from "@/contracts/apartment";
import type { Catalogue, Configuration, Material, Option, OptionAsset } from "@/contracts/configurator";
import { materialById, optionById } from "@/contracts/configurator";

export interface ResolvedItem {
  slotId: string;
  roomId: string;
  optionId: string;
  category: SlotCategory;
  kind: "builtin" | "furniture";
  titleRu: string;
  titleEn: string;
  placement: Placement;
  asset: OptionAsset;
  photoRole: string | null;
  priceGbp: number;
}

export interface ResolvedSurface {
  slotId: string;
  roomId: string;
  optionId: string;
  category: SlotCategory;
  surface: "floor" | "wall" | "splashback" | "worktop";
  titleRu: string;
  titleEn: string;
  material: Material;
  priceGbp: number;
}

export type IssueCode =
  | "unknown_slot"
  | "unknown_option"
  | "not_allowed"
  | "requires"
  | "excludes"
  | "no_material"
  | "wrong_surface";

export interface Issue {
  code: IssueCode;
  slotId: string;
  optionId?: string;
  messageRu: string;
}

export interface Totals {
  basePriceGbp: number;
  upgradesGbp: number;
  totalGbp: number;
  byRoomGbp: Record<string, number>;
  upgradeCount: number;
}

export interface ResolvedScene {
  apartmentId: string;
  items: ResolvedItem[];
  surfaces: ResolvedSurface[];
  totals: Totals;
  issues: Issue[];
  /** Итоговый выбор с подставленными значениями по умолчанию. */
  selections: Record<string, string>;
}

/** Опции, допустимые в слоте: явный список, иначе категория + тип комнаты. */
export function optionsForSlot(a: Apartment, c: Catalogue, slot: Slot): Option[] {
  if (slot.optionIds.length > 0) {
    return slot.optionIds.map((id) => optionById(c, id)).filter((o): o is Option => Boolean(o));
  }
  const room = a.rooms.find((r) => r.id === slot.roomId);
  return c.options.filter(
    (o) =>
      o.category === slot.category &&
      (o.roomKinds.length === 0 || (room ? o.roomKinds.includes(room.kind) : true)),
  );
}

/** Конфигурация «всё по умолчанию» — стартовая точка и эталон для сравнения цены. */
export function defaultConfiguration(a: Apartment, c: Catalogue): Configuration {
  const selections: Record<string, string> = {};
  for (const s of a.slots) selections[s.id] = s.defaultOptionId;
  return { version: 2, apartmentId: a.id, developerId: c.developerId, selections, placements: {} };
}

function priceOf(o: Option): number {
  return o.tier === "base" ? 0 : o.priceGbp;
}

/**
 * Главная функция: из выбора получаем всё, что нужно любому режиму показа.
 * Неизвестный/недопустимый выбор НЕ роняет сцену — слот откатывается к своему default,
 * а причина уезжает в `issues` (демо не должно белеть из-за одной опечатки в ссылке).
 */
export function resolveScene(a: Apartment, c: Catalogue, config: Configuration): ResolvedScene {
  const issues: Issue[] = [];
  const selections: Record<string, string> = {};
  const chosen = new Map<string, Option>();

  for (const slot of a.slots) {
    const allowed = optionsForSlot(a, c, slot);
    const wantedId = config.selections[slot.id];
    let option: Option | undefined;
    if (wantedId) {
      const found = optionById(c, wantedId);
      if (!found) {
        issues.push({ code: "unknown_option", slotId: slot.id, optionId: wantedId, messageRu: `нет опции ${wantedId}` });
      } else if (allowed.length > 0 && !allowed.some((o) => o.id === found.id)) {
        issues.push({ code: "not_allowed", slotId: slot.id, optionId: wantedId, messageRu: `${found.titleRu} нельзя в этот слот` });
      } else {
        option = found;
      }
    }
    option ??= optionById(c, slot.defaultOptionId);
    if (!option) continue; // слот без валидного default — пропускаем, но это ошибка данных
    selections[slot.id] = option.id;
    chosen.set(slot.id, option);
  }

  for (const [slotId, opt] of chosen) {
    const ids = new Set([...chosen.values()].map((o) => o.id));
    for (const need of opt.requires) {
      if (!ids.has(need)) {
        issues.push({ code: "requires", slotId, optionId: opt.id, messageRu: `${opt.titleRu} требует ${need}` });
      }
    }
    for (const bad of opt.excludes) {
      if (ids.has(bad)) {
        issues.push({ code: "excludes", slotId, optionId: opt.id, messageRu: `${opt.titleRu} несовместим с ${bad}` });
      }
    }
  }

  const items: ResolvedItem[] = [];
  const surfaces: ResolvedSurface[] = [];
  const byRoomGbp: Record<string, number> = {};
  let upgradesGbp = 0;
  let upgradeCount = 0;

  for (const slot of a.slots) {
    const opt = chosen.get(slot.id);
    if (!opt) continue;
    const price = priceOf(opt);
    if (price > 0 || opt.tier !== "base") {
      upgradesGbp += price;
      if (price > 0) upgradeCount += 1;
      byRoomGbp[slot.roomId] = (byRoomGbp[slot.roomId] ?? 0) + price;
    }

    if (slot.kind === "surface") {
      if (opt.asset.kind !== "material") {
        issues.push({ code: "no_material", slotId: slot.id, optionId: opt.id, messageRu: `${opt.titleRu} — не материал` });
        continue;
      }
      const mat = materialById(c, opt.asset.materialId);
      if (!mat) {
        issues.push({ code: "no_material", slotId: slot.id, optionId: opt.id, messageRu: `нет материала ${opt.asset.materialId}` });
        continue;
      }
      // ПРИМЕНИМОСТЬ МАТЕРИАЛА (владелец 29.09): доску пола нельзя надеть на фасад шкафа,
      // а плитку — на столешницу дивана. Материал сам объявляет, где он уместен.
      const wanted = slot.surface ?? "floor";
      if (mat.surfaces.length > 0 && !mat.surfaces.includes(wanted)) {
        issues.push({
          code: "wrong_surface",
          slotId: slot.id,
          optionId: opt.id,
          messageRu: `${mat.titleRu} не для поверхности «${wanted}»`,
        });
        continue;
      }
      surfaces.push({
        slotId: slot.id,
        roomId: slot.roomId,
        optionId: opt.id,
        category: slot.category,
        surface: slot.surface ?? "floor",
        titleRu: slot.titleRu,
        titleEn: slot.titleEn,
        material: mat,
        priceGbp: price,
      });
      continue;
    }

    if (!slot.placement) continue; // предмет без места не существует (правило Р1 демо)
    // Куда покупатель передвинул/повернул предмет. Габариты берём у ВЫБРАННОЙ модели, а не из
    // подбора: иначе после замены на предмет другого размера сохранилась бы старая коробка.
    const moved = config.placements?.[slot.id];
    const base = moved ? { ...slot.placement, x: moved.x, y: moved.y, rot: moved.rot } : slot.placement;
    const placement = fitPlacement(base, opt.asset);
    items.push({
      slotId: slot.id,
      roomId: slot.roomId,
      optionId: opt.id,
      category: slot.category,
      kind: slot.kind === "builtin" ? "builtin" : "furniture",
      titleRu: opt.titleRu,
      titleEn: opt.titleEn,
      placement,
      asset: opt.asset,
      photoRole: slot.photoRole ?? null,
      priceGbp: price,
    });
  }

  return {
    apartmentId: a.id,
    items,
    surfaces,
    totals: {
      basePriceGbp: a.basePriceGbp,
      upgradesGbp,
      totalGbp: a.basePriceGbp + upgradesGbp,
      byRoomGbp,
      upgradeCount,
    },
    issues,
    selections,
  };
}

/**
 * Габарит предмета берём У ВЫБРАННОЙ МОДЕЛИ, а не у слота: диван 210 см и диван 180 см
 * занимают разное место. Центр и поворот остаются от слота — как в демо при замене товара.
 * Это же правило «габарит только из паспорта» (Р1): выдумывать оси нельзя.
 */
export function fitPlacement(base: Placement, asset: OptionAsset): Placement {
  if (asset.kind !== "mesh") return base;
  return { ...base, wCm: asset.wCm, dCm: asset.dCm, hCm: asset.hCm };
}
