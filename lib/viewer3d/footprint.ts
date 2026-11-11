// След модели на полу — подсветка места при «Переместить» (T-20261111-05/5).
//
// Прямоугольник габарита у Г-дивана с оттоманкой наполовину ложился на пустой пол (угол буквы «Г» пуст), и владелец видел
// «зелёное не под диваном». След строим по САМОЙ модели: треугольники проецируем на пол, закрашиваем клетки сетки, ряды
// клеток сливаем в полосы без наложений (прозрачная заливка не темнеет на стыках). Годится для любой модели и набора.

import * as THREE from "three";

/**
 * Предмет «в руке» при переносе (T-20261111-05/8, как в Sims 2): модель полупрозрачная (`alpha` от её прозрачности), глубину не пишет
 * и рисуется после следа (`order`), поэтому след на полу под ней виден целиком. Материалы КОПИРУЮТСЯ: одна модель в сцене бывает
 * дважды (два одинаковых стула) с общими материалами — второй экземпляр бледнеть не должен. → функция, возвращающая всё как было.
 */
export function fadeForMove(obj: THREE.Object3D, alpha: number, order: number): () => void {
  const undo: (() => void)[] = [];
  obj.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh || !m.material) return;
    const orig = m.material, ro = m.renderOrder;
    const fade = (x: THREE.Material): THREE.Material => {
      const c = x.clone();
      c.transparent = true;
      c.opacity = Math.min(1, x.opacity ?? 1) * alpha;
      c.depthWrite = false;
      c.needsUpdate = true;
      return c;
    };
    const made = Array.isArray(orig) ? orig.map(fade) : fade(orig);
    m.material = made;
    m.renderOrder = order;
    undo.push(() => {
      (Array.isArray(made) ? made : [made]).forEach((c) => c.dispose());
      m.material = orig;
      m.renderOrder = ro;
    });
  });
  return () => undo.forEach((f) => f());
}

/** Клеток по длинной стороне: ~8 см у дивана 2 м — угол «Г» и ножки читаются, геометрия — сотни полос, не тысячи. */
const CELLS = 24;

/**
 * След объекта на полу в его собственных осях (поворот вокруг вертикали не учитывается, начало — точка объекта),
 * плоскость y = 0. Пусто (нет треугольников) — null.
 */
export function floorFootprint(obj: THREE.Object3D, cells = CELLS): THREE.BufferGeometry | null {
  const yaw = obj.rotation.y;
  obj.rotation.y = 0;
  obj.updateMatrixWorld(true);
  const at = obj.getWorldPosition(new THREE.Vector3());
  const tris: number[] = [];
  const v = new THREE.Vector3();
  obj.traverse((o) => {
    const m = o as THREE.Mesh;
    const pos = m.isMesh ? (m.geometry?.getAttribute("position") as THREE.BufferAttribute | undefined) : undefined;
    if (!pos || !m.visible) return;
    const idx = m.geometry.getIndex();
    const n = idx ? idx.count : pos.count;
    for (let k = 0; k < n; k++) {
      v.fromBufferAttribute(pos, idx ? idx.getX(k) : k).applyMatrix4(m.matrixWorld);
      tris.push(v.x - at.x, v.z - at.z);
    }
  });
  obj.rotation.y = yaw;
  obj.updateMatrixWorld(true);
  if (tris.length < 6) return null;

  let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
  for (let k = 0; k < tris.length; k += 2) {
    x0 = Math.min(x0, tris[k]!); x1 = Math.max(x1, tris[k]!);
    z0 = Math.min(z0, tris[k + 1]!); z1 = Math.max(z1, tris[k + 1]!);
  }
  const step = Math.max(x1 - x0, z1 - z0, 1e-4) / cells;
  const nx = Math.max(1, Math.ceil((x1 - x0) / step)), nz = Math.max(1, Math.ceil((z1 - z0) / step));
  const grid = new Uint8Array(nx * nz);
  const cell = (x: number, z: number): void => {
    const i = Math.min(nx - 1, Math.max(0, Math.floor((x - x0) / step)));
    const j = Math.min(nz - 1, Math.max(0, Math.floor((z - z0) / step)));
    grid[j * nx + i] = 1;
  };
  // треугольник закрашиваем точками с шагом в полклетки: крупный плоский треугольник (сиденье) не оставляет дыр
  for (let k = 0; k + 5 < tris.length; k += 6) {
    const ax = tris[k]!, az = tris[k + 1]!, bx = tris[k + 2]!, bz = tris[k + 3]!, cx = tris[k + 4]!, cz = tris[k + 5]!;
    const span = Math.max(Math.hypot(bx - ax, bz - az), Math.hypot(cx - ax, cz - az), Math.hypot(cx - bx, cz - bz));
    const s = Math.max(1, Math.ceil((span / step) * 2));
    for (let a = 0; a <= s; a++) {
      for (let b = 0; a + b <= s; b++) {
        const u = a / s, w = b / s;
        cell(ax + (bx - ax) * u + (cx - ax) * w, az + (bz - az) * u + (cz - az) * w);
      }
    }
  }

  // ряды занятых клеток → полосы (два треугольника на полосу)
  const out: number[] = [];
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; ) {
      if (!grid[j * nx + i]) { i++; continue; }
      let e = i;
      while (e + 1 < nx && grid[j * nx + e + 1]) e++;
      const ax = x0 + i * step, bx = Math.min(x1, x0 + (e + 1) * step);
      const az = z0 + j * step, bz = Math.min(z1, z0 + (j + 1) * step);
      out.push(ax, 0, az, ax, 0, bz, bx, 0, bz, ax, 0, az, bx, 0, bz, bx, 0, az);
      i = e + 1;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
  return geo;
}

/** Площадь следа, м² — для проверок. */
export function footprintArea(geo: THREE.BufferGeometry): number {
  const p = geo.getAttribute("position");
  let s = 0;
  for (let k = 0; k + 2 < p.count; k += 3) {
    const ax = p.getX(k), az = p.getZ(k), bx = p.getX(k + 1), bz = p.getZ(k + 1), cx = p.getX(k + 2), cz = p.getZ(k + 2);
    s += Math.abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2;
  }
  return s;
}
