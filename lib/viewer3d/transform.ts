// Мировые координаты предмета — ЧИСТАЯ математика, общая для 3D и фото.
//
// Это тот же порядок, что в серверном рендере (`tools/scout/scene_mesh.py:61-83`), записанный
// без three.js, чтобы его можно было сверить тестом с эталоном из Python
// (`tests/unit/configurator-transform.test.ts`). Расхождение здесь означает, что кадр перестал
// соответствовать сцене — это ловится числами, а не глазами.
//
// Порядок: выравнивание фронта ry(−yaw) → масштаб по трём осям в паспортные Ш×В×Г →
// поворот расстановки ry(rot) → перенос в точку (центр footprint, низ на полу + elev).

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface TransformPlacement {
  xCm: number;
  yCm: number;
  rotDeg: number;
  wCm: number;
  dCm: number;
  hCm: number;
  elevCm?: number;
  yawDeg?: number;
}

function ry(v: Vec3, deg: number): Vec3 {
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return { x: c * v.x + s * v.z, y: v.y, z: -s * v.x + c * v.z };
}

/**
 * Мировые вершины (сантиметры) для набора вершин исходной модели.
 * Возвращает координаты в системе квартиры: x — вправо, y — вверх, z — вглубь.
 */
export function worldVertices(source: Vec3[], p: TransformPlacement): Vec3[] {
  const yaw = p.yawDeg ?? 0;
  const aligned = source.map((v) => ry(v, -yaw));

  const min = { x: Infinity, y: Infinity, z: Infinity };
  const max = { x: -Infinity, y: -Infinity, z: -Infinity };
  for (const v of aligned) {
    min.x = Math.min(min.x, v.x);
    min.y = Math.min(min.y, v.y);
    min.z = Math.min(min.z, v.z);
    max.x = Math.max(max.x, v.x);
    max.y = Math.max(max.y, v.y);
    max.z = Math.max(max.z, v.z);
  }
  const ext = { x: max.x - min.x, y: max.y - min.y, z: max.z - min.z };
  const s = {
    x: p.wCm / Math.max(ext.x, 1e-6),
    y: p.hCm / Math.max(ext.y, 1e-6),
    z: p.dCm / Math.max(ext.z, 1e-6),
  };
  const elev = p.elevCm ?? 0;

  return aligned.map((v) => {
    const centred = {
      x: (v.x - min.x - ext.x / 2) * s.x,
      y: (v.y - min.y - ext.y / 2) * s.y + p.hCm / 2,
      z: (v.z - min.z - ext.z / 2) * s.z,
    };
    const rotated = ry(centred, p.rotDeg);
    return { x: p.xCm + rotated.x, y: elev + rotated.y, z: p.yCm + rotated.z };
  });
}

/** Направление «лица» предмета в мире: rot 0 → +y (канон планировщика). */
export function frontDirection(rotDeg: number): { x: number; y: number } {
  const r = (rotDeg * Math.PI) / 180;
  return { x: Math.sin(r), y: Math.cos(r) };
}
