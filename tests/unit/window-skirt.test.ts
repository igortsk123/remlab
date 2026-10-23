import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { buildOpenings } from "@/lib/viewer3d/openings";

// КАЙМА ВИДА ЗА ОКНОМ (demo-27 Г): плоскость вида кончается у конца стены — под углом за её краем была панорама вокруг дома
// (другой, «пиксельный» город) и шов. Кайма — та же картинка в том же месте и масштабе, только дальше и шире: в каждой точке
// стены у плоскости вида и у каймы одна и та же точка картинки, иначе на краю плоскости — ступенька.

const win = { kind: "window", offsetCm: 70, widthCm: 150, sillCm: 85, heightCm: 150 } as never;

/** Точка картинки (uv) плоскости в точке стены (локальные x, y, м): по углам геометрии — линейно. */
function uvAt(m: THREE.Mesh, x: number, y: number): [number, number] {
  const pos = m.geometry.attributes.position as THREE.BufferAttribute, uv = m.geometry.attributes.uv as THREE.BufferAttribute;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, u0 = 0, u1 = 0, v0 = 0, v1 = 0;
  for (let i = 0; i < pos.count; i++) {
    const px = pos.getX(i) + m.position.x, py = pos.getY(i) + m.position.y;
    if (px < x0) { x0 = px; u0 = uv.getX(i); }
    if (px > x1) { x1 = px; u1 = uv.getX(i); }
    if (py < y0) { y0 = py; v0 = uv.getY(i); }
    if (py > y1) { y1 = py; v1 = uv.getY(i); }
  }
  return [u0 + ((x - x0) / (x1 - x0)) * (u1 - u0), v0 + ((y - y0) / (y1 - y0)) * (v1 - v0)];
}

describe("кайма вида за окном", () => {
  const g = buildOpenings([win], "west", { heightCm: 270, lengthCm: 325 });
  const find = (name: string) => { let r: THREE.Mesh | undefined; g.traverse((o) => { if (o.name === name) r = o as THREE.Mesh; }); return r!; };
  const view = find("window-view"), skirt = find("window-view:skirt");

  it("дальше плоскости вида (в её пределах видна она) и шире её на метры", () => {
    expect(skirt.position.z).toBeLessThan(view.position.z);
    const w = (m: THREE.Mesh) => (m.geometry as THREE.PlaneGeometry).parameters.width;
    expect(w(skirt) - w(view)).toBeGreaterThan(10);
  });

  it("в каждой точке плоскости вида — та же точка картинки, что у каймы", () => {
    const p = (view.geometry as THREE.PlaneGeometry).parameters;
    for (const fx of [-0.5, 0, 0.5]) for (const fy of [-0.5, 0.5]) {
      const x = view.position.x + fx * p.width, y = view.position.y + fy * p.height;
      const a = uvAt(view, x, y), b = uvAt(skirt, x, y);
      expect(b[0]).toBeCloseTo(a[0], 6);
      expect(b[1]).toBeCloseTo(a[1], 6);
    }
  });
});
