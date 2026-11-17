import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { fromDemoVariant, type DemoContext, type DemoData } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { SCENE_EXPORT_VERSION, exportScene } from "@/lib/viewer3d/scene-export";
import { tintHex } from "@/lib/viewer3d/finish-passport";
import { texturedFinish } from "@/lib/viewer3d/finish-textures";
import { material as materialSchema } from "@/contracts/configurator";
import materials from "@/data/flat3d/materials.json";

// ЭКСПОРТ СЦЕНЫ ДЛЯ BLENDER (render-3d-01 шаги 0–1): одно описание сцены для /demo и рендера — отделка с картами, тайлом и тонировкой.
const live = JSON.parse(readFileSync("tests/fixtures/flat-bridge-live-0511.json", "utf8")) as DemoData;
const gold = JSON.parse(readFileSync("tests/fixtures/flat-bridge-live-0511.golden.json", "utf8")) as { contexts: Record<string, DemoContext> };

const exportOf = (flat: string, variant: string) => {
  const r = fromDemoVariant(live, variant, gold.contexts[flat]!)!;
  const sc = resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue));
  return exportScene(r.apartment, r.catalogue, sc);
};

describe("тонировка карты цветом паспорта", () => {
  it("нет tintMean — карта цветная, цвет белый (как прежде)", () => {
    expect(tintHex({ colorHex: "#dcc7a6" })).toBe("#ffffff");
  });
  it("нейтральная карта: цвет делится на её среднюю яркость, не выходя за белый", () => {
    const t = tintHex({ colorHex: "#808080", tintMean: 0.5 });
    expect(t).not.toBe("#808080");
    const ch = [1, 3, 5].map((i) => parseInt(t.slice(i, i + 2), 16));
    expect(ch[0]).toBe(ch[1]);
    expect(Math.max(...ch)).toBeLessThanOrEqual(255);
    expect(tintHex({ colorHex: "#ffffff", tintMean: 0.5 })).toBe("#ffffff");
  });
  it("материалы finish-* собраны с картами, тайлом, тонировкой и источником CC0", () => {
    for (const id of ["finish-wall", "finish-floor"]) {
      const m = (materials.materials as Record<string, unknown>[]).find((x) => x.id === id)!;
      expect(m, id).toBeTruthy();
      const parsed = materialSchema.parse({ ...m, baseColorUrl: `/flat3d/materials/${m.baseColorUrl as string}` });
      expect(parsed.tintMean).toBeGreaterThan(0.2);
      expect(parsed.source?.licence).toBe("CC0-1.0");
      expect(parsed.source?.sourceUrl).toMatch(/^https:\/\/ambientcg\.com\/a\//);
      expect(parsed.tileCm[0]).toBeGreaterThan(50);
    }
  });
  it("texturedFinish: цвет паспорта и приставка id комнаты, адреса карт абсолютные", () => {
    const w = texturedFinish("wall", { id: "paint-white", colorHex: "#aabbcc" }, "bedroom-1/paint-white")!;
    expect(w.id).toBe("bedroom-1/paint-white");
    expect(w.colorHex).toBe("#aabbcc");
    expect(String(w.baseColorUrl)).toMatch(/^\/flat3d\/materials\/finish-wall-v\d+\.webp$/);
    expect(String(w.normalUrl)).toMatch(/^\/flat3d\/materials\//);
  });
});

describe("экспорт сцены", () => {
  for (const [flat, variant] of [["flat215", "set16"], ["demo-uk-215", "set1"]] as const) {
    it(`${flat}/${variant}: версия, отделка с фактурой, мебель с ключом и местом`, () => {
      const e = exportOf(flat, variant);
      expect(e.version).toBe(SCENE_EXPORT_VERSION);
      expect(e.units).toBe("cm");
      const room = e.rooms[0]!;
      // пол из выбора застройщика (контекст квартиры) остаётся его материалом; без выбора — фактура паспорта (CC0)
      for (const s of [room.wall, room.floor]) {
        expect(s.maps.color).toMatch(/^\/flat3d\/materials\//);
        expect(s.maps.normal).toBeTruthy();
        expect(s.tileCm[0]).toBeGreaterThan(50);
      }
      expect(room.wall.maps.color).toMatch(/finish-wall/);
      expect(room.wall.source?.licence).toBe("CC0-1.0");
      // цвет паспорта сохранён, а умножается карта тонирующим цветом (светлее паспорта: делится на яркость карты)
      expect(room.wall.colorHex).toMatch(/^#[0-9a-f]{6}$/);
      expect(room.wall.tintHex).not.toBe("#ffffff");
      expect(e.meshes.length).toBeGreaterThan(3);
      for (const m of e.meshes) {
        expect(m.meshId).toBeTruthy();
        expect(m.placement.wCm).toBeGreaterThan(0);
        expect(m.liteMissing).toBe(m.liteUrl === null);
      }
      expect(e.liteMissing).toEqual(e.meshes.filter((m) => m.liteMissing).map((m) => m.meshId));
    });
  }
  it("экспорт детерминирован: два вызова дают одно и то же", () => {
    expect(JSON.stringify(exportOf("flat215", "set16"))).toBe(JSON.stringify(exportOf("flat215", "set16")));
  });
});
