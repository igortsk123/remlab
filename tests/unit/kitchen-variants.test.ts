import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { Material } from "@/contracts/configurator";
import { kitchenExamplesFile, type KitchenExample } from "@/contracts/kitchen-example";
import { kitchenFitFile } from "@/contracts/kitchen-fit";
import catalogue from "@/data/flat3d/catalogue-base.json";
import materials from "@/data/flat3d/materials.json";
import demoUk from "@/data/partners/demo-uk.json";
import demo from "@/data/partners/demo.json";
import fitFile from "@/data/partners/kitchen-fit/flat215.json";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
import { apartmentCard, findApartment, partners } from "@/lib/partners/registry";
import { buildKitchen } from "@/lib/viewer3d/kits/kitchen";
import { kitchenSpecFromExample } from "@/lib/viewer3d/kits/kitchen-from-example";
import { createMaterialCtx } from "@/lib/viewer3d/materials";

// ВАРИАНТЫ КУХНИ С ПРИМЕРОМ (план onb-09 Т3, T-20261105-33): у застройщика вариант со `specRef` — настоящая кухня из примеров
// того же рынка с посадкой на квартиру; цена — цена примера; картинка — наш 3D-кадр; к покупателю — только при включённой комнате.

const examples = new Map<string, KitchenExample>([ru, uk].flatMap((f) => kitchenExamplesFile.parse(f).examples).map((e) => [e.id, e]));
const fits = kitchenFitFile.parse(fitFile);
const list = partners();
const withSpec = list.flatMap((p) => p.apartments.flatMap((a) => (a.options ?? []).flatMap((g) =>
  g.variants.filter((v) => v.specRef).map((v) => ({ p, a, g, v, e: examples.get(v.specRef!) })))));

describe("варианты со specRef — данные", () => {
  it("есть у обеих квартир с посадкой: русские — Сима-ленд, английские — IKEA; рынки не смешаны", () => {
    expect(fits.apartments.length).toBeGreaterThan(0);
    for (const id of fits.apartments) {
      const own = withSpec.filter((x) => x.a.id === id);
      expect(own.length, id).toBeGreaterThan(0);
    }
    for (const { p, v, e } of withSpec) {
      expect(e, v.specRef).toBeDefined();
      expect(e!.market, v.id).toBe(p.market);
      expect(e!.currency, v.id).toBe(p.currency);
    }
  });

  it("пример разрешён для квартиры и встал на неё; цена — цена примера; картинка лежит в public", () => {
    for (const { a, v, e } of withSpec) {
      const banned = [a.id, a.enTwin].filter(Boolean).some((id) => (e!.notFor?.flats ?? []).includes(id!));
      expect(banned, v.id).toBe(false);
      expect(fits.apartments, a.id).toContain(a.id);
      expect(fits.fits[e!.id]?.ok, v.id).toBe(true);
      expect(v.pricing, v.id).toEqual({ type: "surcharge", amount: e!.price });
      expect(v.image && existsSync(`public${v.image}`), v.image).toBe(true);
    }
  });

  it("прежний вариант по умолчанию остаётся — без примера, как было", () => {
    for (const { g } of withSpec) expect(g.variants.find((v) => v.id === g.defaultVariantId)?.specRef).toBeUndefined();
  });
});

describe("показ покупателю — только при включённой комнате", () => {
  const specIds = (id: string, l = list): string[] =>
    apartmentCard(findApartment(id, l)!).options.flatMap((g) => g.variants.filter((v) => v.specRef).map((v) => v.id));

  it("кухня пока «скоро» — вариантов с примером в карточке нет", () => {
    for (const id of fits.apartments) {
      const kitchen = findApartment(id)!.apartment.rooms.find((r) => r.kind === "kitchen");
      if (kitchen?.enabled && kitchen.contentState === "ready") continue; // комнату уже включили — проверяет следующий тест
      expect(specIds(id), id).toEqual([]);
    }
  });

  it("включили комнату — варианты с примером приходят в карточку со ссылкой", () => {
    const on = (raw: typeof demo | typeof demoUk): unknown => ({
      ...raw,
      apartments: raw.apartments.map((a) => (!("rooms" in a) || !Array.isArray(a.rooms) ? a
        : { ...a, rooms: a.rooms.map((r) => (r.kind === "kitchen" ? { ...r, enabled: true, contentState: "ready" } : r)) })),
    });
    const l = partners([on(demo), on(demoUk)]);
    for (const id of fits.apartments) {
      const ids = specIds(id, l);
      expect(ids.length, id).toBe(withSpec.filter((x) => x.a.id === id).length);
    }
  });
});

describe("процесс: вариант → набор с посадкой → 3D", () => {
  const ctx = {
    materials: createMaterialCtx(1, false),
    byId: (id: string): Material | undefined => [...materials.materials, ...catalogue.materials].find((m) => m.id === id) as Material | undefined,
    fallback: { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as Material,
  };

  it("каждый вариант со specRef собирается по своей посадке, без допущения о холодильнике", () => {
    for (const { v, e } of withSpec) {
      const fit = fits.fits[e!.id];
      if (!fit?.ok) throw new Error(`${v.id}: нет посадки`);
      const spec = kitchenSpecFromExample(e!, { fit });
      expect(spec.fridgeAssumed, v.id).toBeFalsy();
      expect(buildKitchen(ctx, spec).children.length, v.id).toBeGreaterThan(20);
    }
  });
});
