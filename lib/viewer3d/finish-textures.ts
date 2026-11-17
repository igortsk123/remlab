// ФАКТУРА ОТДЕЛКИ ПО ПАСПОРТУ (render-3d-01 шаг 1): у паспорта комнаты (`finish-passport.ts`) только цвет и id — рельефа и рисунка
// нет, и стены с полом читались плоской краской («картонный» кадр). Здесь паспортной стене и полу ставятся CC0-карты (ambientCG,
// `data/flat3d/finish-cc0.json` → `tools/assets/material_from_cc0.py`): карта НЕЙТРАЛЬНАЯ, цвет паспорта красит её при показе
// (`tintHex`). Тот же материал уходит в экспорт сцены (`scene-export.ts`), поэтому /demo и Blender берут одни карты и одну тонировку.
//
// Тип материала — свободный словарь, как у остального моста (`fromDemo.ts:Mat`): схему проверяет `catalogueSchema.parse`.

import finishCfg from "@/data/flat3d/finish-cc0.json";
import materialsJson from "@/data/flat3d/materials.json";
import type { Finish } from "@/lib/viewer3d/finish-passport";

export type FinishTextureSurface = "wall" | "floor";

const IDS: Record<FinishTextureSurface, string> = { wall: "finish-wall", floor: "finish-floor" };
const BASE = (materialsJson as { baseUrl?: string }).baseUrl ?? "/flat3d/materials/";
const URLS = ["baseColorUrl", "baseColorLiteUrl", "normalUrl", "roughnessUrl", "aoUrl", "heightUrl", "variationUrl", "previewUrl"] as const;

type Rec = Record<string, unknown> & { id: string };

/** Акцентные стены по стилю (T-20261117-16): стиль варианта → id материала из `finish-cc0.json` (`accentWalls.styles` → `surfaces`). */
const ACCENT_BY_STYLE: Record<string, string> = Object.fromEntries(
  Object.entries((finishCfg as { accentWalls: { styles: Record<string, string> } }).accentWalls.styles)
    .flatMap(([style, surface]) => {
      const id = (finishCfg as { surfaces: Record<string, { id: string }> }).surfaces[surface]?.id;
      return id ? [[style, id]] : [];
    }),
);

const RECORDS: Record<string, Rec> = Object.fromEntries(
  (materialsJson as { materials: Rec[] }).materials
    .filter((m) => Object.values(IDS).includes(m.id) || Object.values(ACCENT_BY_STYLE).includes(m.id)).map((m) => [m.id, m]),
);

const withUrls = (rec: Rec, id: string, colorHex?: string): Rec => {
  const out: Rec = { ...rec, id, ...(colorHex ? { colorHex } : {}) };
  for (const k of URLS) {
    const v = rec[k];
    if (typeof v === "string") out[k] = /^https?:|^\//.test(v) ? v : BASE + v;
  }
  return out;
};

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
  return withUrls(rec, id, finish.colorHex);
}

/**
 * Акцентная стена по стилю варианта («лофт» — кирпич): материал со СВОЕЙ расцветкой скана (паспорт его не красит) и якорь «за главным
 * предметом комнаты» (`accent.ts`). Нет правила для стиля, нет собранных карт или фактура выключена (`?finish=0`) — undefined.
 */
export function accentWallFor(style?: string): { material: Rec; anchor: "behind-focal" } | undefined {
  const id = style ? ACCENT_BY_STYLE[style.toLowerCase()] : undefined;
  const rec = id ? RECORDS[id] : undefined;
  if (!rec || !finishTexFromUrl()) return undefined;
  return { material: withUrls(rec, rec.id), anchor: "behind-focal" };
}
