import { existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { kitchenExample, kitchenExamplesFile, type KitchenExample } from "@/contracts/kitchen-example";
import materials from "@/data/flat3d/materials.json";
import ru from "@/data/partners/kitchen-examples/ru.json";
import uk from "@/data/partners/kitchen-examples/uk.json";
import type { KitchenSpec } from "@/lib/viewer3d/kits/kitchen";

// ПРИМЕРЫ КУХОНЬ (план onb-08, ADR-0330 п.8): паспорт товара → параметры нашего набора. Цена гарнитура ≠ «под ключ»,
// фото показываем только с ясным правом, модели — только CC0/CC-BY.

const files = { ru: kitchenExamplesFile.parse(ru), uk: kitchenExamplesFile.parse(uk) };
const all: KitchenExample[] = [...files.ru.examples, ...files.uk.examples];
const surfacesOf = new Map(materials.materials.map((m) => [m.id, m.surfaces ?? []]));

describe("примеры кухонь", () => {
  it("РФ ≥ 3, UK ≥ 3; рынок и валюта записи совпадают с файлом; id уникальны", () => {
    expect(files.ru.examples.length).toBeGreaterThanOrEqual(3);
    expect(files.uk.examples.length).toBeGreaterThanOrEqual(3);
    for (const [m, f] of Object.entries(files)) {
      for (const e of f.examples) {
        expect(e.market).toBe(m);
        expect(e.currency).toBe(m === "ru" ? "RUB" : "GBP");
      }
    }
    expect(new Set(all.map((e) => e.id)).size).toBe(all.length);
  });

  it("на каждую квартиру рынка — минимум 3 прямые кухни с открытой ценой (flat215 — без углового образца)", () => {
    for (const f of Object.values(files)) {
      const fit = f.examples.filter(
        (e) => e.shape === "straight" && e.priceKind === "fixed" && !e.notFor?.flats.includes("flat215"),
      );
      expect(fit.length, f.market).toBeGreaterThanOrEqual(3);
    }
    expect(files.uk.examples.find((e) => e.shape === "corner")?.notFor?.flats).toContain("flat215");
  });

  it("что входит в цену и что нет — не пересекается", () => {
    for (const e of all) {
      expect(e.priceIncludes.filter((p) => e.priceExcludes.includes(p)), e.id).toEqual([]);
    }
  });

  it("материалы набора есть в каталоге, подходят слоту и совпадают с замером цвета", () => {
    for (const e of all) {
      const s = e.kitSpec;
      const slots: [string | undefined, string][] = [
        [s.doorMaterialId, "front"], [s.worktopMaterialId, "worktop"], [s.splashbackMaterialId, "splashback"],
      ];
      for (const [id, surface] of slots) {
        if (id) expect(surfacesOf.get(id), `${e.id}: ${id}`).toContain(surface);
      }
      expect(s.doorMaterialId).toBe(e.colors.front.materialId);
      expect(s.worktopMaterialId).toBe(e.colors.worktop.materialId);
      if (s.splashbackMaterialId) expect(s.splashbackMaterialId).toBe(e.colors.splashback?.materialId);
      if (e.colors.frontUpper) expect(surfacesOf.get(e.colors.frontUpper.materialId)).toContain("front");
      for (const c of Object.values(e.colors)) {
        if (c?.proposed) expect(surfacesOf.has(c.proposed.id), `${e.id}: новый ${c.proposed.id} уже есть`).toBe(false);
      }
    }
  });

  it("набор той же ширины и глубины, остров — только если он у товара", () => {
    for (const e of all) {
      expect(e.kitSpec.widthCm).toBe(e.lengthCm);
      expect(e.kitSpec.depthCm).toBe(e.depthCm);
      expect(e.kitSpec.features.includes("island")).toBe(e.island);
      if (!e.island) expect(e.kitSpec.level, `${e.id}: premium сам ставит остров`).not.toBe("premium");
      const spec: KitchenSpec = e.kitSpec;
      expect(spec.widthCm).toBeGreaterThan(0);
    }
  });

  it("фото показываем только с ясным правом и с копией в public/", () => {
    for (const e of all) {
      if (e.photo.showAllowed) {
        expect(["CC0-1.0", "CC-BY-4.0"]).toContain(e.photo.license);
        expect(e.photo.path && existsSync(join("public", e.photo.path))).toBe(true);
      } else {
        expect(e.photo.path).toBeUndefined();
      }
      if (e.displayImage.kind === "photo") {
        expect(e.photo.showAllowed).toBe(true);
        expect(e.displayImage.path).toBe(e.photo.path);
      }
      expect(e.affiliate === null || e.market === "ru").toBe(true);
    }
  });

  it("модель — только CC0/CC-BY, у CC-BY обязательна подпись", () => {
    const base = all[0];
    const ccby = { kind: "cc-by", url: "https://example.org/k", author: "A", license: "CC-BY-4.0", checkedAt: "2026-11-05" };
    expect(kitchenExample.safeParse({ ...base, model: ccby }).success).toBe(false);
    expect(kitchenExample.safeParse({ ...base, model: { ...ccby, attribution: "«K» by A, CC BY 4.0" } }).success).toBe(true);
    expect(kitchenExample.safeParse({ ...base, model: { ...ccby, license: "free-commercial" } }).success).toBe(false);
  });

  it("длина вне 240–330 см и пустой список «не входит» не проходят схему", () => {
    const base = all[0];
    expect(kitchenExample.safeParse({ ...base, lengthCm: 200 }).success).toBe(false);
    expect(kitchenExample.safeParse({ ...base, priceExcludes: [] }).success).toBe(false);
  });
});
