import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { fallbackMeshColor, placeMesh } from "@/lib/viewer3d/meshes";

// ЧЁРНЫЕ МОДЕЛИ (план demo-05 п.3): карта цвета товара не пришла → предмет не должен стать чёрным. Подмена — только
// почти чёрный цвет БЕЗ живой карты; настоящий тёмный товар (с картой или просто тёмно-серый) не трогаем.

const BLACK = new THREE.Color(0, 0, 0);
const TINT: [number, number, number] = [0.6, 0.55, 0.5];

function mapWith(width: number, height: number): THREE.Texture {
  const t = new THREE.Texture();
  t.image = { width, height };
  return t;
}

describe("fallbackMeshColor — когда подставлять запасной цвет", () => {
  it("нет карты, цвет чёрный, подкраски нет → светло-серый", () => {
    const c = fallbackMeshColor({ color: BLACK.clone(), map: null });
    expect(c).not.toBeNull();
    expect(c!.getHexString()).toBe("c9c9c6");
  });

  it("нет карты, цвет чёрный, есть подкраска товара → цвет товара", () => {
    const c = fallbackMeshColor({ color: BLACK.clone(), map: null }, TINT);
    expect(c!.toArray()).toEqual(TINT);
  });

  it("карта есть, но картинка не пришла (пустая) → запасной цвет", () => {
    expect(fallbackMeshColor({ color: BLACK.clone(), map: new THREE.Texture() })).not.toBeNull();
    expect(fallbackMeshColor({ color: BLACK.clone(), map: mapWith(0, 0) })).not.toBeNull();
  });

  it("чёрный диван С живой картой — не трогаем", () => {
    expect(fallbackMeshColor({ color: BLACK.clone(), map: mapWith(1024, 1024) })).toBeNull();
  });

  it("светлый цвет без карты (GLTFLoader после отказа: baseColorFactor белый) — не трогаем", () => {
    expect(fallbackMeshColor({ color: new THREE.Color(1, 1, 1), map: null })).toBeNull();
  });

  it("тёмно-серый без карты (графит, sRGB #333) — настоящий цвет, не трогаем", () => {
    expect(fallbackMeshColor({ color: new THREE.Color("#333333"), map: null })).toBeNull();
  });

  it("у материала нет цвета вовсе — не трогаем", () => {
    expect(fallbackMeshColor({ map: null })).toBeNull();
  });
});

describe("placeMesh — запасной цвет в сцене", () => {
  const spot = { xCm: 100, yCm: 100, rotDeg: 0, wCm: 100, dCm: 50, hCm: 80 };
  const colorOf = (g: THREE.Group): THREE.MeshStandardMaterial => {
    let mat: THREE.MeshStandardMaterial | null = null;
    g.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) mat = (o as THREE.Mesh).material as THREE.MeshStandardMaterial;
    });
    return mat!;
  };

  it("чёрная модель с пустой картой → цвет товара как есть (без повторного умножения), карта снята, исходник цел", () => {
    const src = new THREE.MeshStandardMaterial({ color: 0x000000, map: new THREE.Texture() });
    const g = placeMesh(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), src), { ...spot, tintRgb: TINT });
    const mat = colorOf(g);
    expect(mat.color.toArray()).toEqual(TINT);
    expect(mat.map).toBeNull();
    expect(src.color.getHex()).toBe(0x000000); // исходник в кэше загрузчика не испорчен
  });

  it("обычная модель с подкраской — подкраска умножается, как раньше", () => {
    const src = new THREE.MeshStandardMaterial({ color: 0xffffff });
    const mat = colorOf(placeMesh(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), src), { ...spot, tintRgb: TINT }));
    expect(mat.color.toArray()).toEqual(TINT);
    expect(mat).not.toBe(src);
  });

  it("обычная модель без подкраски — материал общий, не клонируется", () => {
    const src = new THREE.MeshStandardMaterial({ color: 0xffffff });
    expect(colorOf(placeMesh(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), src), spot))).toBe(src);
  });
});
