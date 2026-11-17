// ЭКСПОРТ СЦЕНЫ (render-3d-01 шаг 0, Codex 17.11): ОДНО описание сцены для двух потребителей — браузера (/demo, туры) и
// бесплатного рендера Blender. Blender читает ТОЛЬКО этот JSON (и GLB декора рядом) и не воспроизводит правила (доски пола, места
// картин, шторы) в Python. Источник — результат `resolveScene` и каталог: те же числа, что строят сцену /demo.
//
// Имя файла выпуска — `scene-export.json`, НЕ `lib/scene.json`: тот — манифест файлов сборки (`tools/scout/flat215-demo/index.html`,
// `tools/ops/demo-release-hash.mjs`). Версия формата — `SCENE_EXPORT_VERSION`; читатель с другой версией отказывается, а не угадывает.
// Модуль чистый: без three.js, сети и DOM — гоняется в vitest; GLB декора строит отдельный выгрузчик (`tools/scout/render3d/`).

import type { Apartment, Placement, Room } from "@/contracts/apartment";
import type { Catalogue, Material, Option } from "@/contracts/configurator";
import { materialById, optionById } from "@/contracts/configurator";
import type { ResolvedItem, ResolvedScene, ResolvedSurface } from "@/lib/configurator/resolve";
import { meshUrl, runtimeEntry } from "@/lib/configurator/mesh-url";
import { textileRenders, type TextileShape } from "@/lib/configurator/textile";
import { finishPassport, tintHex } from "@/lib/viewer3d/finish-passport";
import { windowView } from "@/lib/viewer3d/window-views";

export const SCENE_EXPORT_VERSION = 1;

/** Карты поверхности: адреса абсолютные (как их качает /demo), `tileCm` — физический размер одного повтора. */
export interface ExportMaps {
  color?: string;
  colorLite?: string;
  normal?: string;
  roughness?: string;
  ao?: string;
  height?: string;
  variation?: string;
}

export interface ExportSurface {
  /** id материала каталога (`data/flat3d/materials.json`) или паспорта; по нему сверяют /demo и Blender. */
  materialId: string;
  /** Цвет паспорта (то, что видит владелец квартиры). */
  colorHex: string;
  /** Цвет, на который умножается карта цвета: `tintHex` (нейтральная карта) или белый (цветная); без карт — сам `colorHex`. */
  tintHex: string;
  maps: ExportMaps;
  tileCm: [number, number];
  roughness: number;
  metalness: number;
  /** Источник и лицензия карт (реестр рядом с ассетом, `source` материала). */
  source?: { kind?: string; sourceUrl?: string; licence?: string; note?: string; method?: string };
}

export interface ExportOpening {
  kind: string;
  wall: string;
  offsetCm: number;
  widthCm: number;
  sillCm?: number;
  heightCm?: number;
  junction?: boolean;
  open?: boolean;
}

export interface ExportRoom {
  id: string;
  kind: string;
  rectCm: { x: number; y: number; w: number; d: number };
  heightCm: number;
  openings: ExportOpening[];
  wall: ExportSurface;
  /** Акцентная стена: материал и сторона (`accent.ts:resolveAccentSide`). */
  accent?: { side: string; surface: ExportSurface };
  floor: ExportSurface;
  ceiling: { colorHex: string };
  skirting: { colorHex: string };
  windowView?: { id: string; url: string };
}

export interface ExportMesh {
  slotId: string;
  roomId: string;
  role: string | null;
  titleRu: string;
  /** Ключ товара в каталоге мешей (msid) — по нему и по `sha` сверяют «мебель не изменилась». */
  meshId: string;
  /** Что берёт /demo: лёгкая копия или исходник; нет лёгкой — `liteMissing` (в браузере будет исходник, не коробка). */
  url: string;
  liteUrl: string | null;
  liteMissing: boolean;
  sha: string | null;
  shaLite: string | null;
  yawDeg: number;
  tintRgb?: [number, number, number];
  placement: Placement;
  shop?: { name?: string; url?: string; priceRub?: number };
}

export interface ExportKit {
  slotId: string;
  roomId: string;
  role: string | null;
  kit: string;
  placement: Placement;
  /** Цвет условной ткани (штора, плед, подушка) или материал ковра/картины. */
  surface?: ExportSurface;
  features: string[];
}

export interface ExportLight {
  slotId: string;
  roomId: string;
  kind: "point" | "spot";
  posCm: [number, number, number];
  watts: number;
  kelvin: number;
}

export interface ExportCamera {
  id: string;
  roomId: string;
  xCm: number;
  yCm: number;
  rotDeg: number;
  fov: number;
  pose?: number;
  pshift?: number;
}

export interface SceneExport {
  version: number;
  apartmentId: string;
  /** Единицы: все длины — сантиметры; ось y квартиры — «север» плана (в сцене three это z). */
  units: "cm";
  rooms: ExportRoom[];
  meshes: ExportMesh[];
  kits: ExportKit[];
  lights: ExportLight[];
  cameras: ExportCamera[];
  /** Проверка переносимости: сколько мешей без лёгкой копии (в /demo-телефоне они грузятся исходником). */
  liteMissing: string[];
}

function surfaceOf(m: Material): ExportSurface {
  const hasColor = !!m.baseColorUrl;
  return {
    materialId: m.id,
    colorHex: m.colorHex,
    tintHex: hasColor ? tintHex(m) : m.colorHex,
    maps: {
      ...(m.baseColorUrl ? { color: m.baseColorUrl } : {}),
      ...(m.baseColorLiteUrl ? { colorLite: m.baseColorLiteUrl } : {}),
      ...(m.normalUrl ? { normal: m.normalUrl } : {}),
      ...(m.roughnessUrl ? { roughness: m.roughnessUrl } : {}),
      ...(m.aoUrl ? { ao: m.aoUrl } : {}),
      ...(m.heightUrl ? { height: m.heightUrl } : {}),
      ...(m.variationUrl ? { variation: m.variationUrl } : {}),
    },
    tileCm: m.tileCm,
    roughness: m.roughness,
    metalness: m.metalness,
    ...(m.source ? { source: { kind: m.source.kind, sourceUrl: m.source.sourceUrl, licence: m.source.licence, note: m.source.note, method: m.source.method } } : {}),
  };
}

function roomOf(r: Room, sc: ResolvedScene): ExportRoom {
  const fp = finishPassport(r.finish);
  const surf = (s: "wall" | "floor"): ResolvedSurface | undefined => sc.surfaces.find((x) => x.roomId === r.id && x.surface === s);
  const wall = surf("wall"), floor = surf("floor");
  // нет слота покрытия (комната без отделки в каталоге) — паспортный цвет без карт
  const plain = (id: string, hex: string): ExportSurface => ({ materialId: id, colorHex: hex, tintHex: hex, maps: {}, tileCm: [100, 100], roughness: 0.9, metalness: 0 });
  const view = r.openings.some((o) => o.kind === "window") ? windowView(r.windowView) : null;
  return {
    id: r.id,
    kind: r.kind,
    rectCm: { x: r.x, y: r.y, w: r.w, d: r.d },
    heightCm: r.heightCm,
    openings: r.openings.map((o) => ({ kind: o.kind, wall: o.wall, offsetCm: o.offsetCm, widthCm: o.widthCm,
      ...(o.sillCm !== undefined ? { sillCm: o.sillCm } : {}), ...(o.heightCm !== undefined ? { heightCm: o.heightCm } : {}),
      ...(o.junction ? { junction: true } : {}), ...(o.open ? { open: true } : {}) })),
    wall: wall ? surfaceOf(wall.material) : plain(fp.wall.id, fp.wall.colorHex),
    ...(wall?.accent ? { accent: { side: wall.accent.side, surface: surfaceOf(wall.accent.material) } } : {}),
    floor: floor ? surfaceOf(floor.material) : plain(fp.floor.id, fp.floor.colorHex),
    ceiling: { colorHex: fp.ceiling.colorHex },
    skirting: { colorHex: fp.skirting.colorHex },
    ...(view ? { windowView: { id: view.id, url: view.view.url } } : {}),
  };
}

function meshOf(it: ResolvedItem, o: Option | undefined, lite: boolean): ExportMesh | null {
  if (it.asset.kind !== "mesh" || it.unplaced) return null;
  const e = runtimeEntry(it.asset.meshId);
  const liteUrl = e?.["size-lite"] ? meshUrl(it.asset.meshId, it.asset.runtimeUrl, true) : null;
  return {
    slotId: it.slotId,
    roomId: it.roomId,
    role: it.photoRole,
    titleRu: it.titleRu,
    meshId: it.asset.meshId,
    url: meshUrl(it.asset.meshId, it.asset.runtimeUrl, lite),
    liteUrl,
    liteMissing: !liteUrl,
    sha: e?.src_sha ?? null,
    shaLite: e?.["src_sha-lite"] ?? null,
    yawDeg: it.asset.yawDeg,
    ...(it.asset.tintRgb ? { tintRgb: it.asset.tintRgb } : {}),
    placement: it.placement,
    ...(o && (o.shopName || o.shopUrl) ? { shop: { name: o.shopName, url: o.shopUrl, priceRub: o.listPrice } } : {}),
  };
}

const TEXTILE_SHAPES: readonly string[] = ["curtain", "throw", "pillow"];

/** Описание сцены для рендера: чистая функция от результата `resolveScene` и каталога. `lite` — какую копию мешей берёт /demo. */
export function exportScene(apartment: Apartment, catalogue: Catalogue, sc: ResolvedScene, opts: { lite?: boolean } = {}): SceneExport {
  const meshes: ExportMesh[] = [];
  const kits: ExportKit[] = [];
  for (const it of sc.items) {
    const o = optionById(catalogue, it.optionId);
    const m = meshOf(it, o, opts.lite === true);
    if (m) { meshes.push(m); continue; }
    if (it.asset.kind !== "kit" || it.unplaced) continue;
    // ткань, чья форма не рисуется геометрией (`data/flat3d/textile.json:render`, плед — ярлык), в рендер не идёт: ни цвета «по слову», ни бруска
    if (it.asset.kit === "textile" && it.asset.features.some((f) => TEXTILE_SHAPES.includes(f) && !textileRenders(f as TextileShape))) continue;
    // ткань, ковёр и картина: материал каталога по ролям кита (`kit.materials`) — первый, иначе по id опции
    const matId = Object.values(it.asset.materials)[0];
    const mat = (matId && materialById(catalogue, matId)) || undefined;
    kits.push({ slotId: it.slotId, roomId: it.roomId, role: it.photoRole, kit: it.asset.kit, placement: it.placement,
      ...(mat ? { surface: surfaceOf(mat) } : {}), features: it.asset.features });
  }
  return {
    version: SCENE_EXPORT_VERSION,
    apartmentId: apartment.id,
    units: "cm",
    rooms: apartment.rooms.map((r) => roomOf(r, sc)),
    meshes,
    kits,
    lights: [],     // шаг 4 плана: источники ламп — здесь, из места лампы
    cameras: apartment.cameras.map((c) => ({ id: c.id, roomId: c.roomId, xCm: c.x, yCm: c.y, rotDeg: c.rot, fov: c.fov,
      ...(c.pose !== undefined ? { pose: c.pose } : {}), ...(c.pshift !== undefined ? { pshift: c.pshift } : {}) })),
    liteMissing: meshes.filter((m) => m.liteMissing).map((m) => m.meshId),
  };
}
