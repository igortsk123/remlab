import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { fadeForMove, floorFootprint, footprintArea } from "@/lib/viewer3d/footprint";

// СЛЕД МОДЕЛИ ДЛЯ «ПЕРЕМЕСТИТЬ» (T-20261111-05/5): подсветка места — по самой модели, а не по прямоугольнику габарита.
// У Г-дивана прямоугольник наполовину лежал на пустом полу, и «зелёное не под диваном».

const box = (w: number, h: number, d: number, x: number, z: number): THREE.Mesh => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d));
  m.position.set(x, h / 2, z);
  return m;
};

describe("след модели на полу", () => {
  it("прямоугольный предмет — след равен габариту и стоит по центру", () => {
    const g = new THREE.Group();
    g.add(box(1.4, 0.6, 0.5, 0, 0));
    g.position.set(3, 0, 2);
    const geo = floorFootprint(g)!;
    expect(footprintArea(geo)).toBeCloseTo(1.4 * 0.5, 2);
    geo.computeBoundingBox();
    const c = geo.boundingBox!.getCenter(new THREE.Vector3());
    expect(Math.abs(c.x)).toBeLessThan(0.01);
    expect(Math.abs(c.z)).toBeLessThan(0.01);
    expect(geo.boundingBox!.max.y).toBe(0);
  });

  it("Г-диван: пустой угол буквы «Г» в след не входит", () => {
    const g = new THREE.Group();
    g.add(box(2.0, 0.9, 0.9, 0, -0.3)); // основная часть 2,0 × 0,9 у стены
    g.add(box(0.8, 0.5, 0.6, 0.6, 0.45)); // оттоманка 0,8 × 0,6 вперёд с правого края
    const geo = floorFootprint(g)!;
    const want = 2.0 * 0.9 + 0.8 * 0.6;
    expect(footprintArea(geo)).toBeGreaterThan(want * 0.97);
    expect(footprintArea(geo)).toBeLessThan(want * 1.12);
    expect(footprintArea(geo)).toBeLessThan(2.0 * 1.5 * 0.85); // заметно меньше прямоугольника габарита 2,0 × 1,5
  });

  it("поворот группы на след не влияет (след — в осях предмета), и поворот группе возвращается", () => {
    const g = new THREE.Group();
    g.add(box(1.0, 0.5, 0.4, 0, 0));
    g.rotation.y = Math.PI / 4;
    const geo = floorFootprint(g)!;
    geo.computeBoundingBox();
    const s = geo.boundingBox!.getSize(new THREE.Vector3());
    expect(s.x).toBeCloseTo(1.0, 2);
    expect(s.z).toBeCloseTo(0.4, 2);
    expect(g.rotation.y).toBeCloseTo(Math.PI / 4, 9);
  });

  it("пустая группа — null (вызывающий рисует прямоугольник габарита)", () => {
    expect(floorFootprint(new THREE.Group())).toBeNull();
  });
});

// ПРЕДМЕТ «В РУКЕ» (T-20261111-05/8, владелец TG 1588–1591): модель полупрозрачная и не закрывает след на полу; соседний экземпляр той же
// модели (общий материал) не бледнеет; после переноса всё как было.
describe("предмет в руке при переносе", () => {
  it("копии материалов полупрозрачные, без записи глубины, поверх следа; общий материал не тронут; откат возвращает всё", () => {
    const shared = new THREE.MeshStandardMaterial({ color: 0x886644 });
    const a = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), shared);
    const b = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), shared);   // второй стул той же модели — не в группе
    const g = new THREE.Group();
    g.add(a);
    const undo = fadeForMove(g, 0.3, 999);
    const f = a.material as THREE.MeshStandardMaterial;
    expect(f).not.toBe(shared);
    expect(f.transparent).toBe(true);
    expect(f.opacity).toBeCloseTo(0.3, 6);
    expect(f.depthWrite).toBe(false);
    expect(a.renderOrder).toBe(999);
    expect(b.material).toBe(shared);
    expect(shared.transparent).toBe(false);
    expect(shared.opacity).toBe(1);
    undo();
    expect(a.material).toBe(shared);
    expect(a.renderOrder).toBe(0);
  });
  it("уже полупрозрачный материал (стекло) становится ещё прозрачнее, а не непрозрачным; массив материалов — каждый", () => {
    const glass = new THREE.MeshStandardMaterial({ transparent: true, opacity: 0.5 });
    const wood = new THREE.MeshStandardMaterial();
    const m = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), [glass, wood]);
    const undo = fadeForMove(m, 0.3, 999);
    const list = m.material as THREE.MeshStandardMaterial[];
    expect(list[0]!.opacity).toBeCloseTo(0.15, 6);
    expect(list[1]!.opacity).toBeCloseTo(0.3, 6);
    undo();
    expect(m.material).toEqual([glass, wood]);
  });
});
