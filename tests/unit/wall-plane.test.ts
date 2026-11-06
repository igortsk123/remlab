// Зеркало прихожей сквозь мост и сцену (T-20261106-73, план hall-demo-01 этап 2): настенная плоскость по стратегии ассета
// (`procedural_plane`) — на своей стене, лицом в комнату, на высоте солвера; не меш, не препятствие. Данные — набор
// `compose_hall` (банк стенда T-61, сканди и лофт: зеркало у западной и у восточной стены).
import { describe, expect, it } from "vitest";

import { catalogue as catalogueSchema, kitAsset } from "@/contracts/configurator";
import { baseSnapshotOf, fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { isFlatOnSurface, planObjects } from "@/lib/viewer3d/build-scene";
import { canvasRect, frameCm, wallPlaneFace } from "@/lib/viewer3d/kits/wall-plane";
import catalogueBase from "@/data/flat3d/catalogue-base.json";

const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
const HALL = { w: 153, d: 210, title: "Прихожая", height_cm: 270, openings: [] };
const MIRROR = { role: "зеркало", strategy: "procedural_plane", w: 56, d: 3, h: 72,
  sku: { name: "Зеркало настенное Тило 56x72", price: 9990, sid: "112923:4956391049781899832", img: "https://cdn.example/m.jpg" } };
const SHOE = { role: "обувница", strategy: "hunyuan3d", x: 20, y: 30, rot: 90, w: 60, d: 35, h: 50,
  sku: { name: "Обувница", msid: "112923_7" } };

const build = (items: object[]) => {
  const r = fromDemoVariant({ room: HALL, variants: [{ id: "h1", items }] }, "h1", CTX)!;
  const specs = planObjects(r.apartment, r.catalogue, resolveScene(r.apartment, r.catalogue, defaultConfiguration(r.apartment, r.catalogue)));
  return { ...r, specs };
};

describe("настенное зеркало: мост → сцена", () => {
  it("зеркало стратегии procedural_plane — набор wall-plane с высотой солвера, не меш (даже с msid)", () => {
    const { apartment, catalogue, specs } = build([SHOE, { ...MIRROR, x: 1.5, y: 28, rot: 90, elev: 114, sku: { ...MIRROR.sku, msid: "112923_9" } }]);
    const slot = apartment.slots.find((s) => s.id === "зеркало#0")!;
    expect(slot.placement).toMatchObject({ x: 1.5, y: 28, rot: 90, wCm: 56, dCm: 3, hCm: 72, elevCm: 114 });
    const opt = catalogue.options.find((o) => o.id === "opt:зеркало#0")!;
    expect(opt.asset).toMatchObject({ kind: "kit", kit: "wall-plane", features: ["mirror"] });
    expect(opt.price).toBe(9990);
    const mirror = specs.filter((s) => s.slotId === "зеркало#0");
    expect(mirror.map((s) => s.kind)).toEqual(["wall-plane"]);
    expect(mirror[0]!.kind === "wall-plane" && mirror[0]!.mirror).toBe(true);
    // не меш: ни одного заказа модели на зеркало
    expect(specs.some((s) => s.kind === "mesh" && s.slotId.startsWith("зеркало"))).toBe(false);
  });

  it("западная стена (rot 90): полотно у стены лицом на +x, низ и верх — от высоты подвеса", () => {
    const f = wallPlaneFace({ x: 1.5, y: 28, rot: 90, wCm: 56, dCm: 3, hCm: 72, elevCm: 114 });
    const fr = frameCm(56, 72);
    expect(f.normal).toEqual([1, 0]);
    expect(new Set(f.corners.map((c) => c[0]))).toEqual(new Set([1.5 + 1.5 + 0.2]));   // лицевая сторона, 3,2 см от стены
    expect(Math.min(...f.corners.map((c) => c[2]))).toBeCloseTo(114 + fr, 5);
    expect(Math.max(...f.corners.map((c) => c[2]))).toBeCloseTo(114 + 72 - fr, 5);
    // вдоль стены — ширина полотна вокруг центра следа
    const ys = f.corners.map((c) => c[1]);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(canvasRect({ widthCm: 56, heightCm: 72, depthCm: 3 }).w, 5);
    expect((Math.max(...ys) + Math.min(...ys)) / 2).toBeCloseTo(28, 5);
  });

  it("восточная стена (rot 270) и южная (rot 0): нормаль в комнату", () => {
    expect(wallPlaneFace({ x: 151.5, y: 30, rot: 270, wCm: 60, dCm: 3, hCm: 102, elevCm: 99 }).normal).toEqual([-1, 0]);
    const s = wallPlaneFace({ x: 80, y: 1.5, rot: 0, wCm: 60, dCm: 3, hCm: 60, elevCm: 120 });
    expect(s.normal).toEqual([0, 1]);
    expect(new Set(s.corners.map((c) => c[1]))).toEqual(new Set([3.2]));
  });

  it("не препятствие: прогулка и старт камеры его пропускают, обувница под ним — препятствие", () => {
    const { specs } = build([SHOE, { ...MIRROR, x: 1.5, y: 28, rot: 90, elev: 114 }]);
    const byId = new Map(specs.map((s) => [s.slotId, s]));
    expect(isFlatOnSurface(byId.get("зеркало#0")!)).toBe(true);
    expect(isFlatOnSurface(byId.get("обувница#0")!)).toBe(false);
  });

  it("смена товара зеркала — «набор обновился» в снимке сохранения", () => {
    const a = build([SHOE, { ...MIRROR, x: 1.5, y: 28, rot: 90, elev: 114 }]);
    const b = build([SHOE, { ...MIRROR, x: 1.5, y: 28, rot: 90, elev: 114, sku: { ...MIRROR.sku, sid: "99272:1" } }]);
    expect(baseSnapshotOf(a.apartment, a.catalogue)["зеркало#0"]).toMatch(/^plane:/);
    expect(baseSnapshotOf(a.apartment, a.catalogue)["зеркало#0"]).not.toBe(baseSnapshotOf(b.apartment, b.catalogue)["зеркало#0"]);
  });

  it("картина той же стратегии — плоскость с фото товара; ковёр (лежит) — прежним путём", () => {
    const { catalogue, specs } = build([SHOE, { role: "картина", strategy: "procedural_plane", x: 76, y: 1.5, rot: 0, w: 50, d: 2, h: 70, elev: 120,
      sku: { name: "Картина", sid: "p1", img: "https://cdn.example/p.jpg" } },
    { role: "ковёр", strategy: "procedural_plane", x: 76, y: 100, rot: 0, w: 120, d: 80, h: 1, sku: { name: "Ковёр", sid: "r1", img: "https://cdn.example/r.jpg" } }]);
    expect(specs.find((s) => s.slotId === "картина#0")).toMatchObject({ kind: "wall-plane", mirror: false });
    expect(catalogue.materials.find((m) => m.id.startsWith("plane:"))!.baseColorUrl).toBe("https://cdn.example/p.jpg");
    expect(specs.find((s) => s.slotId === "ковёр#0")!.kind).toBe("rug");
  });
});

describe("старые сцены без нового вида — как раньше", () => {
  it("каталог без wall-plane разбирается, прежние виды набора приняты", () => {
    expect(catalogueSchema.safeParse(catalogueBase).success).toBe(true);
    for (const kit of ["kitchen", "bathroom", "bed", "wardrobe", "rug"]) expect(kitAsset.safeParse({ kind: "kit", kit }).success).toBe(true);
    expect(kitAsset.safeParse({ kind: "kit", kit: "wall-plane" }).success).toBe(true);
    expect(kitAsset.safeParse({ kind: "kit", kit: "mirror-ball" }).success).toBe(false);
  });

  it("данные без стратегии: зеркало без модели не появляется, с моделью — меш, как до T-73", () => {
    const plain = { role: "зеркало", x: 1.5, y: 28, rot: 90, w: 56, d: 3, h: 72, elev: 114, sku: { name: "З" } };
    expect(build([SHOE, plain]).specs.map((s) => s.slotId)).toEqual(["обувница#0"]);
    const withMesh = build([SHOE, { ...plain, sku: { name: "З", msid: "m1" } }]);
    expect(withMesh.specs.find((s) => s.slotId === "зеркало#0")!.kind).toBe("mesh");
  });
});
