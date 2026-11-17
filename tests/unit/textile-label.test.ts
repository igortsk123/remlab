// ЯРЛЫК ПЛЕДА (T-20261117-10, владелец TG 1445): плед в 3D — не геометрия, а место-ярлык с фото товара и ценой. Здесь: зеркало правила на
// странице (`CLOTH_LABEL` = `data/flat3d/textile.json:label`), место-ярлык невидимо, но имеет рамку и принимает луч; рендер (экспорт сцены для
// Blender) пледа не получает — ни бруска, ни цвета «по слову»; шторы и подушки в экспорте остаются.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import textileJson from "@/data/flat3d/textile.json";
import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { buildLabelSpot } from "@/lib/viewer3d/kits/textile";
import { exportScene } from "@/lib/viewer3d/scene-export";

const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const SOFA = { role: "диван", x: 200, y: 280, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const GEO = { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [{ kind: "window", wall: "west", offset_cm: 70, width_cm: 150, sill_cm: 85, height_cm: 150 }] };
const THROW = { role: "плед", strategy: "textile_abstract",
  place: { x: 56.3, y: 280, rot: 180, elev_cm: 60, slot_instance_id: "soft.throw#0", kind: "throw", edge: "arm_right", w: 36, d: 55, h: 5 },
  look: { hex: "#b8644a", from: "name:терракот", sheer: false, of: "t1" }, sku: { name: "Плед Ягель", price: 2990, sid: "t1", img: "img/t1.jpg" } };
const PILLOW = { role: "подушка 2", strategy: "textile_abstract",
  place: { x: 180, y: 289.5, rot: 180, elev_cm: 45, slot_instance_id: "soft.pillows#1", parent: "seating.sofa#0", kind: "pillow", w: 45, d: 11, h: 45 },
  look: { hex: "#d8c4a6", from: "name:бежев", sheer: false, of: "p2" }, sku: { name: "Подушка Удина", price: 990, sid: "p2", w: 45, d: 45, h: 11 } };

describe("ярлык пледа", () => {
  it("страница зеркалит правило: CLOTH_LABEL в index.html = формы с label:true в data/flat3d/textile.json", () => {
    const html = readFileSync(resolve(__dirname, "../../tools/scout/flat215-demo/index.html"), "utf8");
    const m = /const CLOTH_LABEL=\[([^\]]*)\]/.exec(html);
    expect(m, "в index.html нет CLOTH_LABEL").not.toBeNull();
    const page = m![1]!.split(",").map((s) => s.trim().replace(/['"]/g, "")).filter(Boolean).sort();
    const data = Object.entries(textileJson.label).filter(([, on]) => on === true).map(([k]) => k).sort();
    expect(page).toEqual(data);
  });

  it("место-ярлык: невидимо для глаза, но в сцене есть рамка (для ярлыка страницы) и луч его находит (тап → карточка)", () => {
    const g = buildLabelSpot({ widthCm: 36, depthCm: 55, heightCm: 5 });
    g.updateMatrixWorld(true);
    const bb = new THREE.Box3().setFromObject(g);
    expect(Math.round((bb.max.x - bb.min.x) * 100)).toBe(36);
    expect(Math.round((bb.max.z - bb.min.z) * 100)).toBe(55);
    const mesh = g.children[0] as THREE.Mesh;
    expect((mesh.material as THREE.Material).visible).toBe(false);       // ничего не рисует
    expect(mesh.castShadow || mesh.receiveShadow).toBe(false);           // и тени не даёт
    const ray = new THREE.Raycaster(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, -1, 0));
    expect(ray.intersectObject(g, true).length).toBeGreaterThan(0);
  });

  it("рендер: плед в экспорт сцены не идёт (нет бруска и цвета по слову), подушка и штора остаются", () => {
    const built = fromDemoVariant({ room: GEO, variants: [{ id: "v", style: "сканди", items: [SOFA], decor: [THROW, PILLOW] }] } as never, "v", CTX)!;
    const sc = resolveScene(built.apartment, built.catalogue, defaultConfiguration(built.apartment, built.catalogue));
    const slotIds = sc.items.map((i) => i.slotId);
    expect(slotIds).toContain("textile:плед#0");                            // в сцене-расчёте плед есть: список, сумма, карточка
    const out = exportScene(built.apartment, built.catalogue, sc);
    const kitSlots = out.kits.map((k) => k.slotId);
    expect(kitSlots).not.toContain("textile:плед#0");
    expect(kitSlots).toContain("textile:подушка 2#0");
  });
});
