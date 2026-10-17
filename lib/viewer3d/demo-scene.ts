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
  /** Стены застройщика (demo-07): материал и необязательная акцентная стена «за диваном». */
  wall?: DemoWall;
}

type Mat = Record<string, unknown> & { id: string };
/** Стены живой сцены: материал всех стен и акцентная — сторону считает расчёт сцены (`accent.ts`). */
export type DemoWall = { material: Mat; accent?: { material: Mat; anchor: "behind-sofa" } };

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
  /** Сменить стены (demo-07): оболочка перерисовывается, модели мебели не перезагружаются. */
  setWall(wall: DemoWall | null): Promise<void>;
  /** Сторона акцентной стены текущей расстановки (для запроса серверного кадра); акцента нет — null. */
  accentSide(): string | null;
  exportFrame(width: number, height: number, type?: string, quality?: number): Promise<Blob>;
  /** Вид окна (demo-02): «Ракурс» — фото-поза (`setPhotoPose`), «3D» — прогулка; с позой — из точки этого ракурса,
   *  взгляд на середину мебели (`viewer.walkFrom`). */
  setWalk(from?: PhotoPose): void;
  /** Плавно перейти к позе ракурса (стрелки «‹ ›» в 3D, demo-09); в конце — кадр будущего реалистичного фото. */
  goToPose(pose: PhotoPose): void;
  /** Портрет телефона: взгляд из позы наклонён к мебели (снимок сервера — без наклона). */
  setTilt(on: boolean): void;
  /** Кадры для нейросети из поз ракурсов (demo-10): JPEG каждого вида и роли предметов, оставшихся коробкой (clay). */
  capture(poses: PhotoPose[], width: number, height: number): Promise<{ frames: Blob[]; clay: string[] }>;
  /** Повернуть взгляд в прогулке (перетаскивание пальцем/мышью). */
  look(dx: number, dy: number): void;
  /** Какой предмет под точкой холста: номер в расстановке страницы (как в `update`), иначе -1. */
  pick(clientX: number, clientY: number): number;
  /** Метки предметов на холсте: номер в расстановке и точка (px холста), видна ли (demo-02: цены на сцене). */
  pins(): { index: number; x: number; y: number; visible: boolean }[];
  /** Повернуть взгляд прогулки к предмету расстановки (номер как в `update`): заменённый в «3D» предмет должен быть виден
   *  (приёмка владельцем 16.10: диван менялся за краем кадра, и замена казалась несработавшей). */
  focus(index: number): void;
  /** Выделить предмет расстановки (номер как в `update`) или снять выделение — рамка и тёплая подсветка (`viewer.highlight`). */
  select(index: number | null): void;
  /** Повернуть взгляд прогулки на `deg` градусов (тап по краю сцены в «3D», demo-02 v3: поворот не только перетаскиванием). */
  turn(deg: number): void;
  /** Тап в «3D»: по предмету — его номер в расстановке; по полу — шаг туда (`viewer.goTo`) и -1. */
  walkTap(clientX: number, clientY: number): number;
  /** Где стоит и куда смотрит прогулка (см, градусы) — живая проверка поворота тапом по краю и шага по полу. */
  pose(): { x: number; y: number; yaw: number };
  /** Номер предмета расстановки → подпись модели на сцене (живая проверка «замена дошла до сцены»). */
  models(): Record<number, string>;
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
  floor?: Record<string, unknown> & { id: string }, wall?: DemoWall): { apartment: Apartment; catalogue: Catalogue } | null {
  const built = fromDemoVariant({ room, variants: [{ id: "live", items, decor }] }, "live",
    { ...CTX, assetBase: base, ...(floor ? { floorMaterial: floor } : {}), ...(wall ? { wallMaterial: wall } : {}) });
  if (!built) return null;
  const { apartment, catalogue } = built;
  // стены и пол — свои материалы из паспорта отделки: их ставит сам мост (`fromDemoVariant`), одинаково для окна и /flat
  return { apartment, catalogue };
}

export function createDemoScene(canvas: HTMLCanvasElement, opts: DemoSceneOptions): DemoScene {
  if (opts.runtimeMeshes) setRuntimeMeshes(opts.runtimeMeshes);
  let decor: DemoDecor[] = opts.decor ?? [];
  let floor = opts.floor;
  let wall = opts.wall;
  const first = liveApartment(opts.room, opts.items, opts.base, decor, floor, wall);
  if (!first) throw new Error("пустая расстановка");
  const listeners = new Map<DemoSceneEvent, Set<(...a: number[]) => void>>();
  const emit = (ev: DemoSceneEvent, ...a: number[]): void => listeners.get(ev)?.forEach((f) => f(...a));
  const viewer = new FlatViewer(canvas, first.apartment, first.catalogue, opts.lite ? LITE_QUALITY : DESKTOP_QUALITY, {
    onProgress: (l, t) => emit("progress", l, t),
    onContextLost: () => emit("contextlost"),
  });
  const resolved = (a: Apartment, c: Catalogue) => resolveScene(a, c, defaultConfiguration(a, c));
  // сторона акцентной стены — из расчёта сцены; меняется, когда переставили диван, — тогда оболочку перестраиваем
  const sideOf = (sc: ReturnType<typeof resolved>): string | null => sc.surfaces.find((x) => x.surface === "wall")?.accent?.side ?? null;
  const sc0 = resolved(first.apartment, first.catalogue);
  let lastSide = sideOf(sc0);
  viewer.buildShell(sc0);
  const ready = viewer.syncObjects(sc0);

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
  // выделенный предмет переживает пересборку расстановки (замена модели пересоздаёт объект — выделение ставим заново)
  let selected: number | null = null;
  const reselect = (): void => {
    if (selected == null) return;
    const id = [...slotIndex()].find(([, i]) => i === selected)?.[0];
    viewer.highlight(id ?? null);
  };
  const update = (items: DemoItem[], nextDecor?: DemoDecor[]): Promise<void> => {
    pending = { items, decor: nextDecor ?? pending?.decor ?? decor };
    running = running
      .then(async () => {
        if (!pending) return;
        current = pending.items;
        decor = pending.decor;
        const next = liveApartment(opts.room, current, opts.base, decor, floor, wall);
        pending = null;
        if (!next) return;
        viewer.setApartment(next.apartment, next.catalogue);
        const sc = resolved(next.apartment, next.catalogue);
        if (sideOf(sc) !== lastSide) { lastSide = sideOf(sc); viewer.buildShell(sc); }   // акцент переехал за диваном
        await viewer.syncObjects(sc);
        reselect();
      })
      // ошибка одной синхронизации не должна молча глушить все следующие (verify 14.10)
      .catch((e: unknown) => console.warn("живая сцена: обновление не применилось", e));
    return running;
  };

  // оболочка комнаты (пол, стены) по новой отделке: перерисовка коробки, модели мебели не перезагружаются (подписи те же)
  const reshell = (what: string): Promise<void> => {
    running = running.then(async () => {
      const next = liveApartment(opts.room, current, opts.base, decor, floor, wall);
      if (!next) return;
      viewer.setApartment(next.apartment, next.catalogue);
      const sc = resolved(next.apartment, next.catalogue);
      lastSide = sideOf(sc);
      viewer.buildShell(sc);
      await viewer.syncObjects(sc);
      reselect();
    }).catch((e: unknown) => console.warn(`живая сцена: ${what} не сменились`, e));
    return running;
  };

  return {
    ready,
    update,
    setPhotoPose: (pose) => viewer.setPhotoPose(pose),
    setFloor: (f) => { floor = f ?? undefined; return reshell("пол"); },
    setWall: (w) => { wall = w ?? undefined; return reshell("стены"); },
    accentSide: () => lastSide,
    exportFrame: (w, h, type, q) => viewer.exportFrame(w, h, type, q),
    setWalk: (from) => (from ? viewer.walkFrom(from) : viewer.setViewMode("walk")),
    goToPose: (pose) => { viewer.goToPose(pose); viewer.start(); },
    setTilt: (on) => viewer.setTilt(on),
    capture: async (poses, width, height) => {
      await running;                                  // последняя расстановка уже в сцене
      viewer.highlight(null);                         // тёплая подсветка выбранного — не в кадр нейросети
      try {
        const frames: Blob[] = [];
        for (const p of poses) frames.push(await viewer.capturePhoto(p, width, height, 0.85, { tilt: height > width }));
        const st = viewer.slotStatus();
        const clay = [...slotIndex()].filter(([id]) => st[id] === "stub").map(([, i]) => String(current[i]?.role ?? "")).filter(Boolean);
        return { frames, clay };
      } finally {
        reselect();
        viewer.start();
      }
    },
    look: (dx, dy) => viewer.look(dx, dy),
    focus: (index) => {
      const it = current[index];
      const x = Number(it?.x), y = Number(it?.y);
      if (Number.isFinite(x) && Number.isFinite(y)) viewer.faceToward(x, y);
    },
    // плюс — направо; `viewer.look` с положительным dx поворачивает налево (перетаскивание «тянет мир»), 0,22° на пиксель
    select: (index) => {
      selected = index;
      const id = index == null ? null : [...slotIndex()].find(([, i]) => i === index)?.[0] ?? null;
      viewer.highlight(id);
      viewer.start();
    },
    turn: (deg) => viewer.look(-deg / 0.22, 0),
    walkTap: (x, y) => {
      const hit = viewer.pick(x, y, canvas.getBoundingClientRect());
      if (hit.slotId) return slotIndex().get(hit.slotId) ?? -1;
      if (hit.point) {
        if (viewer.mode === "photo") viewer.photoToWalk();   // 3D из точки съёмки: шаг по полу — уже прогулка
        viewer.goTo(hit.point.x, hit.point.y);
      }
      return -1;
    },
    pose: () => viewer.viewPose(),
    models: () => {
      const sig = viewer.placedSignatures();
      return Object.fromEntries([...slotIndex()].map(([id, i]) => [i, sig[id] ?? ""]));
    },
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
