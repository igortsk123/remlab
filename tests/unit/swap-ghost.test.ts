import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { APPEAR_MS, FADE_MS, SwapGhosts, appearScale, ghostOpacity } from "@/lib/viewer3d/swap-ghost";

// T-20261112-109: замена товара в 3D без пустоты — прежний предмет мерцает призраком, пока грузится новый
const item = (): { group: THREE.Group; mat: THREE.MeshStandardMaterial } => {
  const mat = new THREE.MeshStandardMaterial();
  const group = new THREE.Group();
  group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat));
  return { group, mat };
};
const meshMat = (g: THREE.Object3D): THREE.Material => (g.children[0] as THREE.Mesh).material as THREE.Material;

describe("swap-ghost", () => {
  it("пульс спокойный: прозрачность 0.35…0.75, появление 0.94 → 1", () => {
    const a = Array.from({ length: 50 }, (_, i) => ghostOpacity(i * 37));
    expect(Math.min(...a)).toBeGreaterThanOrEqual(0.35 - 1e-9);
    expect(Math.max(...a)).toBeLessThanOrEqual(0.75 + 1e-9);
    expect(appearScale(0)).toBeCloseTo(0.94);
    expect(appearScale(APPEAR_MS)).toBe(1);
    expect(appearScale(APPEAR_MS / 2)).toBeGreaterThan(0.97);
  });

  it("призрак рисуется копией материала, гаснет после прихода новой и уходит из сцены", () => {
    const scene = new THREE.Scene();
    const gh = new SwapGhosts(scene);
    const old = item();
    scene.add(old.group);
    gh.hold("диван#0", old, true, 0);
    expect(scene.children).toContain(old.group);
    expect(meshMat(old.group)).not.toBe(old.mat);   // общий материал модели не трогаем
    expect(meshMat(old.group).transparent).toBe(true);
    gh.tick(100);
    expect(meshMat(old.group).opacity).toBeLessThan(1);
    const fresh = new THREE.Group();
    gh.release("диван#0", fresh, 1000);
    expect(fresh.scale.x).toBeCloseTo(0.94);
    gh.tick(1000 + FADE_MS / 2);
    expect(scene.children).toContain(old.group);
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
});
