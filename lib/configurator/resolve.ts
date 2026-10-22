// Чистое ядро конфигуратора: выбор → разрешённая сцена + цена + претензии.
// Без БД, сети и three.js — это гоняет vitest (`tests/unit/configurator-resolve.test.ts`),
// а все три режима показа (3D, план, фото) строятся ТОЛЬКО поверх результата `resolveScene`.

import { baseSnapshotOf } from "@/lib/configurator/fromDemo";
import { decorLayout } from "@/lib/viewer3d/scene-extras";
import type { Apartment, Placement, Slot, SlotCategory, WallSide } from "@/contracts/apartment";
import { resolveAccentSide } from "@/lib/configurator/accent";
import type { Catalogue, Configuration, Material, Option, OptionAsset } from "@/contracts/configurator";
import { materialById, optionById } from "@/contracts/configurator";
import { budgetBucket, type BudgetBucket } from "@/lib/configurator/budget";
import type { Settlement } from "@/lib/configurator/settlement";

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
  price: number;
  /** Настольный декор без опоры (столика нет или не влезает): в составе и цене есть, в сцене не рисуется. */
  unplaced?: boolean;
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
  price: number;
  /** Акцентная стена (demo-07): материал и уже вычисленная сторона (`accent.ts:resolveAccentSide`). */
  accent?: { material: Material; side: WallSide };
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
  basePrice: number;
  upgrades: number;
  total: number;
  byRoom: Record<string, number>;
  upgradeCount: number;
  /** Доплаты по назначению (demo-06): в сертификат, застройщику вне сертификата, в цену квартиры; сумма = `upgrades`. */
  bySettlement: Record<Settlement, number>;
  /** То, что идёт в пакет (`allowance`), по бюджетам (demo-23); сумма = `bySettlement.allowance`. */
  byBudget: Record<BudgetBucket, number>;
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
  return {
    version: 3, apartmentId: a.id, developerId: c.developerId, selections, placements: {},
    // набор витрины: снимок «место → модель» едет и в черновик, чтобы после пересборки сравнить
    ...(a.baseVariant ? { baseVariant: a.baseVariant, baseSnapshot: baseSnapshotOf(a, c) } : {}),
  };
}

function priceOf(o: Option): number {
  return o.tier === "base" ? 0 : o.price;
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
  sameInGroups(a, c, chosen, selections);

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
  const byRoom: Record<string, number> = {};
  let upgrades = 0;
  let upgradeCount = 0;
  const bySettlement: Record<Settlement, number> = { allowance: 0, developer_surcharge: 0, property_price: 0 };
  const byBudget: Record<BudgetBucket, number> = { furniture: 0, fitout: 0 };

  const hidden = new Set(config.hidden ?? []);
  for (const slot of a.slots) {
    const opt = chosen.get(slot.id);
    if (!opt) continue;
    // УБРАННОЕ ПОКУПАТЕЛЕМ: мебели нет ни в сцене, ни в сумме; встроенное и отделка не убираются (их нет без ремонта)
    if (hidden.has(slot.id) && slot.kind !== "surface" && slot.kind !== "builtin") continue;
    const price = priceOf(opt);
    if (price > 0 || opt.tier !== "base") {
      upgrades += price;
      bySettlement[opt.settlement ?? "allowance"] += price;
      if ((opt.settlement ?? "allowance") === "allowance") byBudget[budgetBucket({ slotKind: slot.kind, slotCategory: slot.category })] += price;
      if (price > 0) upgradeCount += 1;
      byRoom[slot.roomId] = (byRoom[slot.roomId] ?? 0) + price;
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
        price: price,
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
      price: price,
    });
  }
  placeTabletop(a, items);
  // ВТОРОЙ ПРОХОД — АКЦЕНТНАЯ СТЕНА «ЗА ДИВАНОМ» (demo-07, Codex 16.10): сторона — от итогового места дивана в той же комнате
  // (после перестановок покупателя); дивана нет — акцента нет, стены базовые, без молчаливой «северной»
  for (const sf of surfaces) {
    const opt = optionById(c, sf.optionId);
    const acc = opt?.asset.kind === "material" ? opt.asset.accent : undefined;
    if (!acc) continue;
    const mat = materialById(c, acc.materialId);
    const room = a.rooms.find((r) => r.id === sf.roomId);
    const sofa = items.find((i) => i.roomId === sf.roomId && i.kind === "furniture" && /^диван/.test(i.photoRole ?? i.slotId));
    if (!mat || !room || !sofa) {
      issues.push({ code: "no_material", slotId: sf.slotId, optionId: sf.optionId, messageRu: "акцентная стена без дивана или материала" });
      continue;
    }
    sf.accent = { material: mat, side: resolveAccentSide(room, sofa.placement) };
  }
  const packed = packPrices(c, items);
  upgrades += packed.delta;
  bySettlement.allowance += packed.delta;   // упаковки — мебель
  byBudget.furniture += packed.delta;
  for (const [roomId, d] of packed.byRoom) byRoom[roomId] = (byRoom[roomId] ?? 0) + d;
  upgradeCount += packed.countDelta;

  return {
    apartmentId: a.id,
    items,
    surfaces,
    totals: {
      basePrice: a.basePrice,
      upgrades,
      total: a.basePrice + upgrades,
      byRoom,
      upgradeCount,
      bySettlement,
      byBudget,
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
  if (asset.kind === "kit" && asset.wCm && asset.dCm) {
    // плита ковра (demo-18 п.2): размер товара, длинная сторона — вдоль длинной стороны места (поворот места не меняется)
    const [long, short] = [Math.max(asset.wCm, asset.dCm), Math.min(asset.wCm, asset.dCm)];
    return base.wCm >= base.dCm ? { ...base, wCm: long, dCm: short } : { ...base, wCm: short, dCm: long };
  }
  if (asset.kind !== "mesh") return base;
  return { ...base, wCm: asset.wCm, dCm: asset.dCm, hCm: asset.hCm };
}

/**
 * НАСТОЛЬНЫЙ ДЕКОР ВСТАЁТ НА ТЕКУЩУЮ ОПОРУ (demo-05 п.9, разбор Codex): место вазы — не данные, а следствие расстановки.
 * Покупатель передвинул, заменил или убрал столик — ваза следует за ним (ряд по длинной оси, правило серверного кадра
 * `decorLayout`); опоры нет или не влезает — предмет остаётся в составе и цене, но не рисуется (`unplaced`).
 */
export function placeTabletop(a: Apartment, items: ResolvedItem[]): void {
  const tabletop = new Set(a.slots.filter((s) => s.tabletop).map((s) => s.id));
  if (!tabletop.size) return;
  for (const roomId of new Set(items.map((i) => i.roomId))) {
    const here = items.filter((i) => i.roomId === roomId);
    const decor = here.filter((i) => tabletop.has(i.slotId));
    if (!decor.length) continue;
    const supports = here.filter((i) => !tabletop.has(i.slotId)).map((i) => ({ role: i.photoRole ?? undefined, x: i.placement.x,
      y: i.placement.y, rot: i.placement.rot, w: i.placement.wCm, d: i.placement.dCm, h: i.placement.hCm, elev: i.placement.elevCm }));
    const { placed } = decorLayout(supports, decor.map((i) => ({ role: i.photoRole ?? undefined, item: i,
      sku: { w: i.placement.wCm, d: i.placement.dCm, h: i.placement.hCm } })));
    const at = new Map(placed.map((p) => [p.decor.item, p]));
    for (const i of decor) {
      const p = at.get(i);
      if (!p) {
        i.unplaced = true;
        continue;
      }
      i.placement = { ...i.placement, x: p.x, y: p.y, rot: p.rot, elevCm: p.elev };
      delete i.unplaced;
    }
  }
}

/**
 * ГРУППА СОВМЕСТНОЙ ЗАМЕНЫ — ИНВАРИАНТ СЕРВЕРА (разбор Codex 15.10): стулья за одним столом одинаковые (владелец 30.09).
 * Клиент (`useFlatConfig.choose`) ставит одну опцию всем, но старый или поддельный подбор мог бы смешать товары и занизить
 * число упаковок — здесь вся группа приводится к выбору первого места, если он разрешён остальным.
 */
function sameInGroups(a: Apartment, c: Catalogue, chosen: Map<string, Option>, selections: Record<string, string>): void {
  const groups = new Map<string, Slot[]>();
  for (const s of a.slots) if (s.selectionGroup) groups.set(s.selectionGroup, [...(groups.get(s.selectionGroup) ?? []), s]);
  for (const members of groups.values()) {
    const lead = chosen.get(members[0]!.id);
    if (!lead) continue;
    for (const s of members.slice(1)) {
      if (chosen.get(s.id)?.id === lead.id) continue;
      if (!optionsForSlot(a, c, s).some((o) => o.id === lead.id)) continue;
      chosen.set(s.id, lead);
      selections[s.id] = lead.id;
    }
  }
}

/**
 * Цена упаковок: места с одним `packKey` (у опции `pack` > 1) — ceil(мест/pack) покупок одной строкой на первое место.
 * → поправки к итогам (рядом с ценой «по штуке», которую уже посчитал основной проход).
 */
function packPrices(c: Catalogue, items: ResolvedItem[]): { delta: number; countDelta: number; byRoom: Map<string, number> } {
  const byKey = new Map<string, ResolvedItem[]>();
  for (const i of items) {
    const o = optionById(c, i.optionId);
    if (!o?.packKey || !o.pack || o.pack <= 1 || o.tier === "base") continue;
    byKey.set(o.packKey, [...(byKey.get(o.packKey) ?? []), i]);
  }
  let delta = 0;
  let countDelta = 0;
  const byRoom = new Map<string, number>();
  for (const group of byKey.values()) {
    const o = optionById(c, group[0]!.optionId)!;
    const total = o.price * Math.ceil(group.length / o.pack!);
    group.forEach((i, k) => {
      const next = k === 0 ? total : 0;
      const d = next - i.price;
      if (i.price > 0 && next === 0) countDelta -= 1;
      if (i.price === 0 && next > 0) countDelta += 1;
      i.price = next;
      delta += d;
      byRoom.set(i.roomId, (byRoom.get(i.roomId) ?? 0) + d);
    });
  }
  return { delta, countDelta, byRoom };
}

