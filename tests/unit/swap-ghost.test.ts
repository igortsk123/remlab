import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { APPEAR_MS, FADE_MS, SILHOUETTE_RGB, SwapGhosts, appearScale, ghostGlow, standsOn } from "@/lib/viewer3d/swap-ghost";

// T-20261112-109: замена товара в 3D без пустоты — прежний предмет на месте, пока грузится новый.
// T-20261113-19 (владелец TG 1567: «5 секунд ждёт, страшно, так черно выглядит»): прежний — НЕПРОЗРАЧНЫЙ светлый силуэт, мягко
// «дышит» светом; вещи на заменяемой (подушки, плед) ждут её и появляются вместе
const item = (): { group: THREE.Group; mat: THREE.MeshStandardMaterial } => {
  const mat = new THREE.MeshStandardMaterial();
  const group = new THREE.Group();
  group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat));
  return { group, mat };
};
const meshMat = (g: THREE.Object3D): THREE.Material => (g.children[0] as THREE.Mesh).material as THREE.Material;

describe("swap-ghost", () => {
  it("«дыхание» спокойное: свечение 0.35…0.65, появление 0.94 → 1", () => {
    const a = Array.from({ length: 50 }, (_, i) => ghostGlow(i * 37));
    expect(Math.min(...a)).toBeGreaterThanOrEqual(0.35 - 1e-9);
    expect(Math.max(...a)).toBeLessThanOrEqual(0.65 + 1e-9);
    expect(appearScale(0)).toBeCloseTo(0.94);
    expect(appearScale(APPEAR_MS)).toBe(1);
    expect(appearScale(APPEAR_MS / 2)).toBeGreaterThan(0.97);
  });

  it("силуэт НЕПРОЗРАЧНЫЙ и светлый (сквозь него ничего не видно), дышит светом; гаснет после прихода новой и уходит", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const old = item();
    scene.add(old.group);
    gh.hold("диван#0", old, true, 0);
    expect(scene.children).toContain(old.group);
    const sil = (): THREE.MeshStandardMaterial => meshMat(old.group) as THREE.MeshStandardMaterial;
    expect(sil()).not.toBe(old.mat);   // общий материал модели не трогаем
    for (const ms of [0, 100, 350, 700, 1050, 4000]) {   // пока ждём — ни кадра прозрачности
      gh.tick(ms);
      expect(sil().transparent).toBe(false);
      expect(sil().opacity).toBe(1);
      expect(sil().color.getHex()).toBe(SILHOUETTE_RGB);
    }
    gh.tick(350);
    const g1 = sil().emissiveIntensity;
    gh.tick(1050);
    expect(Math.abs(sil().emissiveIntensity - g1)).toBeGreaterThan(0.2);   // дышит, а не стоит
    const fresh = new THREE.Group();
    gh.release("диван#0", fresh, 1000);
    expect(fresh.scale.x).toBeCloseTo(0.94);
    gh.tick(1000 + FADE_MS / 2);
    expect(scene.children).toContain(old.group);
    expect(sil().transparent).toBe(true);   // гаснет поверх подрастающей новой
    expect(sil().opacity).toBeCloseTo(0.5, 1);
    gh.tick(1000 + FADE_MS + 1);
    expect(scene.children).not.toContain(old.group);
    expect(gh.has("диван#0")).toBe(false);
    expect(fresh.scale.x).toBe(1);
  });

  it("быстрые замены: на экране одна модель — первая; промежуточная, не успевшая прийти, убирается", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const a = item();
    const b = item();
    scene.add(a.group, b.group);
    gh.hold("стол#0", a, true, 0);
    gh.hold("стол#0", b, false, 50);   // B ещё грузился (невидимая заглушка)
    expect(scene.children).toContain(a.group);
    expect(scene.children).not.toContain(b.group);
    const c = item();
    scene.add(c.group);
    gh.hold("стол#0", c, true, 80);   // даже видимый промежуточный при живом призраке — прочь: двух моделей нет
    expect(scene.children.filter((o) => o === a.group || o === c.group)).toEqual([a.group]);
  });

  it("новая не пришла — прежний предмет целиком, со своим материалом, без мерцания", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const old = item();
    scene.add(old.group);
    gh.hold("кресло#0", old, true, 0);
    gh.tick(300);
    const back = gh.restore("кресло#0");
    expect(back).toBe(old);
    expect(meshMat(old.group)).toBe(old.mat);
    expect(old.mat.transparent).toBe(false);
    expect(old.mat.opacity).toBe(1);
    expect(gh.has("кресло#0")).toBe(false);
    gh.tick(600);
    expect(meshMat(old.group)).toBe(old.mat);
  });

  it("рамка выделения считается по полному размеру подрастающей модели", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const old = item();
    scene.add(old.group);
    gh.hold("ковёр#0", old, true, 0);
    const fresh = item().group;
    gh.release("ковёр#0", fresh, 10);
    const w = gh.atFullSize(fresh, () => new THREE.Box3().setFromObject(fresh).getSize(new THREE.Vector3()).x);
    expect(w).toBeCloseTo(1, 6);
    expect(fresh.scale.x).toBeCloseTo(0.94);
  });

  it("перед сохранённым кадром гаснущие призраки убраны сразу, живые остаются", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const a = item();
    const b = item();
    scene.add(a.group, b.group);
    gh.hold("a", a, true, 0);
    gh.hold("b", b, true, 0);
    gh.release("a", null, 10);
    gh.settle();
    expect(scene.children).not.toContain(a.group);
    expect(scene.children).toContain(b.group);
    gh.disposeAll();
    expect(scene.children).not.toContain(b.group);
  });

  it("вещь стоит на носителе: подушка на сиденье и лампа на комоде — да; картина над диваном, ковёр, сосед — нет", () => {
    const sofa = { x: 200, y: 280, rot: 180, wCm: 162, dCm: 90, hCm: 79, elevCm: 0 };
    expect(standsOn({ x: 180, y: 300, rot: 180, wCm: 45, dCm: 12, hCm: 45, elevCm: 42 }, sofa)).toBe(true);   // подушка
    expect(standsOn({ x: 275, y: 280, rot: 0, wCm: 36, dCm: 55, hCm: 5, elevCm: 60 }, sofa)).toBe(true);     // плед на подлокотнике
    expect(standsOn({ x: 200, y: 322, rot: 180, wCm: 90, dCm: 3, hCm: 60, elevCm: 120 }, sofa)).toBe(false);  // картина выше дивана
    expect(standsOn({ x: 200, y: 280, rot: 0, wCm: 230, dCm: 160, hCm: 1, elevCm: 0 }, sofa)).toBe(false);    // ковёр на полу
    expect(standsOn({ x: 330, y: 280, rot: 0, wCm: 40, dCm: 40, hCm: 50, elevCm: 30 }, sofa)).toBe(false);    // рядом, не на нём
    const chest = { x: 100, y: 50, rot: 90, wCm: 120, dCm: 45, hCm: 80, elevCm: 0 };
    expect(standsOn({ x: 100, y: 90, rot: 90, wCm: 30, dCm: 30, hCm: 50, elevCm: 80 }, chest)).toBe(true);    // лампа, след повёрнут
    expect(standsOn({ x: 140, y: 50, rot: 90, wCm: 30, dCm: 30, hCm: 50, elevCm: 80 }, chest)).toBe(false);
  });

  it("подушки ждут несущую: спрятаны, пока грузится диван, и появляются вместе с ним; не пришёл — показываются без ожидания", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const pillow = item().group;
    expect(gh.follow("диван#0", pillow)).toBe(false);   // носитель не грузится — ждать нечего
    expect(pillow.visible).toBe(true);
    gh.expect("диван#0");
    expect(gh.follow("диван#0", pillow)).toBe(true);
    expect(pillow.visible).toBe(false);
    gh.lead("диван#0", 500);
    expect(pillow.visible).toBe(true);
    expect(pillow.scale.x).toBeCloseTo(0.94);   // подрастает вместе с диваном
    gh.tick(500 + APPEAR_MS);
    expect(pillow.scale.x).toBe(1);
    const other = item().group;
    gh.expect("кресло#0");
    gh.follow("кресло#0", other);
    gh.leadAllExcept(new Set(["диван#0"]), 900);   // новая расстановка кресло больше не грузит
    expect(other.visible).toBe(true);
    expect(other.scale.x).toBe(1);
  });

  it("спрятанная вещь при новой замене силуэтом не становится — её никто не видел", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const p = item();
    scene.add(p.group);
    gh.expect("диван#0");
    gh.follow("диван#0", p.group);
    gh.hold("подушка#0", p, true, 0);
    expect(scene.children).not.toContain(p.group);
    expect(gh.has("подушка#0")).toBe(false);
  });
});
