import { describe, expect, it } from "vitest";

import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { isExtra, planObjects } from "@/lib/viewer3d/build-scene";
import { liveApartment, sceneAssetUrls, sceneMeshUrls } from "@/lib/viewer3d/demo-scene";

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

  it("ваза — на столике, подъём — его высота; без опоры — не в сцене", () => {
    const specs = plan(items, [vase]);
    const v = specs.find((s) => s.kind === "mesh" && s.meshId === "99272_1")!;
    expect(v.placement).toMatchObject({ x: 246, y: 175, elevCm: 35 });
    expect(v.slotId).toBe("decor:ваза#0");
    // без столика и обеденного стола — не в сцене (размер опоры не придумываем)
    expect(plan(items.filter((i) => i.role !== "столик"), [vase]).some((s) => s.kind === "mesh" && s.meshId === "99272_1")).toBe(false);
  });

  it("ваза следует за столиком, который передвинул покупатель; убрал столик — ваза в цене, но не в сцене", () => {
    const b = liveApartment(room, items, "https://remont-lab.online/demo/", [vase])!;
    const cfg = defaultConfiguration(b.apartment, b.catalogue);
    const moved = resolveScene(b.apartment, b.catalogue, { ...cfg, placements: { "столик#0": { x: 300, y: 200, rot: 90 } } });
    expect(moved.items.find((i) => i.slotId === "decor:ваза#0")!.placement).toMatchObject({ x: 300, y: 200, rot: 90, elevCm: 35 });
    const hidden = resolveScene(b.apartment, b.catalogue, { ...cfg, hidden: ["столик#0"] });
    const v = hidden.items.find((i) => i.slotId === "decor:ваза#0")!;
    expect(v.unplaced).toBe(true);
    expect(hidden.totals.upgrades).toBe(resolveScene(b.apartment, b.catalogue, cfg).totals.upgrades - 28990);
  });
});


// ФОНОВАЯ ПОДГРУЗКА НА «ФОТО» (demo-26): страница качает в кэш те же адреса, что потом возьмёт сцена — иначе кэш мимо
describe("живая сцена демо: адреса моделей для подгрузки заранее", () => {
  const rt = { "112923_1": { size: 10, "size-lite": 5, src_sha: "aa", "src_sha-lite": "bb" }, "112923_2": { size: 10, src_sha: "cc" } };
  const vase = { role: "ваза", sku: { msid: "99272_1", name: "Ваза Фьюжн", w: 19.5, d: 19.5, h: 30, price: 2490 } };
  const base = "https://remont-lab.online/demo/";

  it("совпадают с адресами сцены: по одному на модель, ковёр (фото) не качается, ваза на столике — да", () => {
    for (const lite of [false, true]) {
      const urls = sceneMeshUrls({ room, items, decor: [vase], base, runtimeMeshes: rt, lite });
      const b = liveApartment(room, items, base, [vase])!;
      const specs = planObjects(b.apartment, b.catalogue, resolveScene(b.apartment, b.catalogue, defaultConfiguration(b.apartment, b.catalogue)), { lite });
      expect(urls.sort()).toEqual([...new Set(specs.flatMap((s) => (s.kind === "mesh" ? [s.url] : [])))].sort());
      expect(urls).toHaveLength(4); // диван, столик, стул (два места — одна модель), ваза
    }
  });

  it("телефон — лёгкая копия, где она есть; компьютер — полная; нет копии — исходник галереи", () => {
    const lite = sceneMeshUrls({ room, items, base, runtimeMeshes: rt, lite: true });
    const full = sceneMeshUrls({ room, items, base, runtimeMeshes: rt, lite: false });
    expect(lite).toContain("/rt/112923_1-lite.glb?v=bb");
    expect(full).toContain("/rt/112923_1.glb?v=aa");
    expect(lite).toContain("/rt/112923_2.glb?v=cc");
    expect(full).toContain("/test/mesh-pilot10/112923_4/model.glb");
  });

  it("оболочка: транскодер KTX2 (есть копии /rt/), фото ковра, вид за окном, панорама; доп. карты — только в полном режиме", () => {
    const lite = sceneAssetUrls({ room, items, base, runtimeMeshes: rt, lite: true }).shell;
    expect(lite).toEqual(expect.arrayContaining(["/vendor/basis/basis_transcoder.wasm", "https://remont-lab.online/demo/img/rug.jpg",
      "/flat3d/env/outside.webp"]));
    expect(lite.some((u) => u.startsWith("/scene/views/"))).toBe(true);
    const noRt = sceneAssetUrls({ room, items, base, runtimeMeshes: {}, lite: true }).shell;
    expect(noRt.some((u) => u.includes("basis"))).toBe(false);
    const floor = { id: "f1", titleRu: "Пол", titleEn: "Floor", colorHex: "#c8b090", baseColorUrl: "/flat3d/materials/f1.webp", normalUrl: "/flat3d/materials/f1-n.webp", surfaces: ["floor"] };
    expect(sceneAssetUrls({ room, items, base, floor, lite: false }).shell).toContain("/flat3d/materials/f1-n.webp");
    expect(sceneAssetUrls({ room, items, base, floor, lite: true }).shell).not.toContain("/flat3d/materials/f1-n.webp");
  });
});
