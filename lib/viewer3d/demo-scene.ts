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
import { fromDemoVariant, isCeilingDecor, isWallArtDecor, isWallPlane, stableSlotIds, wallArtItems, type DemoData } from "@/lib/configurator/fromDemo";
import { type DecorIn } from "@/lib/viewer3d/scene-extras";
import { meshUrl, RUNTIME_BASE, setRuntimeMeshes, type RuntimeEntry } from "@/lib/configurator/mesh-url";
import { windowView } from "@/lib/viewer3d/window-views";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { planObjects } from "@/lib/viewer3d/build-scene";
import { DESKTOP_QUALITY, FlatViewer, LITE_QUALITY, type PhotoPose } from "@/lib/viewer3d/viewer";

type DemoRoom = NonNullable<DemoData["room"]>;
type DemoItem = NonNullable<NonNullable<DemoData["variants"]>[number]["items"]>[number] & { sku?: { img?: string } };
/** Декор варианта (`v.decor` витрины): настольный — товар с моделью, место по столику; картина (`strategy: procedural_plane`) —
 *  фото товара на стене над опорой (`wall-art.ts`). */
export type DemoDecor = DecorIn & { strategy?: string; list_only?: boolean;
  sku?: DecorIn["sku"] & { yaw?: number; price?: number; img?: string; img_art?: string } };

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
  /** Тап по полу ведёт туда (по умолчанию да) — и на телефоне (T-20261112-36, владелец «да» TG 1791; прежде, demo-20 Б6, на
   *  сенсорном экране было выключено). `false` — только осмотр, повороты и ракурсы; тап по предмету выбирает его в любом случае. */
  walk?: boolean;
  /** Декоративные шторы у окон (T-20261111-22, владелец TG 1643). Нет — адрес страницы (`curtainsFromUrl`), иначе по умолчанию вкл. */
  curtains?: boolean;
}

/**
 * Выключатель картин в адресе страницы (viz-decor-01 шаг 3): `?art=0` — картины не висят в 3D (откат без выкладки; в списке и сумме
 * страницы они остаются); иначе — по правилам `data/flat3d/wall-art.json` (`enabled`).
 */
export function artFromUrl(search: string = (globalThis as { location?: { search?: string } }).location?.search ?? ""): boolean {
  return !/[?&]art=0(&|$)/.test(search);
}

/** Выключатель штор в адресе страницы: `?curtains=0` — без штор (откат без выкладки), `?curtains=1` — со шторами; нет — решает движок. */
export function curtainsFromUrl(search: string = (globalThis as { location?: { search?: string } }).location?.search ?? ""): boolean | undefined {
  const m = /[?&]curtains=([01])(&|$)/.exec(search);
  return m ? m[1] === "1" : undefined;
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
  /** «3D» глазами стоящего (demo-27): глаз, см, и видимая полоса холста — доли высоты (над шторкой и переключателем); null — выкл. */
  setLiveEye(v: { eyeCm?: number; band?: { top?: number; bottom?: number } } | null): void;
  /** Наклон взгляда по мебели заново (после загрузки расстановки). */
  aimLive(): void;
  /** Кадры для нейросети из поз ракурсов (demo-10): JPEG каждого вида и роли предметов, оставшихся коробкой (clay). */
  capture(poses: PhotoPose[], width: number, height: number): Promise<{ frames: Blob[]; clay: string[] }>;
  /** Повернуть взгляд в прогулке (перетаскивание пальцем/мышью). */
  look(dx: number, dy: number): void;
  /** Какой предмет под точкой холста: номер в расстановке страницы (как в `update`; картина декора — `items.length` + номер в `decor`,
   *  `sceneSlotIndex`), иначе -1. Тот же номер — у `pins`, `select`, `walkTap`. */
  pick(clientX: number, clientY: number): number;
  /** Метки предметов на холсте: номер в расстановке и точка (px холста), видна ли (demo-02: цены на сцене); рамка предмета на холсте
   *  `[left, top, right, bottom]` — ценник над ней (demo-27 В), null — угол коробки за камерой. */
  pins(): { index: number; x: number; y: number; visible: boolean; box: [number, number, number, number] | null }[];
  /** Повернуть взгляд прогулки к предмету расстановки (номер как в `update`): заменённый в «3D» предмет должен быть виден
   *  (приёмка владельцем 16.10: диван менялся за краем кадра, и замена казалась несработавшей). */
  focus(index: number): void;
  /** Навестись на предмет после замены (demo-15): поворот на месте или безопасный переход; ответ — что сделано. */
  frameItem(index: number): "turn" | "move" | "none";
  /** Выделить предмет расстановки (номер как в `update`) или снять выделение — рамка и тёплая подсветка (`viewer.highlight`). */
  select(index: number | null): void;
  /** Рамка выбранного — предупреждение (красная): повёрнутый кнопкой «Повернуть» предмет задевает соседний (T-20261111-05 п.7). */
  warn(on: boolean): void;
  /** «Переместить» (T-20261111-05/4): начать перетаскивание предмета (номер как в `update`); false — предмета нет в сцене. */
  moveBegin(index: number): boolean;
  /** Сдвинуть черновик на (dx, dy) см от исходного места; под ним след на полу: `ok` — зелёный, иначе красный. `rot` — новый угол
   *  предмета в градусах расстановки (поворот «в руке», колесо или R, T-20261111-05/8); не задан — прежний. */
  moveBy(dx: number, dy: number, ok: boolean, rot?: number): void;
  /** Исходное место переносимого предмета в координатах сцены, см (как у `floorAt`); null — переноса нет. Страница по нему
   *  ставит предмет центром под курсор: место = исходное + (точка пола − это место). */
  moveOrigin(): { x: number; y: number } | null;
  /** Закончить: `commit` — предмет остаётся (страница запишет место в расстановку), иначе возвращается, где стоял. */
  moveEnd(commit: boolean): void;
  /** Точка пола под экранной точкой, см (тянут палец или мышь); null — луч мимо пола (выше горизонта). */
  floorAt(clientX: number, clientY: number): { x: number; y: number } | null;
  /** Повернуть взгляд прогулки на `deg` градусов (тап по краю сцены в «3D», demo-02 v3: поворот не только перетаскиванием). */
  turn(deg: number): void;
  /** Тап по окну — подойти к нему (`viewer.walkToWindow`); не окно — false. Для краёв сцены, где тап иначе поворачивает взгляд. */
  windowTap(clientX: number, clientY: number): boolean;
  /** Тап в «3D» — по ближайшему под пальцем (`viewer.walkAim`, T-20261112-36): предмет — его номер в расстановке; окно — подойти
   *  к нему (`viewer.walkToWindow`) и -1; пол (и ковёр) комнаты или закутка — шаг туда с кольцом в точке, где встанем (`viewer.goTo`,
   *  если `walk` не выключен) и -1; стена — -1. */
  walkTap(clientX: number, clientY: number): number;
  /** Мышь над сценой «3D» (T-20261112-36): над полом — пульсирующее кольцо там, куда пойдём; иначе кольца нет. Не чаще ~25 раз в
   *  секунду (луч по мебели), последнее положение не теряется. */
  previewWalk(clientX: number, clientY: number): void;
  /** Убрать кольцо под мышью (мышь ушла со сцены, начался поворот взгляда); кольцо цели идущего пути остаётся. */
  hideWalkHint(): void;
  /** Где стоит и куда смотрит прогулка (см, градусы) — живая проверка поворота тапом по краю и шага по полу. */
  pose(): { x: number; y: number; yaw: number; pitch: number };
  /** Номер предмета расстановки → подпись модели на сцене (живая проверка «замена дошла до сцены»). */
  models(): Record<number, string>;
  /** Подгрузить модели кандидатов заранее (лента замен открылась) — замена потом без сети. */
  prefetch(items: DemoItem[]): void;
  /** Миниатюры предметов расстановки (номера как в `update`) для строк списка тура (T-20261109-35/2): JPEG data URL на белом фоне;
   *  модель не пришла, ковёр или предмета нет на сцене — null (страница держит заглушку и спросит позже). */
  thumbs(indices: number[], size?: number): (string | null)[];
  /** p95 времени кадра (мс) и программный ли рендер — по ним страница решает, нужен ли серверный эскиз. */
  probe(frames?: number): { p95Ms: number; software: boolean };
  setSize(width: number, height: number): void;
  on(ev: DemoSceneEvent, fn: (...a: number[]) => void): () => void;
  start(): void;
  stop(): void;
  dispose(): void;
}

const CTX = { apartmentId: "demo-live", partnerId: "demo", currency: "RUB" as const, basePrice: 0 };
/** Кольцо под мышью — не чаще раза в 40 мс (~25 в секунду): луч по мебели на каждое движение мыши грузит слабые машины (Codex 12.11). */
const HOVER_MS = 40;
const isRug = (it: DemoItem): boolean => String(it.role ?? "").startsWith("ковёр");

/**
 * Квартира и каталог из живой расстановки — тем же мостом `fromDemoVariant`, что открывает вариант в `/flat` (demo-05 п.9:
 * ковёр — плита с фото товара, ваза — на столике по правилу серверного кадра; одно место для окна и /flat).
 */
export function liveApartment(room: DemoRoom, items: DemoItem[], base: string, decor: DemoDecor[] = [],
  floor?: Record<string, unknown> & { id: string }, wall?: DemoWall): { apartment: Apartment; catalogue: Catalogue } | null {
  const live = artFromUrl() ? decor : decor.filter((d) => !isWallArtDecor(d));
  const built = fromDemoVariant({ room, variants: [{ id: "live", items, decor: live }] }, "live",
    { ...CTX, assetBase: base, ...(floor ? { floorMaterial: floor } : {}), ...(wall ? { wallMaterial: wall } : {}) });
  if (!built) return null;
  const { apartment, catalogue } = built;
  // стены и пол — свои материалы из паспорта отделки: их ставит сам мост (`fromDemoVariant`), одинаково для окна и /flat
  return { apartment, catalogue };
}

/**
 * Адреса моделей расстановки — ровно те, что возьмёт сцена (`planObjects`, тот же признак `lite`). Страница качает их в кэш
 * браузера, пока покупатель смотрит фото варианта (demo-26): «3D» потом открывается без «Загружаем модели N из M».
 * Без видеоконтекста — только расчёт сцены; на телефоне до «3D» холст не создаётся.
 */
export function sceneMeshUrls(opts: PrefetchOptions): string[] {
  return sceneAssetUrls(opts).meshes;
}

/**
 * Где висят картины расстановки — тот же расчёт, что строит 3D (`resolveScene` → `wall-art.ts:placeWallArt`), без холста:
 * роль картины («картина», «картина 2») → роль опоры, над которой она висит, или null — места на стене нет (в составе и цене
 * есть, в 3D не висит). Подпись страницы «где стоит» берётся отсюда, а не своим порядком опор (T-20261112-26/2).
 */
export function wallArtWhere(opts: Pick<DemoSceneOptions, "room" | "items" | "decor" | "base">): Record<string, string | null> {
  const built = liveApartment(opts.room, opts.items, opts.base, opts.decor ?? []);
  if (!built) return {};
  const { apartment, catalogue } = built;
  const art = new Set(apartment.slots.filter((s) => s.wallArt).map((s) => s.id));
  const sc = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
  return Object.fromEntries(sc.items.filter((i) => art.has(i.slotId) && i.photoRole)
    .map((i) => [i.photoRole as string, i.unplaced ? null : i.hungOver ?? null]));
}

/**
 * Место движка («диван#0», «картина#0») → номер предмета страницы — тем же счётом, что у моста (`fromDemo.ts`). Мебель — номер
 * в `items` (ковёр и настенные плоскости расстановки не выбираются). КАРТИНА-ТОВАР ИЗ ДЕКОРА (T-20261112-45, владелец TG 1062:
 * «цена, выделяется и даёт заменить — той же логикой») — `items.length` + номер в переданном `decor`: место той же нумерацией,
 * что `wallPlanes` (зеркала расстановки, затем картины); без картин в сцене (`?art=0`) — не добавляются.
 */
export function sceneSlotIndex(items: DemoItem[], decor: DemoDecor[], art: boolean = artFromUrl()): Map<string, number> {
  const idx = items.map((it, i) => ({ it, i })).filter(({ it }) => !isRug(it) && it.w && it.d && it.h && it.sku?.msid && !isWallPlane(it));
  const out = new Map(stableSlotIds(idx.map(({ it }) => it)).map((id, k): [string, number] => [id, idx[k]!.i]));
  // люстра (T-20261112-66) — как картина: `items.length` + номер в декоре; страница (`vwItemAt`) даёт ценник и строку списка
  const lights = decor.map((x, k) => ({ x, k })).filter(({ x }) => isCeilingDecor(x));
  stableSlotIds(lights.map(({ x }) => ({ role: x.role ?? "люстра" }))).forEach((id, j) => out.set(`ceiling:${id}`, items.length + lights[j]!.k));
  if (!art) return out;
  const pics = decor.map((x, k) => ({ x, k })).filter(({ x }) => isWallArtDecor(x))
    .map(({ x, k }) => ({ it: wallArtItems([x])[0]!, k })).filter(({ it }) => isWallPlane(it));
  const mirrors = items.filter(isWallPlane);
  const ids = stableSlotIds([...mirrors, ...pics.map(({ it }) => it)]);
  pics.forEach(({ k }, j) => out.set(ids[mirrors.length + j]!, items.length + k));
  return out;
}

type PrefetchOptions =Pick<DemoSceneOptions, "room" | "items" | "decor" | "base" | "runtimeMeshes" | "lite" | "floor" | "wall">;
/** Транскодер KTX2 (`viewer.ts`: `ktx2Path`): лёгкие копии `/rt/` сжаты в KTX2, и сцена тянет его при первой модели (~0,5 МБ). */
const BASIS = ["/vendor/basis/basis_transcoder.js", "/vendor/basis/basis_transcoder.wasm"];
/** Панорама за окнами (`rooms.ts:buildSurroundings`, адрес по умолчанию). */
const PANORAMA = "/flat3d/env/outside.webp";

/**
 * Всё, что сцена качает при первом показе: модели (`meshes`) и оболочка (`shell`) — карты пола, стен и ковра (дополнительные
 * карты — только в полном режиме, как `LITE_QUALITY.extraMaps`), вид за окном (`windowView`), панорама, транскодер KTX2.
 */
export function sceneAssetUrls(opts: PrefetchOptions): { meshes: string[]; shell: string[] } {
  if (opts.runtimeMeshes) setRuntimeMeshes(opts.runtimeMeshes);
  const built = liveApartment(opts.room, opts.items, opts.base, opts.decor ?? [], opts.floor, opts.wall);
  if (!built) return { meshes: [], shell: [] };
  const { apartment, catalogue } = built;
  const lite = opts.lite === true;
  const sc = resolveScene(apartment, catalogue, defaultConfiguration(apartment, catalogue));
  const specs = planObjects(apartment, catalogue, sc, { lite });
  const meshes = [...new Set(specs.flatMap((s) => (s.kind === "mesh" ? [s.url] : [])))];
  // ковёр и картина — фото товара в материале (у зеркала материал рамы — сплошной цвет, адреса нет и качать нечего)
  const rugIds = new Set(specs.flatMap((s) => ((s.kind === "rug" || s.kind === "wall-plane") && s.materialId ? [s.materialId] : [])));
  const mats = [...sc.surfaces.flatMap((s) => (s.accent ? [s.material, s.accent.material] : [s.material])),
    ...catalogue.materials.filter((m) => rugIds.has(m.id))];
  // лёгкий режим качает тот же файл цвета, что возьмёт `baseMaterial` (512², если есть), — без лишней 1024
  const maps = mats.flatMap((m) => (lite ? [m.baseColorLiteUrl ?? m.baseColorUrl] : [m.baseColorUrl, m.normalUrl, m.roughnessUrl]));
  const views = apartment.rooms.filter((r) => r.openings.some((o) => o.kind === "window")).map((r) => windowView(r.windowView).view.url);
  const shell = [...new Set([...(meshes.some((u) => u.startsWith(RUNTIME_BASE)) ? BASIS : []), ...maps, ...views, PANORAMA]
    .filter((u): u is string => !!u))];
  return { meshes, shell };
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
  }, { curtains: opts.curtains ?? curtainsFromUrl() });
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
    return sceneSlotIndex(current, decor);
  };
  let running: Promise<void> = ready;
  // выделенный предмет переживает пересборку расстановки (замена модели пересоздаёт объект — выделение ставим заново)
  let selected: number | null = null;
  // «Переместить»: исходное место предмета в координатах движка — черновик двигаем от него на сдвиг пальца
  let moveFrom: { x: number; y: number; rot: number } | null = null;
  // кольцо под мышью (T-20261112-36): луч по мебели — не на каждое движение, а раз в HOVER_MS; последнее положение — хвостовым вызовом
  let hover: { x: number; y: number } | null = null;
  let hoverAt = 0;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  const runHover = (): void => {
    hoverTimer = undefined;
    hoverAt = performance.now();
    if (!hover || moveFrom) return;
    const idx = slotIndex();
    viewer.previewWalk(hover.x, hover.y, canvas.getBoundingClientRect(), (id) => idx.has(id));
  };
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
    setLiveEye: (v) => viewer.setLiveEye(v),
    aimLive: () => viewer.aimLive(),
    capture: async (poses, width, height) => {
      await running;                                  // последняя расстановка уже в сцене
      // подсветку выбранного снимает и возвращает сам `capturePhoto` на время кадра (T-20261109-32/2: здесь она гасла на всю съёмку)
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
    frameItem: (index) => {
      const it = current[index];
      const x = Number(it?.x), y = Number(it?.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return "none";
      const r = viewer.frameItem({ x, y });
      viewer.start();
      return r;
    },
    // плюс — направо; `viewer.look` с положительным dx поворачивает налево (перетаскивание «тянет мир»), 0,22° на пиксель
    select: (index) => {
      selected = index;
      const id = index == null ? null : [...slotIndex()].find(([, i]) => i === index)?.[0] ?? null;
      viewer.highlight(id);
      viewer.start();
    },
    warn: (on) => viewer.setOutlineWarn(on),
    moveBegin: (index) => {
      const id = [...slotIndex()].find(([, i]) => i === index)?.[0];
      moveFrom = id ? viewer.beginMove(id) : null;
      viewer.start();
      return moveFrom != null;
    },
    moveBy: (dx, dy, ok, rot) => {
      if (!moveFrom) return;
      viewer.moveDraftTo(moveFrom.x + dx, moveFrom.y + dy, ok, rot);
      viewer.start();
    },
    moveOrigin: () => (moveFrom ? { x: moveFrom.x, y: moveFrom.y } : null),
    moveEnd: (commit) => {
      if (commit) viewer.endMove(); else viewer.cancelMove();
      moveFrom = null;
      viewer.start();
    },
    floorAt: (x, y) => viewer.floorPoint(x, y, canvas.getBoundingClientRect()),
    turn: (deg) => viewer.look(-deg / 0.22, 0),
    windowTap: (x, y) => viewer.walkToWindow(x, y, canvas.getBoundingClientRect()),
    walkTap: (x, y) => {
      const rect = canvas.getBoundingClientRect();
      const idx = slotIndex();
      // ближайшее под пальцем (T-20261112-36): окно > предмет или картина-товар (T-45, есть в `slotIndex`) > пол; ковёр не
      // выбирается (нет в `slotIndex`) — под ним пол, шаг туда
      const aim = viewer.walkAim(x, y, rect, (id) => idx.has(id));
      viewer.hideWalkTarget();
      if (aim.kind === "item") return idx.get(aim.slotId)!;
      // тап по окну — подойти к нему и посмотреть наружу (T-20261112-30, TG 1731)
      if (aim.kind === "window") { viewer.walkToWindow(x, y, rect); return -1; }
      if (aim.kind !== "floor" || opts.walk === false) return -1;
      if (viewer.mode === "photo") viewer.photoToWalk();   // 3D из точки съёмки: шаг по полу — уже прогулка
      viewer.goTo(aim.x, aim.y);
      return -1;
    },
    previewWalk: (x, y) => {
      if (opts.walk === false) return;
      hover = { x, y };
      const wait = HOVER_MS - (performance.now() - hoverAt);
      if (wait > 0) { hoverTimer ??= setTimeout(runHover, wait); return; }
      runHover();
    },
    hideWalkHint: () => {
      hover = null;
      viewer.hideWalkTarget();
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
      const out: { index: number; x: number; y: number; visible: boolean; box: [number, number, number, number] | null }[] = [];
      for (const [id, index] of slotIndex()) {
        const p = viewer.projectSlot(id);
        if (p) out.push({ index, x: p.x, y: p.y, visible: p.visible, box: p.box });
      }
      return out;
    },
    prefetch: (items) => {
      for (const it of items) if (it.sku?.msid) viewer.preloadMesh(meshUrl(it.sku.msid, undefined, opts.lite === true));
    },
    thumbs: (indices, size = 128) => {
      const byIndex = new Map([...slotIndex()].map(([id, i]) => [i, id]));
      return viewer.thumbs(indices.map((i) => byIndex.get(i) ?? ""), size);
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
    dispose: () => {
      clearTimeout(hoverTimer);
      hover = null;
      viewer.dispose();
    },
  };
}
