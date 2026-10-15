import { describe, expect, it } from "vitest";

import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { isExtra, planObjects } from "@/lib/viewer3d/build-scene";
import { liveApartment } from "@/lib/viewer3d/demo-scene";

// ЖИВАЯ СЦЕНА ДЕМО (план demo-01): расстановка страницы → квартира и каталог движка. Без WebGL: проверяем то, что
// уходит в сцену, — все предметы на местах, ковёр фотографией на полу, свои стены и пол (живая проверка 14.10:
// без них на стены ложилось фото ковра), лёгкие копии моделей по таблице.

const room = { w: 439, d: 325, title: "Гостиная", openings: [{ kind: "window", wall: "west", offset_cm: 40, width_cm: 150, sill_cm: 85, height_cm: 150 },
  { kind: "door", wall: "east", offset_cm: 230, width_cm: 90 }] };
const items = [
  { role: "диван", x: 169, y: 78, rot: 0, w: 175, d: 155, h: 92, sku: { msid: "112923_1", yaw: 90, name: "Диван", price: 67990 } },
  { role: "столик", x: 246, y: 175, rot: 0, w: 75, d: 75, h: 35, sku: { msid: "112923_2", name: "Столик", price: 28990 } },
  { role: "ковёр", x: 216, y: 150, rot: 0, w: 230, d: 160, sku: { msid: "112923_3", img: "img/rug.jpg", name: "Ковёр", price: 9291 } },
  { role: "стул", x: 330, y: 45, rot: 90, w: 49, d: 53, h: 82, sku: { msid: "112923_4", name: "Стул", price: 5000 } },
  { role: "стул 2", x: 399, y: 114, rot: 180, w: 49, d: 53, h: 82, sku: { msid: "112923_4", name: "Стул", price: 5000 } },
];

describe("живая сцена демо: расстановка → квартира движка", () => {
  const built = liveApartment(room, items, "https://remont-lab.online/demo/")!;
  const scene = resolveScene(built.apartment, built.catalogue, defaultConfiguration(built.apartment, built.catalogue));
  const specs = planObjects(built.apartment, built.catalogue, scene);

  it("каждый предмет — на своём месте, ковёр — плита с фото товара", () => {
    const mesh = specs.filter((s) => s.kind === "mesh");
    expect(mesh.map((s) => s.slotId).sort()).toEqual(["диван#0", "стул 2#0", "стул#0", "столик#0"].sort());
    const sofa = mesh.find((s) => s.slotId === "диван#0")!;
    expect(sofa.placement).toMatchObject({ x: 169, y: 78, rot: 0, wCm: 175, dCm: 155, hCm: 92 });
    expect(sofa.kind === "mesh" && sofa.yawDeg).toBe(90);
    const rug = specs.find((s) => s.kind === "rug")!;
    expect(rug.placement).toMatchObject({ x: 216, y: 150, wCm: 230, dCm: 160 });
    const rugMat = built.catalogue.materials.find((m) => m.id.startsWith("rug:"))!;
    expect(rugMat.baseColorUrl).toBe("https://remont-lab.online/demo/img/rug.jpg");
    expect(rugMat.tileCm).toEqual([230, 160]);
  });

  it("стены и пол — свои материалы, а не первый попавшийся (фото ковра)", () => {
    const surf = Object.fromEntries(scene.surfaces.map((s) => [s.surface, s.material.id]));
    expect(surf).toMatchObject({ floor: "demo-floor", wall: "paint-white" });
    expect(built.catalogue.materials[0]!.id).toBe("paint-white");
  });
});

// ТВ И ВАЗА — КАК НА СЕРВЕРНОМ КАДРЕ (demo-05 п.9, 14.10: в живой сцене их не было)
describe("живая сцена демо: авто-ТВ и декор", () => {
  const stand = { role: "тв-тумба", x: 220, y: 300, rot: 180, w: 139, d: 41, h: 62, sku: { msid: "112923_5", name: "ТВ-тумба Теджонс 139x62", price: 19990 } };
  const vase = { role: "ваза", sku: { msid: "99272_1", name: "Ваза Фьюжн", w: 19.5, d: 19.5, h: 30, price: 2490 } };
  const plan = (its: typeof items, decor: (typeof vase)[] = []) => {
    const b = liveApartment(room, its, "https://remont-lab.online/demo/", decor)!;
    return planObjects(b.apartment, b.catalogue, resolveScene(b.apartment, b.catalogue, defaultConfiguration(b.apartment, b.catalogue)));
  };

  it("над тумбой — телевизор по расстоянию до дивана, на тумбе, производный (не выбирается)", () => {
    const specs = plan([...items, stand]);
    const tv = specs.find((s) => s.kind === "tv")!;
    expect(tv).toBeDefined();
    expect(isExtra(tv.slotId)).toBe(true);
    expect(tv.placement).toMatchObject({ x: 220, y: 300, rot: 180, elevCm: 62, dCm: 22 });
    expect(tv.placement.wCm).toBeLessThanOrEqual(139 * 0.9);
    expect(plan(items).some((s) => s.kind === "tv")).toBe(false); // тумбы нет — телевизора нет
  });

  it("подвесная тумба поднимается на 40 см, телевизор — на стене над ней", () => {
    const hung = { ...stand, h: 30, sku: { ...stand.sku, name: "ТВ-тумба подвесная Харис 160x30" } };
    const specs = plan([...items, hung]);
    expect(specs.find((s) => s.slotId === "тв-тумба#0")!.placement.elevCm).toBe(40);
    const tv = specs.find((s) => s.kind === "tv")!;
    expect(tv.kind === "tv" && tv.hung).toBe(true);
    expect(tv.placement.elevCm).toBeGreaterThanOrEqual(80);
  });

  it("ваза — на столике, подъём — его высота; не выбирается и не мешает прогулке", () => {
    const specs = plan(items, [vase]);
    const v = specs.find((s) => s.kind === "mesh" && s.meshId === "99272_1")!;
    expect(v.placement).toMatchObject({ x: 246, y: 175, elevCm: 35 });
    expect(isExtra(v.slotId)).toBe(true);
    // без столика и обеденного стола — не в сцене (размер опоры не придумываем)
    expect(plan(items.filter((i) => i.role !== "столик"), [vase]).some((s) => s.kind === "mesh" && s.meshId === "99272_1")).toBe(false);
  });
});

