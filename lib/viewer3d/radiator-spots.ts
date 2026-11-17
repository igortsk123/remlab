// РАДИАТОР ПОД ОКНОМ — ПРАВИЛА И МЕСТА (T-20261117-11): чистая часть без three.js (её читают и живая 3D `kits/radiator.ts`, и экспорт сцены для Blender
// `scene-export.ts`: одно правило — одни и те же места и размеры в браузере и на фото-рендере). Данные — `data/flat3d/radiator.json`.

import type { Room } from "@/contracts/apartment";
import radiatorJson from "@/data/flat3d/radiator.json";

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
