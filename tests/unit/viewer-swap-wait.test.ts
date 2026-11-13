import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { fromDemoVariant } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { SwapGhosts } from "@/lib/viewer3d/swap-ghost";
import { FlatViewer } from "@/lib/viewer3d/viewer";

// ЗАМЕНА ДИВАНА В 3D НА ТЕЛЕФОНЕ (T-20261113-19, владелец TG 1566–1567: «5 секунд ждёт, страшно, так черно выглядит»): пока новая
// модель качается — прежний диван светлым непрозрачным силуэтом, тень под ним пересчитана сразу (без чёрного пятна), подушки на
// диване ждут его и появляются вместе; модель не пришла — прежний диван целиком и сигнал странице. Без WebGL: сцена и карта предметов.

const pillow = (sid: string, hex: string, x: number) => ({ role: "подушка", strategy: "textile_abstract",
  sku: { name: "Подушка " + sid, price: 990, sid }, look: { hex, of: sid }, place: { kind: "pillow", x, y: 300, rot: 180, elev_cm: 42 } });
const data = {
  room: { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [] },
  variants: [{ id: "v", title: "Сканди", style: "сканди", items: [
    { role: "диван", x: 166, y: 280, rot: 180, w: 162, d: 90, h: 79, sku: { name: "Диван", price: 54990, msid: "112923_1" } },
  ], decor: [pillow("p1", "#aa5500", 140), pillow("p2", "#335577", 195)] }],
  feeds: { диван: [{ name: "Новый диван", sid: "n", msid: "112923_2", img: "img/n.jpg", w: 170, d: 92, h: 82, price: 64990, url: "u",
    shop: "divan.ru", src: "pool", styles: ["сканди"] }] },
};
const CTX = { apartmentId: "flat215", partnerId: "demo", currency: "RUB" as const, basePrice: 9_578_200 };

type Load = { url: string; ok: (o: THREE.Object3D) => void; fail: (e: Error) => void };
const model = (): THREE.Object3D => {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.BoxGeometry(1, 0.8, 0.9), new THREE.MeshStandardMaterial({ color: 0x886655 })));
  return g;
};

function headless() {
  const r = fromDemoVariant(data, "v", CTX)!;
  const v = Object.create(FlatViewer.prototype) as FlatViewer;
  const scene = new THREE.Scene();
  const loads: Load[] = [];
  const bakes: number[] = [];
  const failed: string[] = [];
  Object.assign(v, {
    scene, ghosts: new SwapGhosts(scene), waitFor: new Map(), placed: new Map(), pendingUrls: new Set(), loadedCount: 0, totalCount: 0,
    disposed: false, apartment: r.apartment, catalogue: r.catalogue, quality: { name: "desktop", preloadRooms: 9 },
    events: { onSwapFailed: (id: string) => failed.push(id) },
    pos: new THREE.Vector2(200, 200), currentRoom: null, outline: null, selectedSlot: null, _bb: new THREE.Box3(),
    contact: { schedule: () => bakes.push(loads.length) },
    meshes: { load: (url: string) => new Promise<THREE.Object3D>((ok, fail) => loads.push({ url, ok, fail })) },
    kitCtx: { materials: createMaterialCtx(1, false), byId: (id: string) => r.catalogue.materials.find((m) => m.id === id),
      fallback: r.catalogue.materials[0]! },
  });
  const placed = (v as unknown as { placed: Map<string, { group: THREE.Object3D; status: string }> }).placed;
  const cfg = defaultConfiguration(r.apartment, r.catalogue);
  const sofaSlot = r.apartment.slots.find((s) => s.id.startsWith("диван"))!.id;
  const newSofa = r.catalogue.options.find((o) => o.id.includes("feed:диван"))!.id;
  const pillows = (): THREE.Object3D[] => [...placed.entries()].filter(([id]) => id.includes("подушк")).map(([, p]) => p.group);
  return { v, r, scene, loads, bakes, failed, placed, cfg, sofaSlot, newSofa, pillows };
}
const tick = (): Promise<void> => new Promise((ok) => setTimeout(ok, 0));
const sil = (g: THREE.Object3D): THREE.MeshStandardMaterial | null => {
  let m: THREE.MeshStandardMaterial | null = null;
  g.traverse((o) => { const x = o as THREE.Mesh; if (x.isMesh && !m) m = x.material as THREE.MeshStandardMaterial; });
  return m;
};

describe("замена дивана в 3D: силуэт, тень, подушки вместе с диваном", () => {
  it("подушки на диване (в данных их две) — их вещи по геометрии", () => {
    const h = headless();
    expect(h.r.apartment.slots.filter((s) => s.id.includes("подушк")).length).toBe(2);
  });

  it("первая сборка: подушки спрятаны, пока грузится диван, появляются вместе с ним", async () => {
    const h = headless();
    const done = h.v.syncObjects(resolveScene(h.r.apartment, h.r.catalogue, h.cfg));
    await tick();
    expect(h.loads.length).toBe(1);
    expect(h.pillows().length).toBe(2);
    expect(h.pillows().every((g) => !g.visible)).toBe(true);
    h.loads[0]!.ok(model());
    await done;
    expect(h.pillows().every((g) => g.visible)).toBe(true);
  });

  it("замена: прежний — светлый непрозрачный силуэт, тень сразу без него, подушки ждут новый диван", async () => {
    const h = headless();
    const first = h.v.syncObjects(resolveScene(h.r.apartment, h.r.catalogue, h.cfg));
    await tick();
    h.loads[0]!.ok(model());
    await first;
    const oldSofa = h.placed.get(h.sofaSlot)!.group;
    const bakesBefore = h.bakes.length;
    const swap = h.v.syncObjects(resolveScene(h.r.apartment, h.r.catalogue,
      { ...h.cfg, selections: { ...h.cfg.selections, [h.sofaSlot]: h.newSofa } }));
    await tick();
    expect(h.loads.length).toBe(2);   // новая модель качается
    expect(h.scene.children).toContain(oldSofa);
    const m = sil(oldSofa)!;
    expect(m.transparent).toBe(false);   // сквозь прежний диван ничего не видно — ни стены, ни тени на полу
    expect(m.opacity).toBe(1);
    expect(h.bakes.length).toBeGreaterThan(bakesBefore);   // тень пересчитана ДО прихода новой модели — без прежнего дивана
    expect(h.pillows().every((g) => !g.visible)).toBe(true);
    h.loads[1]!.ok(model());
    await swap;
    expect(h.pillows().every((g) => g.visible)).toBe(true);
    expect(h.placed.get(h.sofaSlot)!.status).toBe("loaded");
  });

  it("новая модель не пришла — прежний диван целиком, подушки на месте, странице — сигнал", async () => {
    const h = headless();
    const first = h.v.syncObjects(resolveScene(h.r.apartment, h.r.catalogue, h.cfg));
    await tick();
    h.loads[0]!.ok(model());
    await first;
    const oldSofa = h.placed.get(h.sofaSlot)!.group;
    const swap = h.v.syncObjects(resolveScene(h.r.apartment, h.r.catalogue,
      { ...h.cfg, selections: { ...h.cfg.selections, [h.sofaSlot]: h.newSofa } }));
    await tick();
    h.loads[1]!.fail(new Error("нет сети"));
    await swap;
    expect(h.placed.get(h.sofaSlot)!.group).toBe(oldSofa);
    expect(sil(oldSofa)!.color.getHex()).toBe(0x886655);
    expect(h.pillows().every((g) => g.visible)).toBe(true);
    expect(h.failed).toEqual([h.sofaSlot]);
  });
});
