import * as THREE from "three";

import type { Room } from "@/contracts/apartment";
import { CURTAIN_PANEL_CM, CURTAIN_PLANE_CM, CURTAIN_PLEAT_CM, curtainRodY, roomCurtains } from "@/lib/configurator/curtains";
import { WALL_INSET_CM } from "@/lib/viewer3d/rooms";

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

/**
 * Шторы: полотна у краёв окна (`curtains.ts:roomCurtains` — ширина по свободному месту, до 55 см), от штанги карниза до пола, со
 * складками; плоскость — перед подоконником (`CURTAIN_PLANE_CM` от поверхности стены, она вдвинута на `WALL_INSET_CM`), там же
 * штанга (`fixtures-ir.ts`). Окон нет — пустая группа.
 */
export function buildCurtains(rooms: readonly Room[]): THREE.Group {
  const g = new THREE.Group();
  g.name = "curtains";
  const mat = new THREE.MeshStandardMaterial({ color: 0xd8c4a6, roughness: 0.95, side: THREE.DoubleSide });
  const out = (WALL_INSET_CM + CURTAIN_PLANE_CM) * CM;
  for (const r of rooms) {
    roomCurtains(r).forEach((span, i) => {
      const o = r.openings[i]!;
      if (!span) return;
      const sill = o.kind === "balcony" ? 0 : o.sillCm ?? 90;
      const top = Math.min(r.heightCm, o.kind === "balcony" ? o.heightCm ?? 220 : sill + (o.heightCm ?? 140));
      const h = (curtainRodY(top, r.heightCm) - 1) * CM;   // верх — на штанге, низ — в 1 см от пола
      const n = o.wall === "south" ? [0, 1] : o.wall === "north" ? [0, -1] : o.wall === "west" ? [1, 0] : [-1, 0];
      for (const p of span.panels) {
        const pw = (p.u1 - p.u0) * CM, um = (p.u0 + p.u1) / 2;
        // offset — от начала стены: запад→восток у южной/северной, юг→север у западной/восточной (`contracts/apartment.ts:opening`)
        const [px, pz] = o.wall === "south" ? [r.x + um, r.y] : o.wall === "north" ? [r.x + um, r.y + r.d]
          : o.wall === "west" ? [r.x, r.y + um] : [r.x + r.w, r.y + um];
        // складки у верха сходят на нет (до 0,9 см — меньше полутолщины штанги): кромка прячется в штангу, гребни не торчат над ней
        const geo = new THREE.PlaneGeometry(pw, h, 28, Math.ceil(h / 0.08));
        const pos = geo.attributes.position!, folds = Math.max(3, Math.round((9 * (p.u1 - p.u0)) / CURTAIN_PANEL_CM));
        for (let k = 0; k < pos.count; k++) {
          const fade = 0.3 + 0.7 * Math.min(1, (h / 2 - pos.getY(k)) / 0.1);
          pos.setZ(k, fade * CURTAIN_PLEAT_CM * CM * Math.sin((pos.getX(k) / pw + 0.5) * Math.PI * folds));
        }
        geo.computeVertexNormals();
        const m = new THREE.Mesh(geo, mat);
        m.position.set(px * CM + n[0]! * out, 0.01 + h / 2, pz * CM + n[1]! * out);
        m.rotation.y = Math.atan2(n[0]!, n[1]!);
        m.raycast = () => undefined;
        g.add(m);
      }
    });
  }
  return g;
}
