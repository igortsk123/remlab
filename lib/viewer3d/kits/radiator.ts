// РАДИАТОР ПОД ОКНОМ (T-20261117-11): одна общая модель на каждое окно каждой комнаты — не товар, без цены, строки списка и замены. Как растения
// (`kits/plants.ts`): правила — данные (`data/flat3d/radiator.json`: размер от окна, отступ от стены и пола, выключатель), реестр и лицензия модели —
// `data/flat3d/radiator/source.json`; в коде нет ни товаров, ни комнат. Модель — своя процедурная панель «тип 22» (на Poly Haven и ambientCG
// готового радиатора нет): корпус со скруглёнными кромками, два пояса пазов, верхняя решётка, патрубки к полу, термоголовка у левого края.
//
// Локальные оси модели — как у прочих наборов (`kits/common.ts`): центр — на полу под серединой окна, X — вдоль стены, лицо в +Z (в комнату),
// спиной к стене. Группа ничего не перехватывает (`raycast` пуст): тап по радиатору — как по стене, и в рамку ракурса он не входит.

import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

import type { Room } from "@/contracts/apartment";
import radiatorJson from "@/data/flat3d/radiator.json";
import { WALL_INSET_CM } from "@/lib/viewer3d/rooms";

const CM = 0.01;

export interface RadiatorRules {
  enabled: boolean;
  openingKinds: string[];
  size: { widthOfWindow: number; minWidthCm: number; maxWidthCm: number; heightCm: number; depthCm: number };
  offset: { fromWallCm: number; fromFloorCm: number };
  underSillGapCm: number;
  finish: { color: string; grille: string; pipe: string; roughness: number; metalness: number };
  model: {
    edgeRadiusCm: number; grooveCount: number; grooveDepthCm: number; grooveHeightCm: number; grilleHeightCm: number; grilleInsetCm: number;
    pipeRadiusCm: number; pipeInsetCm: number; headRadiusCm: number; headLengthCm: number; bracketCm: [number, number, number];
  };
}
export const RADIATOR_RULES: RadiatorRules = radiatorJson as unknown as RadiatorRules;

/** Выключатель радиаторов в адресе страницы: `?radiators=0` — без них (откат без выкладки), `?radiators=1` — с ними; нет — решает `enabled` данных. */
export function radiatorsFromUrl(search: string = (globalThis as { location?: { search?: string } }).location?.search ?? ""): boolean | undefined {
  const m = /[?&]radiators=([01])(&|$)/.exec(search);
  return m ? m[1] === "1" : undefined;
}

/** Место радиатора под одним окном: центр на плоскости стены (см сцены), нормаль внутрь комнаты, ширина панели, см. */
export interface RadiatorSpot { roomId: string; opening: number; xCm: number; zCm: number; nx: number; nz: number; widthCm: number }

/**
 * Где стоят радиаторы: по окну (`openingKinds`) каждой комнаты, ширина — от ширины окна в пределах [min, max]; окно уже `minWidthCm` или с подоконником
 * ниже верха панели (панель не встаёт под него) — без радиатора. Чистая функция данных комнат и правил.
 */
export function radiatorSpots(rooms: readonly Room[], rules: RadiatorRules = RADIATOR_RULES): RadiatorSpot[] {
  const out: RadiatorSpot[] = [];
  const { size, offset } = rules;
  const topCm = offset.fromFloorCm + size.heightCm;
  for (const r of rooms) {
    r.openings.forEach((o, i) => {
      if (!rules.openingKinds.includes(o.kind) || o.widthCm < size.minWidthCm) return;
      const sill = o.kind === "balcony" ? 0 : o.sillCm ?? 90;
      if (sill < topCm + rules.underSillGapCm) return;
      // offset — от начала стены: запад→восток у южной/северной, юг→север у западной/восточной (`contracts/apartment.ts:opening`)
      const along = o.offsetCm + o.widthCm / 2;
      const at = o.wall === "south" ? { x: r.x + along, z: r.y, nx: 0, nz: 1 }
        : o.wall === "north" ? { x: r.x + along, z: r.y + r.d, nx: 0, nz: -1 }
          : o.wall === "west" ? { x: r.x, z: r.y + along, nx: 1, nz: 0 }
            : { x: r.x + r.w, z: r.y + along, nx: -1, nz: 0 };
      const widthCm = Math.round(Math.min(size.maxWidthCm, Math.max(size.minWidthCm, o.widthCm * size.widthOfWindow)));
      out.push({ roomId: r.id, opening: i, xCm: at.x, zCm: at.z, nx: at.nx, nz: at.nz, widthCm });
    });
  }
  return out;
}

/** Панель радиатора заданной ширины, см (метры сцены). Материалы и геометрия — на группе; освобождает `disposeObject`. */
export function buildRadiator(widthCm: number, rules: RadiatorRules = RADIATOR_RULES): THREE.Group {
  const { size, offset, finish, model: m } = rules;
  const g = new THREE.Group();
  const body = new THREE.MeshStandardMaterial({ color: finish.color, roughness: finish.roughness, metalness: finish.metalness });
  const dark = new THREE.MeshStandardMaterial({ color: finish.grille, roughness: finish.roughness + 0.1, metalness: finish.metalness });
  const pipe = new THREE.MeshStandardMaterial({ color: finish.pipe, roughness: 0.35, metalness: 0.35 });
  const w = widthCm, h = size.heightCm, d = size.depthCm, y0 = offset.fromFloorCm, zFront = d / 2;
  const add = (geo: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number): THREE.Mesh => {
    const mesh = new THREE.Mesh(geo, material);
    mesh.position.set(x * CM, y * CM, z * CM);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.raycast = () => undefined;
    g.add(mesh);
    return mesh;
  };
  const box = (bw: number, bh: number, bd: number, r = 0): THREE.BufferGeometry =>
    r > 0 ? new RoundedBoxGeometry(bw * CM, bh * CM, bd * CM, 3, Math.min(r, bd / 2, bh / 2) * CM) : new THREE.BoxGeometry(bw * CM, bh * CM, bd * CM);
  // корпус: две панели в одном ящике со скруглёнными кромками (спиной к стене, лицом в комнату)
  add(box(w, h, d, m.edgeRadiusCm), body, 0, y0 + h / 2, 0);
  // пазы-рёбра лицевой панели: тонкие тёмные полосы вдоль, равномерно по высоте под решёткой
  const usable = h - m.grilleHeightCm - 6;
  for (let k = 0; k < m.grooveCount; k++) {
    const gy = y0 + 3 + (usable * (k + 1)) / (m.grooveCount + 1);
    add(box(w - 2 * m.edgeRadiusCm - 1, m.grooveHeightCm, m.grooveDepthCm), dark, 0, gy, zFront + m.grooveDepthCm / 2 - 0.05);
  }
  // верхняя решётка: чуть ниже верха, тёмнее корпуса
  add(box(w - 2 * m.grilleInsetCm - 2, m.grilleHeightCm, m.grooveDepthCm + 0.2), dark, 0, y0 + h - m.grilleHeightCm / 2 - 0.9, zFront + m.grooveDepthCm / 2);
  // патрубки к полу у обоих краёв и термоголовка у левого (если смотреть в комнату — слева направо по +X)
  const px = w / 2 - m.pipeInsetCm;
  for (const side of [-1, 1]) {
    const pg = new THREE.CylinderGeometry(m.pipeRadiusCm * CM, m.pipeRadiusCm * CM, y0 * CM, 14);
    add(pg, pipe, side * px, y0 / 2, -d / 2 + 2);
  }
  const head = new THREE.CylinderGeometry(m.headRadiusCm * CM, m.headRadiusCm * CM, m.headLengthCm * CM, 16);
  head.rotateZ(Math.PI / 2);
  add(head, body, -px - 2.4, y0 + 2.6, -d / 2 + 2);
  // кронштейны на стену (за корпусом, видны только снизу)
  const [bw, bh, bd] = m.bracketCm;
  for (const side of [-1, 1]) add(box(bw, bh, bd), dark, side * (w / 2 - 9), y0 + h * 0.18, -d / 2 - bd / 2 + 0.2);
  g.name = "radiator";
  return g;
}

/**
 * Радиаторы всех окон квартиры одной группой (метры сцены): каждый — в своём месте под окном, спиной к стене с отступом `fromWallCm`
 * (от плоскости стены с вставкой `WALL_INSET_CM`), лицом в комнату.
 */
export function buildRadiators(rooms: readonly Room[], rules: RadiatorRules = RADIATOR_RULES): THREE.Group {
  const all = new THREE.Group();
  all.name = "radiators";
  for (const s of radiatorSpots(rooms, rules)) {
    const r = buildRadiator(s.widthCm, rules);
    const back = WALL_INSET_CM + rules.offset.fromWallCm + rules.size.depthCm / 2;
    r.position.set((s.xCm + s.nx * back) * CM, 0, (s.zCm + s.nz * back) * CM);
    r.rotation.y = Math.atan2(s.nx, s.nz);
    all.add(r);
  }
  return all;
}
