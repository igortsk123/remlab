import * as THREE from "three";

import type { Room } from "@/contracts/apartment";

/**
 * СВЕТ ОТ ОКНА (T-20261111-22, владелец TG 1604 «красиво, как на фото»). Солнце стояло в одной точке (-6, 9, -4) при любой
 * комнате — тени ложились «ниоткуда». Теперь оно снаружи первого окна, сверху и чуть сбоку от его оси, и светит в середину
 * квартиры; заполняющий — с противоположной стороны (отражённый от стен свет). Шторы — декоративные льняные полотна по краям
 * окна (флаг `curtains`, по умолчанию вкл.: владелец TG 1643 «Шторы ставь»).
 */

const CM = 0.01;

/**
 * КАЛИБРОВКА СВЕТА по эталону владельца (Планктон, спальня; T-20261111-22/2, владелец TG 1666 «у нас ярче, чем на эталоне; там
 * естественнее»). Числа подобраны замером: тон стены и пола, доля пересвета, перепад «стена у окна / дальний угол» — сценарий
 * `tools/design/mock/light3d/cal.cjs` + `cal.py`, таблица в `~/remlab-logs/t22-1111/s2/`. Пробы HDRI-окружения и света-точки у
 * окна — в истории (коммит «состояние пробы» T-20261111-22/2).
 */
export const LIGHT = {
  // вариант F (совет Codex + экспозиция 0,9): стена L* 92,5 при 88,6 у эталона (было 96), пол 68,7 при 68,4 (было 81,5); ткань
  // кровати L* 44 — не в черноте. HDRI интерьеров Poly Haven (4 шт.) и свет-точка у окна по числам хуже: HDRI пересвечивает белый
  // шкаф и красит стены (отель — синий, lythwood — жёлтый), точка у окна заливает пол (+21 %)
  exposure: 0.9,
  env: 0.42,
  hemi: 0.8, hemiSky: 0xffffff, hemiGround: 0xe6e0d8,
  sun: 1.05, sunColor: 0xfffaf2,
  fill: 0.12,
};

/** Окно в метрах сцены: середина проёма на плоскости стены, нормаль внутрь комнаты, ширина, низ и верх проёма. */
export interface WindowM { x: number; z: number; nx: number; nz: number; w: number; sill: number; top: number; roomH: number }

/** Окна и балконные блоки комнат. Подоконник и высота по умолчанию — как у проёма в стене (`opening-ir.ts:openingIR`). */
export function roomWindows(rooms: readonly Room[]): WindowM[] {
  const out: WindowM[] = [];
  for (const r of rooms) {
    for (const o of r.openings) {
      if (o.kind !== "window" && o.kind !== "balcony") continue;
      // offset — от начала стены: запад→восток у южной/северной, юг→север у западной/восточной (`contracts/apartment.ts:opening`)
      const along = o.offsetCm + o.widthCm / 2;
      const sill = o.kind === "balcony" ? 0 : o.sillCm ?? 90;
      const top = Math.min(r.heightCm, o.kind === "balcony" ? o.heightCm ?? 220 : sill + (o.heightCm ?? 140));
      const at = o.wall === "south" ? { px: r.x + along, pz: r.y, nx: 0, nz: 1 }
        : o.wall === "north" ? { px: r.x + along, pz: r.y + r.d, nx: 0, nz: -1 }
          : o.wall === "west" ? { px: r.x, pz: r.y + along, nx: 1, nz: 0 }
            : { px: r.x + r.w, pz: r.y + along, nx: -1, nz: 0 };
      out.push({ x: at.px * CM, z: at.pz * CM, nx: at.nx, nz: at.nz, w: o.widthCm * CM, sill: sill * CM, top: top * CM, roomH: r.heightCm * CM });
    }
  }
  return out;
}

export interface SunPose {
  sun: [number, number, number];
  target: [number, number, number];
  fill: [number, number, number];
  /** Полуширина камеры тени солнца, м: вся квартира с запасом. */
  half: number;
}

/** Солнце за первым окном: 6 м наружу, 6,5 м вверх, на 0,6 рад сбоку от оси окна (тени чуть наискосок, как в эталоне). Окон нет — null. */
export function sunPose(rooms: readonly Room[]): SunPose | null {
  const w = roomWindows(rooms)[0];
  if (!w || !rooms.length) return null;
  const x0 = Math.min(...rooms.map((r) => r.x)), x1 = Math.max(...rooms.map((r) => r.x + r.w));
  const y0 = Math.min(...rooms.map((r) => r.y)), y1 = Math.max(...rooms.map((r) => r.y + r.d));
  const cx = ((x0 + x1) / 2) * CM, cz = ((y0 + y1) / 2) * CM;
  const a = 0.6, dx = w.nx * Math.cos(a) - w.nz * Math.sin(a), dz = w.nz * Math.cos(a) + w.nx * Math.sin(a);
  return {
    sun: [cx - dx * 6, 6.5, cz - dz * 6],
    target: [cx, 0, cz],
    fill: [cx + w.nx * 5, 2.5, cz + w.nz * 5],
    half: Math.max(x1 - x0, y1 - y0) * CM * 0.8 + 1,
  };
}

/** Шторы: по полотну 55 см с каждого края окна, от карниза (14 см над проёмом) до пола, со складками. Окон нет — пустая группа. */
export function buildCurtains(rooms: readonly Room[]): THREE.Group {
  const g = new THREE.Group();
  g.name = "curtains";
  const wins = roomWindows(rooms);
  if (!wins.length) return g;
  const mat = new THREE.MeshStandardMaterial({ color: 0xd8c4a6, roughness: 0.95, side: THREE.DoubleSide });
  const pw = 0.55;
  for (const w of wins) {
    const top = Math.min(w.roomH - 0.04, w.top + 0.14), h = top - 0.01;
    const geo = new THREE.PlaneGeometry(pw, h, 28, 1);
    const pos = geo.attributes.position!;
    for (let i = 0; i < pos.count; i++) pos.setZ(i, 0.03 * Math.sin((pos.getX(i) / pw + 0.5) * Math.PI * 9));
    geo.computeVertexNormals();
    for (const side of [-1, 1]) {
      const m = new THREE.Mesh(geo, mat);
      const along = side * (w.w / 2 + pw / 2 - 0.12);   // слегка заходит на проём
      const ax = -w.nz, az = w.nx;                       // ось «вдоль стены»
      m.position.set(w.x + ax * along + w.nx * 0.09, 0.01 + h / 2, w.z + az * along + w.nz * 0.09);
      m.rotation.y = Math.atan2(w.nx, w.nz);
      m.raycast = () => undefined;
      g.add(m);
    }
  }
  return g;
}
