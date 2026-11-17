// ФАКТУРА ОТДЕЛКИ ПО ПАСПОРТУ (render-3d-01 шаг 1): у паспорта комнаты (`finish-passport.ts`) только цвет и id — рельефа и рисунка
// нет, и стены с полом читались плоской краской («картонный» кадр). Здесь паспортной стене и полу ставятся CC0-карты (ambientCG,
// `data/flat3d/finish-cc0.json` → `tools/assets/material_from_cc0.py`): карта НЕЙТРАЛЬНАЯ, цвет паспорта красит её при показе
// (`tintHex`). Тот же материал уходит в экспорт сцены (`scene-export.ts`), поэтому /demo и Blender берут одни карты и одну тонировку.
//
// Тип материала — свободный словарь, как у остального моста (`fromDemo.ts:Mat`): схему проверяет `catalogueSchema.parse`.

import materialsJson from "@/data/flat3d/materials.json";
import type { Finish } from "@/lib/viewer3d/finish-passport";

export type FinishTextureSurface = "wall" | "floor";

const IDS: Record<FinishTextureSurface, string> = { wall: "finish-wall", floor: "finish-floor" };
const BASE = (materialsJson as { baseUrl?: string }).baseUrl ?? "/flat3d/materials/";
const URLS = ["baseColorUrl", "baseColorLiteUrl", "normalUrl", "roughnessUrl", "aoUrl", "previewUrl"] as const;

type Rec = Record<string, unknown> & { id: string };

const RECORDS: Record<string, Rec> = Object.fromEntries(
  (materialsJson as { materials: Rec[] }).materials.filter((m) => Object.values(IDS).includes(m.id)).map((m) => [m.id, m]),
);

/**
 * Выключатель фактуры отделки в адресе страницы: `?finish=0` — стены и пол плоской краской (откат без выкладки и замер «до/после»,
 * как `?art=0` у картин); иначе — фактура CC0.
 */
export function finishTexFromUrl(search: string = (globalThis as { location?: { search?: string } }).location?.search ?? ""): boolean {
  return !/[?&]finish=0(&|$)/.test(search);
}

/**
 * Материал паспортной поверхности с фактурой: карты CC0, цвет — паспорта. `id` — тот, что получил бы плоский материал (приставка
 * комнаты), чтобы одинаковый id с другим цветом не слился в каталоге. Нет собранной фактуры — undefined (прежняя плоская краска).
 */
export function texturedFinish(surface: FinishTextureSurface, finish: Finish, id: string): Rec | undefined {
  const rec = RECORDS[IDS[surface]];
  if (!rec || !finishTexFromUrl()) return undefined;
  const out: Rec = { ...rec, id, colorHex: finish.colorHex };
  for (const k of URLS) {
    const v = rec[k];
    if (typeof v === "string") out[k] = /^https?:|^\//.test(v) ? v : BASE + v;
  }
  return out;
}
