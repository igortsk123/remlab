import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { room as roomSchema } from "@/contracts/apartment";
import type { Material } from "@/contracts/configurator";
import { fromDemoVariant, isTextileDecor } from "@/lib/configurator/fromDemo";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { roomCurtains } from "@/lib/configurator/curtains";
import { planObjects, productCurtains } from "@/lib/viewer3d/build-scene";
import { sceneSlotIndex } from "@/lib/viewer3d/demo-scene";
import { buildPillow, buildProductCurtain, buildThrow, SHEER_OPACITY } from "@/lib/viewer3d/kits/textile";
import { createMaterialCtx } from "@/lib/viewer3d/materials";
import { chooseAim, seeThroughWins } from "@/lib/viewer3d/walk-aim";
import { buildCurtains, curtainPanels } from "@/lib/viewer3d/window-light";

// УСЛОВНЫЕ ШТОРЫ И ПЛЕД ЦВЕТОМ ТОВАРА (T-20261112-74, владелец TG 953): место и цвет — от сборки витрины
// (`tools/scout/textile_abstract.py`), в 3D — простая форма с ценой и карточкой; без места или цвета — только в списке, как было

const CTX = { apartmentId: "t", partnerId: "demo", currency: "RUB" as const, basePrice: 0, assetBase: "/demo/demo-data.json" };
const SOFA = { role: "диван", x: 200, y: 280, rot: 180, w: 200, d: 90, h: 80, sku: { name: "Диван", price: 50000, msid: "s_1" } };
const WIN = { kind: "window", wall: "west", offset_cm: 70, width_cm: 150, sill_cm: 85, height_cm: 150 };
const DOOR = { kind: "door", wall: "east", offset_cm: 20, width_cm: 90 };
const GEO = { w: 439, d: 325, title: "Гостиная", height_cm: 270, openings: [DOOR, WIN] };
const curtain = (look: object, extra: object = {}) => ({ role: "шторы", strategy: "textile_abstract",
  place: { x: 0, y: 145, rot: 90, elev_cm: 247.5, slot_instance_id: "textile.curtains#0", kind: "curtain", opening: 1, wall: "west" },
  look, sku: { name: "Тюль Кассандра экрю", price: 4990, sid: "c1", img: "img/c1.jpg", w: 300, h: 260 }, ...extra });
const THROW = { role: "плед", strategy: "textile_abstract",
  place: { x: 56.3, y: 280, rot: 180, elev_cm: 60, slot_instance_id: "soft.throw#0", kind: "throw", edge: "arm_right", w: 36, d: 55, h: 5 },
  look: { hex: "#b8644a", from: "name:терракот", sheer: false, of: "t1" }, sku: { name: "Плед терракотовый", price: 2990, sid: "t1" } };
const TULLE = curtain({ hex: "#e6dcc6", from: "name:экрю", sheer: true, of: "c1" });
const pillow = (role: string, sid: string, name: string, price: number, msid: string | null, dims: object) => ({ role,
  strategy: "textile_abstract", place: { x: 180, y: 289.5, rot: 180, elev_cm: 45, slot_instance_id: `soft.pillows#${role.endsWith("2") ? 1 : 0}`,
    parent: "seating.sofa#0", kind: "pillow", ...dims },
  look: { hex: "#d8c4a6", from: "name:бежев", sheer: false, of: sid }, sku: { name, price, sid, ...(msid ? { msid } : {}), w: 45, d: 45, h: 11 } });
const PILLOW_MESH = pillow("подушка", "p1", "Подушка Линкс бежевая", 1290, "m_p1", { w: 45, d: 16.3, h: 44.2 });
const PILLOW_ABS = pillow("подушка 2", "p2", "Подушка Удина серая", 990, null, { w: 45, d: 11, h: 45 });

const build = (decor: object[]) => fromDemoVariant({ room: GEO, variants: [{ id: "v", style: "сканди", items: [SOFA], decor }] } as never, "v", CTX)!;
const MAT = { id: "x", titleRu: "", titleEn: "", colorHex: "#cccccc", roughness: 0.8, metalness: 0, tileCm: [100, 100], surfaces: [] } as unknown as Material;

describe("условная ткань: мост витрины → места сцены", () => {
  it("без места, без цвета или «только в списке» — не ткань сцены", () => {
    expect(isTextileDecor(TULLE)).toBe(true);
    expect(isTextileDecor({ ...TULLE, look: {} })).toBe(false);
    expect(isTextileDecor({ ...TULLE, place: undefined })).toBe(false);
    expect(isTextileDecor({ ...TULLE, list_only: true })).toBe(false);
    expect(isTextileDecor({ ...TULLE, place: { ...TULLE.place, opening: null } })).toBe(false);
    expect(isTextileDecor({ ...TULLE, strategy: undefined })).toBe(false);
    expect(isTextileDecor(THROW)).toBe(true);
    // покупатель заменил штору: цвет посчитан для прежнего товара — новая только в списке
    expect(isTextileDecor({ ...TULLE, sku: { name: "Штора Пайнон", sid: "c2" } })).toBe(false);
    expect(isTextileDecor({ ...TULLE, sku: { name: "Тюль Кассандра экрю" }, look: { ...TULLE.look, of: "Тюль Кассандра экрю" } })).toBe(true);
  });

  it("штора — слот у своего окна, цвет товара, тюль прозрачный, цена и пометка «вид условный»", () => {
    const { apartment, catalogue } = build([TULLE]);
    const slot = apartment.slots.find((s) => s.textile)!;
    expect(slot.id).toBe("textile:шторы#0");
    // окно — второй проём комнаты (первый — дверь): номер в проёмах моста, а не в сыром списке витрины
    expect(slot.textile).toEqual({ shape: "curtain", opening: 1 });
    const opt = catalogue.options.find((o) => o.id === slot.defaultOptionId)!;
    expect(opt.asset).toMatchObject({ kind: "kit", kit: "textile", features: ["curtain", "sheer"] });
    expect(opt.price).toBe(4990);
    expect(opt.descRu).toContain("вид условный");
    expect(opt.previewUrl).toBe("/demo/img/c1.jpg");
    const body = (opt.asset as { materials: Record<string, string> }).materials.body!;
    expect(catalogue.materials.find((m) => m.id === body)!.colorHex).toBe("#e6dcc6");
    // декоративная штора сцены у этого окна не рисуется — её место заняла штора-товар
    expect([...productCurtains(apartment).get(slot.roomId)!]).toEqual([1]);
  });

  it("сцена рисует штору и плед; без условной ткани — как раньше (шторы только в списке)", () => {
    const { apartment, catalogue } = build([TULLE, THROW]);
    const sc = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
    const specs = planObjects(apartment, catalogue, sc).filter((s) => s.kind === "textile");
    expect(specs.map((s) => s.kind === "textile" && [s.shape, s.sheer])).toEqual([["curtain", true], ["throw", false]]);
    const pl = specs[1]!.placement;
    expect(pl).toMatchObject({ rot: 180, wCm: 36, dCm: 55, hCm: 5, elevCm: 60 });
    const plain = build([{ ...TULLE, strategy: undefined }]);
    expect(plain.apartment.slots.some((s) => s.textile)).toBe(false);
    expect(productCurtains(plain.apartment).size).toBe(0);
  });

  it("подушки на диване (T-20261113-02): с моделью — меш в габарите места, без — условная цветом товара; обе с ценой", () => {
    const { apartment, catalogue } = build([PILLOW_MESH, PILLOW_ABS]);
    const slots = apartment.slots.filter((s) => s.textile?.shape === "pillow");
    expect(slots.map((s) => s.id)).toEqual(["textile:подушка#0", "textile:подушка 2#0"]);
    const [mesh, abs] = slots.map((s) => catalogue.options.find((o) => o.id === s.defaultOptionId)!);
    expect(mesh!.asset).toMatchObject({ kind: "mesh", meshId: "m_p1", wCm: 45, dCm: 16.3, hCm: 44.2 });
    expect(mesh!.descRu).toBe("45×45×11 см");                              // настоящая модель — без «вид условный»
    expect(abs!.asset).toMatchObject({ kind: "kit", kit: "textile", features: ["pillow"] });
    expect(abs!.descRu).toBe("45×45×11 см · вид условный");
    expect([mesh!.price, abs!.price]).toEqual([1290, 990]);
    const sc = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
    const specs = planObjects(apartment, catalogue, sc);
    const tx = specs.find((s) => s.kind === "textile" && s.shape === "pillow")!;
    expect(tx.placement).toMatchObject({ rot: 180, wCm: 45, dCm: 11, hCm: 45, elevCm: 45 });
    expect(specs.some((s) => s.kind === "mesh" && s.slotId === slots[0]!.id)).toBe(true);
    // заменили подушку в списке — цвет посчитан для прежней: в 3D её больше нет (как штора)
    expect(isTextileDecor({ ...PILLOW_ABS, sku: { name: "Подушка Винси", sid: "p9" } })).toBe(false);
  });

  it("номер места сцены → строка декора страницы, id — те же, что у моста", () => {
    const VASE = { role: "ваза", sku: { name: "Ваза", price: 1500, msid: "v_1", w: 15, d: 15, h: 30 } };
    const decor = [VASE, TULLE, THROW, PILLOW_MESH, PILLOW_ABS];
    const m = sceneSlotIndex([SOFA], decor, false);
    expect(m.get("textile:шторы#0")).toBe(1 + 1);
    expect(m.get("textile:плед#0")).toBe(1 + 2);
    expect(m.get("textile:подушка#0")).toBe(1 + 3);
    expect(m.get("textile:подушка 2#0")).toBe(1 + 4);
    const ids = new Set(build(decor).apartment.slots.map((s) => s.id));
    for (const id of m.keys()) expect(ids.has(id)).toBe(true);
  });
});

describe("условная ткань: форма", () => {
  const r = roomSchema.parse({ id: "r", kind: "living", titleRu: "Г", titleEn: "L", x: 0, y: 0, w: 439, d: 325,
    openings: [{ kind: "door", wall: "east", offsetCm: 20, widthCm: 90 },
      { kind: "window", wall: "west", offsetCm: 70, widthCm: 150, sillCm: 85, heightCm: 150 }] });

  it("декоративные шторы пропускают окно со шторой-товаром", () => {
    expect(buildCurtains([r]).children.length).toBe(2);
    expect(buildCurtains([r], new Map([["r", new Set([1])]])).children.length).toBe(0);
  });

  it("тюль — во всю штангу (окно за ним), плотная — по краям окна", () => {
    const span = roomCurtains(r)[1]!;
    const box = (ms: THREE.Mesh[]) => new THREE.Box3().union(ms.reduce((b, m) => b.union(new THREE.Box3().setFromObject(m)), new THREE.Box3()));
    const sheer = box(curtainPanels(r, 1, new THREE.MeshBasicMaterial(), { sheer: true }));
    expect(sheer.min.z * 100).toBeCloseTo(span.rod.u0, 0);
    expect(sheer.max.z * 100).toBeCloseTo(span.rod.u1, 0);
    const dense = curtainPanels(r, 1, new THREE.MeshBasicMaterial());
    expect(dense.length).toBe(span.panels.length);
    expect(curtainPanels(r, 0, new THREE.MeshBasicMaterial())).toEqual([]);   // дверь — не окно
  });

  it("штора-товар в осях своего места стоит там же, где декоративная; тюль полупрозрачный", () => {
    const ctx = { materials: createMaterialCtx(1, false), byId: () => MAT, fallback: MAT };
    const frame = new THREE.Group();
    frame.position.set(0, 0, 1.45);
    frame.rotation.y = Math.PI / 2;
    const g = buildProductCurtain(ctx, r, 1, "x", true, frame);
    frame.add(g);
    const placed = new THREE.Box3().setFromObject(frame);
    const ref = curtainPanels(r, 1, new THREE.MeshBasicMaterial(), { sheer: true }).reduce((b, m) => b.union(new THREE.Box3().setFromObject(m)), new THREE.Box3());
    for (const k of ["x", "y", "z"] as const) {
      expect(placed.min[k]).toBeCloseTo(ref.min[k], 3);
      expect(placed.max[k]).toBeCloseTo(ref.max[k], 3);
    }
    const m = (g.children[0] as THREE.Mesh).material as THREE.MeshStandardMaterial;
    expect(m.transparent && m.opacity).toBe(SHEER_OPACITY);
  });

  it("тап сквозь тюль: за ним окно — «подойти к окну»; за ним стена — выбор шторы; тюль помечен прозрачным для луча", () => {
    const win = { window: 3.05, floor: 6 };
    expect(seeThroughWins(win, 3)).toBe(false);
    expect(chooseAim(win)).toBe("window");
    const wall = { block: 3.05 } as { block: number; item?: number };
    expect(seeThroughWins(wall, 3)).toBe(true);
    expect(chooseAim(wall)).toBe("item");
    expect(seeThroughWins({ item: 2 }, 3)).toBe(false);          // ваза перед тюлем — ваза
    expect(seeThroughWins({ floor: 5 }, undefined)).toBe(false);
    const ctx = { materials: createMaterialCtx(1, false), byId: () => MAT, fallback: MAT };
    const g = (sheer: boolean) => buildProductCurtain(ctx, r, 1, "x", sheer, new THREE.Group()).children.map((m) => !!m.userData.seeThrough);
    expect(g(true).every(Boolean)).toBe(true);
    expect(g(false).some(Boolean)).toBe(false);
  });

  it("условная подушка — мягкий брусок в габарите места, низ на сиденье", () => {
    const ctx = { materials: createMaterialCtx(1, false), byId: () => MAT, fallback: MAT };
    const bb = new THREE.Box3().setFromObject(buildPillow(ctx, { widthCm: 45, depthCm: 11, heightCm: 45, materialId: "x" }));
    expect(bb.max.x - bb.min.x).toBeCloseTo(0.45, 3);
    expect(bb.max.z - bb.min.z).toBeCloseTo(0.11, 3);
    expect(bb.min.y).toBeCloseTo(0, 3);
    expect(bb.max.y).toBeCloseTo(0.45, 3);
  });

  it("плед — брусок на месте и свисающий край спереди, в габарите места по ширине", () => {
    const ctx = { materials: createMaterialCtx(1, false), byId: () => MAT, fallback: MAT };
    const bb = new THREE.Box3().setFromObject(buildThrow(ctx, { widthCm: 36, depthCm: 55, heightCm: 5, materialId: "x" }));
    expect(bb.max.x - bb.min.x).toBeCloseTo(0.36, 3);
    expect(bb.max.y).toBeCloseTo(0.05, 3);
    expect(bb.min.y).toBeLessThan(0);                       // край свисает ниже верха подлокотника
    expect(bb.max.z).toBeGreaterThan(0.275);                // спереди, за краем бруска
  });
});
