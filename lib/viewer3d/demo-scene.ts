// ЖИВАЯ СЦЕНА ДЕМО (план demo-01): гостиная со страницы `/demo` рисуется в браузере тем же движком, что `/flat`
// (`FlatViewer`). Заменил диван или подвинул столик — картинка меняется на следующем кадре, без запроса к серверу.
// Серверный кадр остаётся для ночных карточек, запасного пути (нет WebGL, медленный кадр) и листа «Улучшить» (ADR-0184).
//
// Вход — РАССТАНОВКА СТРАНИЦЫ как есть: комната витрины и живые предметы (`items` демо: role, x, y, rot, w, d, h, elev,
// sku{msid, yaw, img…}). Это та же форма, что у варианта в `demo-data.json`, поэтому квартиру собирает тот же мост
// `fromDemoVariant`, что открывает вариант в `/flat` — одна модель сцены, два потребителя (разбор Codex 14.10).
// ТВ над тумбой и настольный декор — тем же правилом, что серверный кадр (`scene-extras.ts`, demo-05 п.9): ТВ считает
// движок из текущей расстановки (`build-scene.sceneExtras`), вазу на столик ставит `liveApartment` по `decorLayout`.

import { finishPassport } from "@/lib/viewer3d/finish-passport";
import { slot as slotSchema, type Apartment } from "@/contracts/apartment";
import { material as materialSchema, option as optionSchema, type Catalogue } from "@/contracts/configurator";
import { fromDemoVariant, stableSlotIds, type DemoData } from "@/lib/configurator/fromDemo";
import { EXTRA_PREFIX } from "@/lib/viewer3d/build-scene";
import { decorLayout, type DecorIn } from "@/lib/viewer3d/scene-extras";
import { meshUrl, setRuntimeMeshes, type RuntimeEntry } from "@/lib/configurator/mesh-url";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { DESKTOP_QUALITY, FlatViewer, LITE_QUALITY, type PhotoPose } from "@/lib/viewer3d/viewer";

type DemoRoom = NonNullable<DemoData["room"]>;
type DemoItem = NonNullable<NonNullable<DemoData["variants"]>[number]["items"]>[number] & { sku?: { img?: string } };
/** Настольный декор варианта (`v.decor` витрины): товар с моделью и габаритами, место — по опоре. */
export type DemoDecor = DecorIn & { sku?: DecorIn["sku"] & { yaw?: number; price?: number } };

export interface DemoSceneOptions {
  room: DemoRoom;
  items: DemoItem[];
  /** Настольный декор варианта (ваза): ставится на столик тем же правилом, что на серверном кадре. */
  decor?: DemoDecor[];
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
  /** Новая расстановка (и декор — одним состоянием с ней). Последняя побеждает: промежуточные при быстрых правках
   *  пропускаются. Декор не передан — остаётся прежний. */
  update(items: DemoItem[], decor?: DemoDecor[]): Promise<void>;
  setPhotoPose(pose: PhotoPose): void;
  exportFrame(width: number, height: number, type?: string, quality?: number): Promise<Blob>;
  /** Вид окна (demo-02): «Ракурс» — фото-поза (`setPhotoPose`), «3D» — прогулка; с позой — из точки этого ракурса,
   *  взгляд на середину мебели (`viewer.walkFrom`). */
  setWalk(from?: PhotoPose): void;
  /** Повернуть взгляд в прогулке (перетаскивание пальцем/мышью). */
  look(dx: number, dy: number): void;
  /** Какой предмет под точкой холста: номер в расстановке страницы (как в `update`), иначе -1. */
  pick(clientX: number, clientY: number): number;
  /** Метки предметов на холсте: номер в расстановке и точка (px холста), видна ли (demo-02: цены на сцене). */
  pins(): { index: number; x: number; y: number; visible: boolean }[];
  /** Подгрузить модели кандидатов заранее (лента замен открылась) — замена потом без сети. */
  prefetch(items: DemoItem[]): void;
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
export function liveApartment(room: DemoRoom, items: DemoItem[], base: string, decor: DemoDecor[] = []): { apartment: Apartment; catalogue: Catalogue } | null {
  const built = fromDemoVariant({ room, variants: [{ id: "live", items: items.filter((it) => !isRug(it)) }] }, "live", CTX);
  if (!built) return null;
  const { apartment, catalogue } = built;
  // СТЕНЫ И ПОЛ — СВОИ (живая проверка 14.10): своих материалов у набора витрины нет, и движок брал первый материал
  // каталога — фото ковра — на стены и пол. Цвета — как у серверного кадра (светлый бежевый пол, почти белые стены).
  // цвета — из паспорта отделки (`finish-passport.ts`), тем же красится серверный кадр
  const fp = finishPassport(room.finish);
  catalogue.materials.unshift(
    materialSchema.parse({ id: fp.wall.id, titleRu: "Стены", titleEn: "Walls", colorHex: fp.wall.colorHex, roughness: 0.95 }),
    materialSchema.parse({ id: fp.floor.id, titleRu: "Пол", titleEn: "Floor", colorHex: fp.floor.colorHex, roughness: 0.7 }),
  );
  for (const [surface, category, materialId] of [["floor", "flooring", fp.floor.id], ["wall", "walls", fp.wall.id]] as const) {
    catalogue.options.push(optionSchema.parse({ id: `opt:${surface}`, category, titleRu: surface, titleEn: surface, tier: "standard",
      price: 0, availability: "available", roomKinds: ["living"], asset: { kind: "material", materialId } }));
    apartment.slots.push(slotSchema.parse({ id: surface, roomId: "living", category, kind: "surface", surface, titleRu: surface,
      titleEn: surface, defaultOptionId: `opt:${surface}`, optionIds: [`opt:${surface}`] }));
  }
  items.filter(isRug).forEach((it, k) => {
    if (!it.w || !it.d) return;
    const id = `ковёр#${k}`;
    const img = it.sku?.img ? new URL(it.sku.img, base).toString() : undefined;
    // материал назван по ТОВАРУ: подпись ковра в движке — по материалу, и замена ковра того же размера иначе оставила бы
    // старое фото (verify 14.10)
    const mat = `rug:${k}:${it.sku?.sid ?? it.sku?.img ?? ""}`;
    catalogue.materials.push(materialSchema.parse({ id: mat, titleRu: "Ковёр", titleEn: "Rug", colorHex: "#b8b0a4",
      roughness: 0.95, tileCm: [it.w, it.d], surfaces: ["rug"], ...(img ? { baseColorUrl: img } : {}) }));
    catalogue.options.push(optionSchema.parse({ id: `opt:${id}`, category: "furniture", titleRu: it.sku?.name ?? "Ковёр",
      titleEn: it.sku?.name ?? "Rug", tier: "standard", price: 0, availability: "available", roomKinds: ["living"],
      asset: { kind: "kit", kit: "rug", materials: { body: mat } } }));
    apartment.slots.push(slotSchema.parse({ id, roomId: "living", category: "furniture", kind: "furniture", titleRu: "ковёр",
      titleEn: "rug", defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`],
      placement: { x: it.x ?? 0, y: it.y ?? 0, rot: it.rot ?? 0, wCm: it.w, dCm: it.d, hCm: 1, elevCm: 0 } }));
  });
  // НАСТОЛЬНЫЙ ДЕКОР — как на серверном кадре (`draft_render.decor_layout`): ряд по длинной оси столика (иначе обеденного
  // стола), подъём — высота опоры; не влезло или нет модели — не рисуется. Своего места у декора нет (владелец 08.09:
  // «двигать не давать»), поэтому слот производный: не выбирается и не препятствие прогулке (`build-scene.isExtra`).
  decorLayout(items, decor).placed.forEach((p, k) => {
    const msid = p.decor.sku?.msid;
    if (!msid) return;
    const id = `${EXTRA_PREFIX}decor:${p.decor.role ?? "декор"}#${k}`;
    catalogue.options.push(optionSchema.parse({ id: `opt:${id}`, category: "furniture", titleRu: p.decor.sku?.name ?? "Декор",
      titleEn: p.decor.sku?.name ?? "Decor", tier: "standard", price: 0, availability: "available", roomKinds: ["living"],
      asset: { kind: "mesh", meshId: msid, yawDeg: p.decor.sku?.yaw ?? 0, wCm: p.w, dCm: p.d, hCm: p.h } }));
    apartment.slots.push(slotSchema.parse({ id, roomId: "living", category: "furniture", kind: "builtin", titleRu: p.decor.role ?? "декор",
      titleEn: "decor", defaultOptionId: `opt:${id}`, optionIds: [`opt:${id}`],
      placement: { x: p.x, y: p.y, rot: p.rot, wCm: p.w, dCm: p.d, hCm: p.h, elevCm: p.elev } }));
  });
  return { apartment, catalogue };
}

export function createDemoScene(canvas: HTMLCanvasElement, opts: DemoSceneOptions): DemoScene {
  if (opts.runtimeMeshes) setRuntimeMeshes(opts.runtimeMeshes);
  let decor: DemoDecor[] = opts.decor ?? [];
  const first = liveApartment(opts.room, opts.items, opts.base, decor);
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
  let pending: { items: DemoItem[]; decor: DemoDecor[] } | null = null;
  // номер места в движке («диван#0») ↔ номер предмета в расстановке страницы — тем же счётом, что у моста
  let current: DemoItem[] = opts.items;
  const slotIndex = (): Map<string, number> => {
    const idx = current.map((it, i) => ({ it, i })).filter(({ it }) => !isRug(it) && it.w && it.d && it.h && it.sku?.msid);
    const ids = stableSlotIds(idx.map(({ it }) => it));
    return new Map(ids.map((id, k) => [id, idx[k]!.i]));
  };
  let running: Promise<void> = ready;
  const update = (items: DemoItem[], nextDecor?: DemoDecor[]): Promise<void> => {
    pending = { items, decor: nextDecor ?? pending?.decor ?? decor };
    running = running
      .then(async () => {
        if (!pending) return;
        current = pending.items;
        decor = pending.decor;
        const next = liveApartment(opts.room, current, opts.base, decor);
        pending = null;
        if (!next) return;
        viewer.setApartment(next.apartment, next.catalogue);
        await viewer.syncObjects(resolved(next.apartment, next.catalogue));
      })
      // ошибка одной синхронизации не должна молча глушить все следующие (verify 14.10)
      .catch((e: unknown) => console.warn("живая сцена: обновление не применилось", e));
    return running;
  };

  return {
    ready,
    update,
    setPhotoPose: (pose) => viewer.setPhotoPose(pose),
    exportFrame: (w, h, type, q) => viewer.exportFrame(w, h, type, q),
    setWalk: (from) => (from ? viewer.walkFrom(from) : viewer.setViewMode("walk")),
    look: (dx, dy) => viewer.look(dx, dy),
    pick: (x, y) => {
      const id = viewer.pick(x, y, canvas.getBoundingClientRect()).slotId;
      return id ? slotIndex().get(id) ?? -1 : -1;
    },
    pins: () => {
      const out: { index: number; x: number; y: number; visible: boolean }[] = [];
      for (const [id, index] of slotIndex()) {
        const p = viewer.projectSlot(id);
        if (p) out.push({ index, x: p.x, y: p.y, visible: p.visible });
      }
      return out;
    },
    prefetch: (items) => {
      for (const it of items) if (it.sku?.msid) viewer.preloadMesh(meshUrl(it.sku.msid, undefined, opts.lite === true));
    },
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
