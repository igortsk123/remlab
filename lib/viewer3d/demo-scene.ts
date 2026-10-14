// ЖИВАЯ СЦЕНА ДЕМО (план demo-01): гостиная со страницы `/demo` рисуется в браузере тем же движком, что `/flat`
// (`FlatViewer`). Заменил диван или подвинул столик — картинка меняется на следующем кадре, без запроса к серверу.
// Серверный кадр остаётся для ночных карточек, запасного пути (нет WebGL, медленный кадр) и листа «Улучшить» (ADR-0184).
//
// Вход — РАССТАНОВКА СТРАНИЦЫ как есть: комната витрины и живые предметы (`items` демо: role, x, y, rot, w, d, h, elev,
// sku{msid, yaw, img…}). Это та же форма, что у варианта в `demo-data.json`, поэтому квартиру собирает тот же мост
// `fromDemoVariant`, что открывает вариант в `/flat` — одна модель сцены, два потребителя (разбор Codex 14.10).
// Известные отличия от серверного кадра (Codex): декор (вазу) сервер расставляет своим алгоритмом, ТВ на тумбу
// добавляет сам — здесь их пока нет.

import { slot as slotSchema, type Apartment } from "@/contracts/apartment";
import { material as materialSchema, option as optionSchema, type Catalogue } from "@/contracts/configurator";
import { fromDemoVariant, type DemoData } from "@/lib/configurator/fromDemo";
import { setRuntimeMeshes, type RuntimeEntry } from "@/lib/configurator/mesh-url";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { DESKTOP_QUALITY, FlatViewer, LITE_QUALITY, type PhotoPose } from "@/lib/viewer3d/viewer";

type DemoRoom = NonNullable<DemoData["room"]>;
type DemoItem = NonNullable<NonNullable<DemoData["variants"]>[number]["items"]>[number] & { sku?: { img?: string } };

export interface DemoSceneOptions {
  room: DemoRoom;
  items: DemoItem[];
  /** Адрес страницы демо: относительные картинки витрины (`img/…`) считаются от него. */
  base: string;
  /** Свежая таблица лёгких копий (`/demo/rt-meshes.json`); нет — та, что собрана в бандл. */
  runtimeMeshes?: Record<string, RuntimeEntry>;
  /** Телефон/слабая машина — лёгкие копии и без теней. */
  lite?: boolean;
}

export type DemoSceneEvent = "progress" | "contextlost";

export interface DemoScene {
  /** Первая расстановка загружена (модели пришли или остались честными коробками). */
  ready: Promise<void>;
  /** Новая расстановка. Последняя побеждает: промежуточные при быстрых правках пропускаются. */
  update(items: DemoItem[]): Promise<void>;
  setPhotoPose(pose: PhotoPose): void;
  exportFrame(width: number, height: number, type?: string, quality?: number): Promise<Blob>;
  /** p95 времени кадра (мс) и программный ли рендер — по ним страница решает, нужен ли серверный эскиз. */
  probe(frames?: number): { p95Ms: number; software: boolean };
  setSize(width: number, height: number): void;
  on(ev: DemoSceneEvent, fn: (...a: number[]) => void): () => void;
  start(): void;
  stop(): void;
  dispose(): void;
}

const CTX = { apartmentId: "demo-live", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
const isRug = (it: DemoItem): boolean => String(it.role ?? "").startsWith("ковёр");

/**
 * Квартира и каталог из живой расстановки. Ковёр — фото товара на полу (как серверный «фото-ковёр»): своей 3D-модели
 * у ковра нет, а мост `fromDemoVariant` пропускает предметы без высоты — без этой вставки ковров в сцене не было бы.
 */
export function liveApartment(room: DemoRoom, items: DemoItem[], base: string): { apartment: Apartment; catalogue: Catalogue } | null {
  const built = fromDemoVariant({ room, variants: [{ id: "live", items: items.filter((it) => !isRug(it)) }] }, "live", CTX);
  if (!built) return null;
  const { apartment, catalogue } = built;
  // СТЕНЫ И ПОЛ — СВОИ (живая проверка 14.10): своих материалов у набора витрины нет, и движок брал первый материал
  // каталога — фото ковра — на стены и пол. Цвета — как у серверного кадра (светлый бежевый пол, почти белые стены).
  catalogue.materials.unshift(
    materialSchema.parse({ id: "paint-white", titleRu: "Стены", titleEn: "Walls", colorHex: "#f2f0ed", roughness: 0.95 }),
    materialSchema.parse({ id: "demo-floor", titleRu: "Пол", titleEn: "Floor", colorHex: "#dcc7a6", roughness: 0.7 }),
  );
  for (const [surface, category, materialId] of [["floor", "flooring", "demo-floor"], ["wall", "walls", "paint-white"]] as const) {
    catalogue.options.push(optionSchema.parse({ id: `opt:${surface}`, category, titleRu: surface, titleEn: surface, tier: "standard",
      price: 0, availability: "available", roomKinds: ["living"], asset: { kind: "material", materialId } }));
    apartment.slots.push(slotSchema.parse({ id: surface, roomId: "living", category, kind: "surface", surface, titleRu: surface,
      titleEn: surface, defaultOptionId: `opt:${surface}`, optionIds: [`opt:${surface}`] }));
  }
  items.filter(isRug).forEach((it, k) => {
    if (!it.w || !it.d) return;
    const id = `ковёр#${k}`;
    const img = it.sku?.img ? new URL(it.sku.img, base).toString() : undefined;
    catalogue.materials.push(materialSchema.parse({ id: `rug:${k}`, titleRu: "Ковёр", titleEn: "Rug", colorHex: "#b8b0a4",
      roughness: 0.95, tileCm: [it.w, it.d], surfaces: ["rug"], ...(img ? { baseColorUrl: img } : {}) }));
    catalogue.options.push(optionSchema.parse({ id: `opt:${id}`, category: "furniture", titleRu: it.sku?.name ?? "Ковёр",
      titleEn: it.sku?.name ?? "Rug", tier: "standard", price: 0, availability: "available", roomKinds: ["living"],
      asset: { kind: "kit", kit: "rug", materials: { body: `rug:${k}` } } }));
    apartment.slots.push(slotSchema.parse({ id, roomId: "living", category: "furniture", kind: "furniture", titleRu: "ковёр",
      titleEn: "rug", defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`],
      placement: { x: it.x ?? 0, y: it.y ?? 0, rot: it.rot ?? 0, wCm: it.w, dCm: it.d, hCm: 1, elevCm: 0 } }));
  });
  return { apartment, catalogue };
}

export function createDemoScene(canvas: HTMLCanvasElement, opts: DemoSceneOptions): DemoScene {
  if (opts.runtimeMeshes) setRuntimeMeshes(opts.runtimeMeshes);
  const first = liveApartment(opts.room, opts.items, opts.base);
  if (!first) throw new Error("пустая расстановка");
  const listeners = new Map<DemoSceneEvent, Set<(...a: number[]) => void>>();
  const emit = (ev: DemoSceneEvent, ...a: number[]): void => listeners.get(ev)?.forEach((f) => f(...a));
  const viewer = new FlatViewer(canvas, first.apartment, first.catalogue, opts.lite ? LITE_QUALITY : DESKTOP_QUALITY, {
    onProgress: (l, t) => emit("progress", l, t),
    onContextLost: () => emit("contextlost"),
  });
  const resolved = (a: Apartment, c: Catalogue) => resolveScene(a, c, defaultConfiguration(a, c));
  viewer.buildShell(resolved(first.apartment, first.catalogue));
  const ready = viewer.syncObjects(resolved(first.apartment, first.catalogue));

  // ПОСЛЕДНЯЯ РАССТАНОВКА ПОБЕЖДАЕТ, СИНХРОНИЗАЦИИ ИДУТ ПО ОДНОЙ (Codex 14.10): две одновременные `syncObjects`
  // дважды добавили бы один предмет, а быстрые замены гонялись бы с незаконченной загрузкой.
  let pending: DemoItem[] | null = null;
  let running: Promise<void> = ready;
  const update = (items: DemoItem[]): Promise<void> => {
    pending = items;
    running = running.then(async () => {
      if (!pending) return;
      const next = liveApartment(opts.room, pending, opts.base);
      pending = null;
      if (!next) return;
      viewer.setApartment(next.apartment, next.catalogue);
      await viewer.syncObjects(resolved(next.apartment, next.catalogue));
    });
    return running;
  };

  return {
    ready,
    update,
    setPhotoPose: (pose) => viewer.setPhotoPose(pose),
    exportFrame: (w, h, type, q) => viewer.exportFrame(w, h, type, q),
    probe: (frames = 10) => ({ p95Ms: viewer.measureFrameMs(frames), software: viewer.softwareRenderer }),
    setSize: (w, h) => viewer.setSize(w, h),
    on(ev, fn) {
      const set = listeners.get(ev) ?? new Set();
      set.add(fn);
      listeners.set(ev, set);
      return () => set.delete(fn);
    },
    start: () => viewer.start(),
    stop: () => viewer.stop(),
    dispose: () => viewer.dispose(),
  };
}
