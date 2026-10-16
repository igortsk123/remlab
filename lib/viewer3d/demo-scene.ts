// ЖИВАЯ СЦЕНА ДЕМО (план demo-01): гостиная со страницы `/demo` рисуется в браузере тем же движком, что `/flat`
// (`FlatViewer`). Заменил диван или подвинул столик — картинка меняется на следующем кадре, без запроса к серверу.
// Серверный кадр остаётся для ночных карточек, запасного пути (нет WebGL, медленный кадр) и листа «Улучшить» (ADR-0184).
//
// Вход — РАССТАНОВКА СТРАНИЦЫ как есть: комната витрины и живые предметы (`items` демо: role, x, y, rot, w, d, h, elev,
// sku{msid, yaw, img…}). Это та же форма, что у варианта в `demo-data.json`, поэтому квартиру собирает тот же мост
// `fromDemoVariant`, что открывает вариант в `/flat` — одна модель сцены, два потребителя (разбор Codex 14.10).
// ТВ над тумбой и настольный декор — тем же правилом, что серверный кадр (`scene-extras.ts`, demo-05 п.9): ТВ считает
// движок из текущей расстановки (`build-scene.sceneExtras`), вазу на столик — расчёт сцены (`resolve.placeTabletop`).

import type { Apartment } from "@/contracts/apartment";
import type { Catalogue } from "@/contracts/configurator";
import { fromDemoVariant, stableSlotIds, type DemoData } from "@/lib/configurator/fromDemo";
import { type DecorIn } from "@/lib/viewer3d/scene-extras";
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
  /** Пол застройщика (demo-06) — материал каталога (`data/flat3d/materials.json`, адреса карт абсолютные). */
  floor?: Record<string, unknown> & { id: string };
}

export type DemoSceneEvent = "progress" | "contextlost";

export interface DemoScene {
  /** Первая расстановка загружена (модели пришли или остались честными коробками). */
  ready: Promise<void>;
  /** Новая расстановка (и декор — одним состоянием с ней). Последняя побеждает: промежуточные при быстрых правках
   *  пропускаются. Декор не передан — остаётся прежний. */
  update(items: DemoItem[], decor?: DemoDecor[]): Promise<void>;
  setPhotoPose(pose: PhotoPose): void;
  /** Сменить пол (demo-06): оболочка комнаты перерисовывается, модели мебели не перезагружаются. */
  setFloor(floor: (Record<string, unknown> & { id: string }) | null): Promise<void>;
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
 * Квартира и каталог из живой расстановки — тем же мостом `fromDemoVariant`, что открывает вариант в `/flat` (demo-05 п.9:
 * ковёр — плита с фото товара, ваза — на столике по правилу серверного кадра; одно место для окна и /flat).
 */
export function liveApartment(room: DemoRoom, items: DemoItem[], base: string, decor: DemoDecor[] = [],
  floor?: Record<string, unknown> & { id: string }): { apartment: Apartment; catalogue: Catalogue } | null {
  const built = fromDemoVariant({ room, variants: [{ id: "live", items, decor }] }, "live",
    { ...CTX, assetBase: base, ...(floor ? { floorMaterial: floor } : {}) });
  if (!built) return null;
  const { apartment, catalogue } = built;
  // стены и пол — свои материалы из паспорта отделки: их ставит сам мост (`fromDemoVariant`), одинаково для окна и /flat
  return { apartment, catalogue };
}

export function createDemoScene(canvas: HTMLCanvasElement, opts: DemoSceneOptions): DemoScene {
  if (opts.runtimeMeshes) setRuntimeMeshes(opts.runtimeMeshes);
  let decor: DemoDecor[] = opts.decor ?? [];
  let floor = opts.floor;
  const first = liveApartment(opts.room, opts.items, opts.base, decor, floor);
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
        const next = liveApartment(opts.room, current, opts.base, decor, floor);
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
    setFloor: (f) => {
      floor = f ?? undefined;
      running = running.then(async () => {
        const next = liveApartment(opts.room, current, opts.base, decor, floor);
        if (!next) return;
        viewer.setApartment(next.apartment, next.catalogue);
        const sc = resolved(next.apartment, next.catalogue);
        viewer.buildShell(sc);          // пол — часть оболочки комнаты
        await viewer.syncObjects(sc);   // мебель та же — модели не перезагружаются (подписи не меняются)
      }).catch((e: unknown) => console.warn("живая сцена: пол не сменился", e));
      return running;
    },
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
