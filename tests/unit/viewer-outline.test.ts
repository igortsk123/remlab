import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, fitPlacement, optionsForSlot, resolveScene } from "@/lib/configurator/resolve";
import { planObjects } from "@/lib/viewer3d/build-scene";
import { buildRug } from "@/lib/viewer3d/kits/bedroom";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { outlineFrame } from "@/lib/viewer3d/outline";
import { FlatViewer } from "@/lib/viewer3d/viewer";

// РАМКА ВЫДЕЛЕНИЯ КОВРА ПОСЛЕ ЗАМЕНЫ (T-20261019-02, приёмка): в /flat ковёр заменили на 200×140, а рамка осталась
// по месту 230×160 и торчала за край плиты. Рамка строится по объекту сцены, объект — по размеру товара из
// `resolve.fitPlacement`; без WebGL проверяем всю цепочку «выбор → место → плита → рамка».

const data = {
  room: { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [] },
  variants: [{ id: "v", title: "Сканди", style: "сканди", items: [
    { role: "диван", x: 166, y: 280, rot: 180, w: 162, d: 90, h: 79, sku: { name: "Диван", price: 54990, msid: "112923_1" } },
    { role: "ковёр", x: 200, y: 200, rot: 0, w: 230, d: 160, sku: { name: "Ковёр", price: 9291, sid: "r0", img: "img/r0.jpg" } },
  ] }],
  feeds: { ковёр: [{ name: "Котри", sid: "k", msid: "k", img: "img/k.jpg", w: 200, d: 140, h: 1, price: 4990, url: "uk",
    shop: "divan.ru", src: "pool", styles: ["сканди"] }] },
};
const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };

describe("рамка выделения ковра", () => {
  it("после замены ковра рамка — по размеру товара (fitPlacement), а не по исходному месту", () => {
    const r = fromDemoVariant(data, "v", CTX)!;
    const slot = r.apartment.slots.find((s) => s.id === "ковёр#0")!;
    const opt = optionsForSlot(r.apartment, r.catalogue, slot).find((o) => o.id === "feed:ковёр:k")!;
    const cfg = defaultConfiguration(r.apartment, r.catalogue);
    const scene = resolveScene(r.apartment, r.catalogue, { ...cfg, selections: { ...cfg.selections, "ковёр#0": opt.id } });
    const spec = planObjects(r.apartment, r.catalogue, scene).find((s) => s.slotId === "ковёр#0")!;
    const place = slot.placement!;
    const fit = fitPlacement(place, opt.asset);
    expect(spec.placement).toMatchObject({ wCm: fit.wCm, dCm: fit.dCm });
    expect([fit.wCm, fit.dCm]).toEqual([200, 140]);

    const ctx = {
      materials: createMaterialCtx(1, false),
      byId: (id: string) => r.catalogue.materials.find((m) => m.id === id),
      fallback: r.catalogue.materials[0]!,
    };
    const group = buildRug(ctx, { materialId: spec.kind === "rug" ? spec.materialId : undefined, widthCm: spec.placement.wCm,
      depthCm: spec.placement.dCm, pile: "flat" });
    const { size } = outlineFrame(group);
    // метры сцены, рамка на 4 % шире плиты
    expect(size.x).toBeCloseTo(fit.wCm * 0.01 * 1.04, 6);
    expect(size.z).toBeCloseTo(fit.dCm * 0.01 * 1.04, 6);
    expect(size.x).toBeLessThan(place.wCm * 0.01);
  });

  it("выбранный ковёр заменили — 3D пересобрал плиту и пересчитал рамку (раньше она оставалась от прежней)", async () => {
    const r = fromDemoVariant(data, "v", CTX)!;
    const cfg = defaultConfiguration(r.apartment, r.catalogue);
    // без WebGL: только сцена, карта предметов и наборы, которые им нужны (рендерер в проверке не участвует)
    const v = Object.create(FlatViewer.prototype) as FlatViewer;
    Object.assign(v, {
      scene: new THREE.Scene(), placed: new Map(), pendingUrls: new Set(), loadedCount: 0, totalCount: 0, disposed: false,
      apartment: r.apartment, catalogue: r.catalogue, quality: { name: "desktop", preloadRooms: 9 }, events: {},
      pos: new THREE.Vector2(200, 200), currentRoom: null, outline: null, selectedSlot: null, _bb: new THREE.Box3(),
      meshes: { load: () => Promise.reject(new Error("нет сети")) },
      kitCtx: { materials: createMaterialCtx(1, false), byId: (id: string) => r.catalogue.materials.find((m) => m.id === id),
        fallback: r.catalogue.materials[0]! },
    });
    const frame = (): THREE.Vector3 => (v as unknown as { outline: THREE.LineSegments }).outline.scale;
    await v.syncObjects(resolveScene(r.apartment, r.catalogue, cfg));
    v.highlight("ковёр#0");
    expect(frame().x).toBeCloseTo(2.3 * 1.04, 6);
    await v.syncObjects(resolveScene(r.apartment, r.catalogue, { ...cfg, selections: { ...cfg.selections, "ковёр#0": "feed:ковёр:k" } }));
    expect(frame().x).toBeCloseTo(2.0 * 1.04, 6);
    expect(frame().z).toBeCloseTo(1.4 * 1.04, 6);
  });
});
