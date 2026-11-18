// ПРОБА T-20261117-02/2: сцена /demo без страницы — тот же движок (`FlatViewer`), тот же мост (`liveApartment` → `fromDemoVariant`),
// тот же расчёт мест (`resolveScene`: картины, шторы, люстра, подушки) — и выгрузка того, что реально стоит в 3D, в GLB.
// Сборка: esbuild (см. demo_scene_build.sh); запуск — demo_scene_dump.mjs. Ничего из прода не правится, свои правила здесь не добавлены.
import * as THREE from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { liveApartment } from "@/lib/viewer3d/demo-scene";
import { DESKTOP_QUALITY, FlatViewer, LITE_QUALITY } from "@/lib/viewer3d/viewer";
import { sceneAssetUrls } from "@/lib/viewer3d/demo-scene";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { setRuntimeMeshes } from "@/lib/configurator/mesh-url";
import { exportScene } from "@/lib/viewer3d/scene-export";

type Any = any; // eslint-disable-line @typescript-eslint/no-explicit-any

function nodeInfo(root: THREE.Object3D): Any[] {
  const out: Any[] = [];
  root.updateMatrixWorld(true);
  root.traverse((o) => {
    if (!(o as Any).isMesh && !(o as Any).isLight) return;
    const box = new THREE.Box3().setFromObject(o);
    const chain: string[] = [];
    let p: THREE.Object3D | null = o;
    let slot = "";
    let plant = false;
    while (p) { chain.push(p.name || p.type); if (p.userData?.plant) plant = true; if (!slot && p.userData?.slotId) slot = String(p.userData.slotId); p = p.parent; }
    if (!slot && chain.includes("radiators")) slot = "radiator";   // радиатор под окном (`kits/radiator.ts`, T-20261117-11) — группа `radiators` оболочки, предмета-слота нет
    if (plant) slot = `plant:${slot}`;   // растение кашпо/вазы (`kits/plants.ts`) — ребёнок группы носителя; ключ выгрузки `plant`
    out.push({ uuid: o.uuid, type: o.type, name: o.name, chain: chain.slice(0, 6).join("<"), slot, plant, visible: o.visible,
      min: box.min.toArray().map((v) => +v.toFixed(2)), max: box.max.toArray().map((v) => +v.toFixed(2)),
      mat: ((o as Any).material?.name) || "", emissive: (o as Any).material?.emissive?.getHexString?.() ?? null });
  });
  return out;
}

(window as Any).__scene = null;
// что /demo качает при первом показе (модели и оболочка) — для замера байтов «до/после» (`sceneAssetUrls`: тот же расчёт, что у страницы)
(window as Any).assetUrls = (a: { room: Any; items: Any[]; decor: Any[]; base: string; lite?: boolean }) => sceneAssetUrls({ ...a, runtimeMeshes: undefined } as Any);

// снимок кадра по ракурсу квартиры (как «Ракурс» страницы): JPEG base64, ширина × высота в пикселях; в `ms` — время от сборки сцены до готового кадра
(window as Any).shot = async (camIndex: number, w: number, h: number) => {
  const viewer: Any = (window as Any).__viewer;
  const cams = (window as Any).__cams as Any[];   // ракурсы варианта витрины (`v.cams`), как их ставит страница
  const c = cams[camIndex];
  const t0 = performance.now();
  const blob: Blob = await viewer.capturePhoto({ x: c.x, y: c.y, rot: c.rot, fov: c.fov, pose: c.pose, pshift: c.pshift }, w, h, 0.9, { tilt: h > w });
  const buf = new Uint8Array(await blob.arrayBuffer());
  let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return { b64: btoa(s), ms: Math.round(performance.now() - t0), cams: cams.length };
};

// КАМЕРА ЖИВОЙ 3D КАК НА СТРАНИЦЕ (владелец TG 1504/1505: «прямо в таком же виде, как на телефоне»): тот же движок и те же вызовы, что `liveFit` страницы —
// размер холста, «3D глазами стоящего» (глаз 152 см, видимая полоса `band`), поза ракурса `v.cams[camIndex]`, наклон по мебели (`aimLive`); камеру читаем
// после нескольких кадров цикла. Единицы сцены — метры (`CM = 0.01`): три-оси (x, высота, план_y).
(window as Any).liveCamera = async (camIndex: number, w: number, h: number, band: { top: number; bottom: number }) => {
  const viewer: Any = (window as Any).__viewer;
  const c = ((window as Any).__cams as Any[])[camIndex];
  viewer.setSize(w, h);
  viewer.setLiveEye({ eyeCm: 152, band });
  viewer.setPhotoPose({ x: c.x, y: c.y, rot: c.rot, fov: c.fov, pose: c.pose, pshift: c.pshift });
  viewer.aimLive();
  viewer.start();
  await new Promise((r) => setTimeout(r, 1500));
  viewer.aimLive();
  await new Promise((r) => setTimeout(r, 1500));
  viewer.stop();
  const cam = viewer.camera;
  cam.updateMatrixWorld(true);
  const dir = cam.getWorldDirection(cam.position.clone());
  const up = cam.up.clone().applyQuaternion(cam.quaternion);
  return { pos: cam.position.toArray(), dir: dir.toArray(), up: up.toArray(), vfov: cam.fov, aspect: cam.aspect, offsetY: cam.view?.offsetY ?? 0, w, h, band, pose: { x: c.x, y: c.y, rot: c.rot, fov: c.fov } };
};

// РАЗОБРАННЫЕ МЕШИ МЕЖДУ ЗАКАЗАМИ (T-20261118-09/1 шаг 6b, постоянный процесс `demo_scene_dump.mjs --serve`): `GLTFLoader.load` по адресу отдаёт уже разобранный glTF
// (разбор + декод текстур ≈ 3 с на гостиную), пока страница жива. Включается флагом заказа `persist`; одноразовый запуск — как раньше. Меши в сцене берутся клонами
// (`placeMesh`: `source.clone(true)`, материалы свои), общий исходник вьюер не правит; запись держится по последнему использованию, не больше GLTF_CACHE_MAX.
let GLTF_CACHE_ON = false;
let REUSE_CANVAS = false;   // постоянная страница (`persist`): холст и контекст WebGL между заказами общие (замер ниже)
// ПРОФИЛЬ СБОРКИ (отладка, `prof=1` в заказе дампера): события со временем от начала `buildDemoScene` — загрузки мешей (попадание/промах) и методы вьюера
const PROF: Any[] = [];
let PROF_ON = false, PROF_T0 = 0;
const pev = (n: string) => { if (PROF_ON) PROF.push([n, Math.round(performance.now() - PROF_T0)]); };
const tailOf = (u: string) => String(u).split("/").slice(-2).join("/").slice(0, 40);
// потолок кэша — по ОЦЕНКЕ размера разобранных мешей, не по числу: меш ≈ 33 МБ (карта 2048² + геометрия), гостиная — 12–14 мешей; при потолке в 6 штук обход одних и тех же 12 мешей по кругу
// выбивал каждого до повторного обращения (попаданий 0). Память процесса держит клиент (`DUMP_KEEP_GB`): выше — перезапуск.
const GLTF_CACHE_MB = Number((globalThis as Any).__gltfCacheMb ?? 480);
const GLTF_CACHE_MAX = 64;
const gltfCache = new Map<string, Any>();
const gltfMb = new Map<string, number>();
const gltfStamp = new Map<string, number>();       // номер заказа, где запись использована последний раз; записи ТЕКУЩЕГО заказа не вытесняем (их картинки в сцене)
let ORDER_N = 0;
const closeGltf = (g: Any) => {      // картинки вытесненного разбора освобождаем сразу (ImageBitmap держит память вне кучи JS)
  try { g.scene.traverse((o: Any) => { const mm = o.material; if (!mm) return; for (const m of Array.isArray(mm) ? mm : [mm]) for (const k in m) { const t = m[k]; if (t && t.isTexture) { t.image?.close?.(); } } }); } catch { /* не критично */ }
};
const gltfSizeMb = (g: Any): number => {      // оценка размера разобранного glTF: картинки (ширина×высота×4, каждая один раз) + буферы геометрии
  const seen = new Set<Any>(); let b = 0;
  g.scene.traverse((o: Any) => {
    const geo = o.geometry; if (geo) { for (const k in geo.attributes) b += geo.attributes[k].array.byteLength; if (geo.index) b += geo.index.array.byteLength; }
    const mm = o.material; if (!mm) return;
    for (const m of Array.isArray(mm) ? mm : [mm]) for (const k in m) { const t = m[k]; if (t && t.isTexture && t.image && !seen.has(t.image)) { seen.add(t.image); b += (t.image.width || 0) * (t.image.height || 0) * 4; } }
  });
  return b / 2 ** 20;
};
{
  const proto = GLTFLoader.prototype as Any, orig = proto.load;
  proto.load = function (url: string, onLoad: Any, onProgress: Any, onError: Any) {
    if (!GLTF_CACHE_ON || typeof url !== "string" || !/\.glb(\?|$)/.test(url)) return orig.call(this, url, onLoad, onProgress, onError);
    // ключ — адрес + подпись файла на диске (размер, время; даёт процесс выгрузки, `__sigOf`): меш пересобрали под тем же адресом — старый разбор не отдаём;
    // подписи нет (файл с сайта, не с диска) — в кэш не кладём вовсе
    const self = this;
    pev("gltf>" + tailOf(url));
    const onLoad0 = onLoad;
    onLoad = (g: Any) => { pev("gltf<" + tailOf(url)); onLoad0(g); };
    const run = (sig: string) => {
      if (!sig) { pev("nosig " + tailOf(url)); return orig.call(self, url, onLoad, onProgress, onError); }
      const key = `${url}|${sig}`;
      const hit = gltfCache.get(key);
      pev((hit ? "HIT " : "MISS ") + tailOf(url));
      if (hit) {
        gltfCache.delete(key);
        gltfCache.set(key, hit);                             // свежесть — в конец
        gltfStamp.set(key, ORDER_N);
        setTimeout(() => onLoad(hit), 0);
        return;
      }
      return orig.call(self, url, (gltf: Any) => {
        gltfCache.set(key, gltf);
        gltfMb.set(key, gltfSizeMb(gltf));
        gltfStamp.set(key, ORDER_N);
        for (;;) {
          let tot = 0; for (const k of gltfCache.keys()) tot += gltfMb.get(k) ?? 0;
          if (gltfCache.size <= 1 || (tot <= GLTF_CACHE_MB && gltfCache.size <= GLTF_CACHE_MAX)) break;
          const old = [...gltfCache.keys()].find((k) => (gltfStamp.get(k) ?? -1) < ORDER_N);      // самая давняя запись прошлых заказов
          if (!old) break;                                   // всё нужно текущему заказу — потолок временно выше
          closeGltf(gltfCache.get(old)); gltfCache.delete(old); gltfMb.delete(old); gltfStamp.delete(old);
        }
        onLoad(gltf);
      }, onProgress, onError);
    };
    const sigOf = (window as Any).__sigOf as ((u: string) => Promise<string>) | undefined;
    if (!sigOf) return run("");
    sigOf(url).then(run, () => run(""));
  };
}

// ГОТОВНОСТЬ ВМЕСТО ПАУЗЫ (T-20261118-09/1 шаг 3): раньше после `plantsSettled` стояла безусловная пауза 1,5 с «пусть догрузятся картинки».
// Теперь — пока (а) идут загрузки через менеджер three (`DefaultLoadingManager`: текстуры, картинки), (б) у какой-нибудь карты материала сцены
// картинка ещё не загружена. Нужна тишина ТРИ шага подряд (≈150 мс), потолок — прежние 1,5 с (хуже прежнего быть не может). `settle: false` — прежняя пауза.
let LOADING = 0;
{
  const dm = THREE.DefaultLoadingManager as Any, s0 = dm.itemStart.bind(dm), e0 = dm.itemEnd.bind(dm);
  dm.itemStart = (u: string) => { LOADING++; s0(u); };
  dm.itemEnd = (u: string) => { LOADING = Math.max(0, LOADING - 1); e0(u); };
}
const texturesPending = (scene: THREE.Scene): number => {
  let n = 0;
  scene.traverse((o) => {
    const mm: Any = (o as Any).material;
    if (!mm) return;
    for (const m of Array.isArray(mm) ? mm : [mm]) for (const k in m) {
      const t = m[k];
      if (!t || !t.isTexture) continue;
      const im = t.image;
      if (!im) n++;
      else if (typeof HTMLImageElement !== "undefined" && im instanceof HTMLImageElement && !(im.complete && im.naturalWidth > 0)) n++;
    }
  });
  return n;
};
const settleScene = async (scene: THREE.Scene, capMs: number): Promise<number> => {
  const t0 = performance.now();
  let quiet = 0;
  while (performance.now() - t0 < capMs && quiet < 3) {
    await new Promise((r) => setTimeout(r, 50));
    quiet = LOADING === 0 && texturesPending(scene) === 0 ? quiet + 1 : 0;
  }
  return (performance.now() - t0) / 1000;
};

(window as Any).buildDemoScene = async (a: { room: Any; items: Any[]; decor: Any[]; base: string; runtime?: Any; lite?: boolean; cams?: Any[]; style?: string; settle?: boolean; persist?: boolean }) => {
  GLTF_CACHE_ON = !!a.persist;
  REUSE_CANVAS = !!a.persist && !(window as Any).__noReuseCanvas;
  ORDER_N++;
  PROF.length = 0; PROF_ON = !!(a as Any).prof; PROF_T0 = performance.now();
  if (a.persist) {                                          // постоянная страница: вьюер прошлого заказа — долой (его холст и записи сцены)
    pev("start");
    // `FlatViewer.dispose` в конце вызывает `renderer.forceContextLoss()` (живая страница: контексты WebGL не копятся, их ≤16): в Chromium на swiftshader вызов ждёт процесс GPU
    // и стоит ≈1,1–1,4 с на КАЖДЫЙ заказ (замер T-20261118-10/4). Дампер контекст прошлого заказа не терял бы никак иначе — холст ниже снимается, контекст уйдёт со сборкой мусора
    // (а свыше 16 браузер гасит самый старый сам); живой вьюер (`lib/viewer3d/viewer.ts`) не меняется — подмена только на объекте рендерера этой страницы.
    { const rv: Any = (window as Any).__viewer?.renderer; if (rv && !(window as Any).__dumpKeepCtx) rv.forceContextLoss = () => {}; }
    try { (window as Any).__viewer?.dispose?.(); } catch { /* прошлый вьюер мог не успеть собраться */ }
    pev("disposed");
    (window as Any).__viewer = (window as Any).__scene = (window as Any).__sc = (window as Any).__export = null;
    if (!REUSE_CANVAS) for (const c of Array.from(document.querySelectorAll("canvas"))) c.remove();
    pev("canvasRemoved");
  }
  const T0 = performance.now(), trace: Any[] = [];      // ТРАССА (T-20261118-09/1): шаги сборки сцены в странице, секунды от начала `buildDemoScene`
  const mark = (name: string) => trace.push({ name, s: ((performance.now() - T0) / 1000).toFixed(2) });
  // 1) описание сцены для рендера (`scene-export.ts`) — с ЖИВОЙ таблицей runtime-копий (`/demo/rt-meshes.json`, a.runtime): хеши и «нет лёгкой копии»
  setRuntimeMeshes(a.runtime ?? {});
  const first = liveApartment(a.room, a.items, a.base, a.decor, undefined, undefined, a.style);
  if (!first) throw new Error("пустая расстановка");
  const sc0 = resolveScene(first.apartment, first.catalogue, defaultConfiguration(first.apartment, first.catalogue));
  (window as Any).__export = exportScene(first.apartment, first.catalogue, sc0, { lite: false });
  mark("liveApartment_resolve_exportScene");
  setRuntimeMeshes({});            // 2) для выгрузки узлов — полные исходники галереи, не лёгкие копии
  let cv: HTMLCanvasElement | undefined = REUSE_CANVAS ? (window as Any).__cv : undefined;
  if (!cv) {
    cv = document.createElement("canvas");
    cv.width = 640; cv.height = 480;
    document.body.appendChild(cv);
    if (REUSE_CANVAS) (window as Any).__cv = cv;
  }
  const viewer = new FlatViewer(cv, first.apartment, first.catalogue, a.lite ? LITE_QUALITY : DESKTOP_QUALITY, {}, { curtains: true });
  (window as Any).__viewer = viewer;
  mark("FlatViewer_ctor");
  if (PROF_ON) for (const m of ["addObject", "bakeContact", "settleSoft", "waitCarriers", "loadMesh", "placeGroup"]) {
    const vw: Any = viewer, o = vw[m]; if (typeof o !== "function") continue;
    vw[m] = function (this: Any, ...x: Any[]) { pev(">" + m); const r = o.apply(this, x); if (r && r.then) return r.then((v: Any) => { pev("<" + m); return v; }); pev("<" + m); return r; };
  }
  (window as Any).__cams = a.cams ?? [];
  (window as Any).__tBuild = performance.now();
  const sc = resolveScene(first.apartment, first.catalogue, defaultConfiguration(first.apartment, first.catalogue));
  viewer.buildShell(sc);
  mark("buildShell");
  await viewer.syncObjects(sc);
  mark("syncObjects_glb");
  await viewer.plantsSettled();    // растения догружаются после мебели (`kits/plants.ts`); в экспорт идут журнал и узлы с флагом `plant`
  mark("plantsSettled");
  if (a.settle === false) { await new Promise((r) => setTimeout(r, 1500)); mark("pause_1500"); }
  else { const w = await settleScene(viewer.scene, 1500); mark("settle_" + w.toFixed(2)); }
  // замена товара на странице ведёт анимацию (подрастание 0.94 → 1 за 250 мс, силуэт прежнего): выгрузка — только по конечному состоянию, не по часам
  pev("syncDone");
  viewer.settleSwaps();
  // порядок журнала растений — по порядку загрузки (гонка): сортируем по слоту, чтобы одна сцена давала один файл
  const plants = [...viewer.plantReport()].sort((x, y) => (x.slotId < y.slotId ? -1 : x.slotId > y.slotId ? 1 : 0));
  (window as Any).__export = { ...(window as Any).__export, plants };
  (window as Any).__scene = viewer.scene;
  (window as Any).__sc = sc;
  pev("settled");
  (window as Any).__prof_out = PROF.slice();
  return {
    trace,
    slots: sc.items.map((i: Any) => ({ slotId: i.slotId, roomId: i.roomId, role: i.photoRole, kind: i.asset?.kind, kit: i.asset?.kit, features: i.asset?.features, unplaced: !!i.unplaced,
      hungOver: i.hungOver ?? null, placement: i.placement, title: i.titleRu })),
    nodes: nodeInfo(viewer.scene),
  };
};

// материалы оболочки комнаты (стены, пол, потолок, плинтус, окно) — что реально стоит в сцене /demo: тип, цвет, карты
(window as Any).shellInfo = () => {
  const out: Any[] = [];
  const scene: THREE.Scene = (window as Any).__scene;
  scene.traverse((o) => {
    if (!(o as Any).isMesh) return;
    let chain = "";
    for (let p: THREE.Object3D | null = o; p; p = p.parent) chain += (p.name || p.type) + "<";
    if (!/wall:|floor:|ceiling:|fixtures:|joinery:|window-view/.test(chain)) return;
    const m: Any = Array.isArray((o as Any).material) ? (o as Any).material[0] : (o as Any).material;
    out.push({ chain: chain.slice(0, 80), type: m.type, color: m.color?.getHexString?.() ?? null, map: !!m.map, normalMap: !!m.normalMap, bumpMap: !!m.bumpMap,
      roughnessMap: !!m.roughnessMap, rough: m.roughness ?? null, metal: m.metalness ?? null, emissive: m.emissive?.getHexString?.() ?? null,
      opacity: m.opacity ?? null, transparent: !!m.transparent, side: m.side, userMat: m.name || "" });
  });
  return out;
};

// выгрузка выбранных узлов (по uuid) в GLB — с мировыми матрицами, чтобы Blender получил их на местах
// ТРАССА выгрузки узлов: время в кодировании картинок холстом (`toBlob`/`convertToBlob` — PNG/JPEG внутри GLB), в самом экспортёре и в base64 — в журнал (`TRACE page export_*`)
const EXPORT_MARKS: Any[] = [];
let ENCODE_MS = 0, ENCODE_N = 0;
{
  const tb = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function (cb: Any, ...rest: Any[]) {
    const t = performance.now();
    return tb.call(this, (b: Any) => { ENCODE_MS += performance.now() - t; ENCODE_N++; cb(b); }, ...rest);
  };
  const OC = (globalThis as Any).OffscreenCanvas;
  if (OC?.prototype?.convertToBlob) {
    const cv = OC.prototype.convertToBlob;
    OC.prototype.convertToBlob = function (...a: Any[]) {
      const t = performance.now();
      return cv.apply(this, a).then((b: Any) => { ENCODE_MS += performance.now() - t; ENCODE_N++; return b; });
    };
  }
}
(window as Any).exportMarks = () => EXPORT_MARKS;
(window as Any).exportImages = () => Array.from(XIMG_ORDER.values()).map(({ name, sha, bytes }) => ({ name, sha256: sha, bytes }));
(window as Any).imageBytes = async (name: string) => {
  const m = XIMG_ORDER.get(name);
  if (!m) return "";
  const fr = new FileReader();
  return await new Promise<string>((res, rej) => { fr.onload = () => res(String(fr.result).slice(String(fr.result).indexOf(",") + 1)); fr.onerror = () => rej(fr.error); fr.readAsDataURL(m.blob); });
};

// КЭШ КОДИРОВАННЫХ КАРТИНОК GLB (T-20261118-10/1 (а)): экспортёр three каждую текстуру рисует на холсте и кодирует PNG/JPEG заново (7–9 штук, ≈1 с на гостиную), хотя картинки
// у заказов те же. Здесь результат — тот самый Blob холста — запоминается и отдаётся без рисования и кодирования; байты картинок в GLB те же, что без кэша.
// Ключ: (объект картинки | адрес + подпись файла) × тип × переворот × размер. Объект картинки — `ImageBitmap` из разобранного меша (живёт, пока жив кэш разборов `gltfCache`);
// адрес — `HTMLImageElement` карт материалов оболочки (каждый заказ грузит заново), подпись (размер-время) даёт процесс выгрузки (`__sigOf`; нет подписи — без кэша).
// `DataTexture`, холсты (тонированные «на лету») и всё прочее — прежним путём. Включается вместе с `persist`; одноразовый запуск — без кэша.
let ENC_HIT = 0, ENC_MISS = 0, ENC_SKIP = 0;
const ENC_BY_OBJ = new WeakMap<object, Map<string, Blob>>();
const ENC_BY_URL = new Map<string, Blob>();
const ENC_URL_MAX = Number((globalThis as Any).__encUrlMax ?? 40);
const encodeImage = async (image: Any, flipY: boolean, mimeType: string, maxSize: number, sigOf?: (u: string) => Promise<string>): Promise<{ blob: Blob; how: string } | null> => {
  const w = Math.min(image.width, maxSize), h = Math.min(image.height, maxSize);
  const sub = `${mimeType}:${flipY}:${w}x${h}`;
  let byObj: Map<string, Blob> | null = null, urlKey = "";
  if (typeof ImageBitmap !== "undefined" && image instanceof ImageBitmap) {
    byObj = ENC_BY_OBJ.get(image) ?? null;
    const hit = byObj?.get(sub);
    if (hit) return { blob: hit, how: "hit" };
  } else if (typeof HTMLImageElement !== "undefined" && image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0 && sigOf) {
    const sig = await sigOf(image.src).catch(() => "");
    if (!sig) return null;
    urlKey = `${image.src}|${sig}|${sub}`;
    const hit = ENC_BY_URL.get(urlKey);
    if (hit) { ENC_BY_URL.delete(urlKey); ENC_BY_URL.set(urlKey, hit); return { blob: hit, how: "hit" }; }
  } else return null;
  // рисуем и кодируем РОВНО как `GLTFExporter.processImage` (тот же холст, тот же переворот, тот же `toBlob`): байты те же
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true }) as CanvasRenderingContext2D;
  if (flipY) { ctx.translate(0, canvas.height); ctx.scale(1, -1); }
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob: Blob = await new Promise((res) => canvas.toBlob((b) => res(b as Blob), mimeType));
  canvas.width = canvas.height = 0;       // память холста (2048² ≈ 16 МБ на картинку) отдаём сразу, а не сборщику: у постоянной страницы она копилась (≈300 МБ на заказ)
  if (urlKey) { ENC_BY_URL.set(urlKey, blob); while (ENC_BY_URL.size > ENC_URL_MAX) ENC_BY_URL.delete(ENC_BY_URL.keys().next().value as string); }
  else { if (!byObj) { byObj = new Map(); ENC_BY_OBJ.set(image, byObj); } byObj.set(sub, blob); }
  return { blob, how: "miss" };
};
// ВНЕШНИЕ КАРТИНКИ GLB (T-20261118-10/1, `ximg=1`): вместо вшивания в GLB (bufferView) картинка получает `uri = img/<sha256[:32]>.<png|jpg>` (рядом с GLB), её байты — те же, что вшивались.
// Имя = хеш содержимого: одна и та же картинка у разных заказов — один и тот же файл (его не пересылают и не пишут снова). Список (имя, полный sha256, размер) — `exportImages()`,
// байты по имени — `imageBytes(name)` (процесс выгрузки забирает только те, которых нет в его общем кэше).
const XIMG_META = new WeakMap<Blob, { name: string; sha: string; bytes: number }>();
const XIMG_ORDER = new Map<string, { name: string; sha: string; bytes: number; blob: Blob }>();
const EXT_OF: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" };
const ximgMeta = async (blob: Blob, mime: string) => {
  let m = XIMG_META.get(blob);
  if (m) return m;
  const buf = await blob.arrayBuffer();
  const dig = new Uint8Array(await crypto.subtle.digest("SHA-256", buf));
  const sha = Array.from(dig, (b) => b.toString(16).padStart(2, "0")).join("");
  m = { name: `${sha.slice(0, 32)}.${EXT_OF[mime] ?? "bin"}`, sha, bytes: buf.byteLength };
  XIMG_META.set(blob, m);
  return m;
};
const encodeCachePlugin = (opts: { maxTextureSize: number; ximg?: boolean }) => (writer: Any) => {
  const orig = writer.processImage.bind(writer);
  writer.processImage = (image: Any, format: number, flipY: boolean, mimeType = "image/png") => {
    const cacheable = (GLTF_CACHE_ON || !!opts.ximg) && image && image.data === undefined && !(image instanceof HTMLCanvasElement) && !(typeof OffscreenCanvas !== "undefined" && image instanceof OffscreenCanvas);
    if (!cacheable) { ENC_SKIP++; return orig(image, format, flipY, mimeType); }
    const cache = writer.cache, json = writer.json;
    if (!cache.images.has(image)) cache.images.set(image, {});
    const cached = cache.images.get(image);
    const key = mimeType + ":flipY/" + flipY.toString();
    if (cached[key] !== undefined) return cached[key];
    if (!json.images) json.images = [];
    const imageDef: Any = { mimeType };
    writer.pending.push(
      encodeImage(image, flipY, mimeType, opts.maxTextureSize, (window as Any).__sigOf).then(async (r) => {
        if (!r) {            // не наш случай (нет подписи и т.п.) — тот же путь, что в экспортёре, без кэша
          const c = document.createElement("canvas");
          c.width = Math.min(image.width, opts.maxTextureSize); c.height = Math.min(image.height, opts.maxTextureSize);
          const cx = c.getContext("2d", { willReadFrequently: true }) as CanvasRenderingContext2D;
          if (flipY) { cx.translate(0, c.height); cx.scale(1, -1); }
          cx.drawImage(image, 0, 0, c.width, c.height);
          ENC_SKIP++;
          const bl = await new Promise<Blob>((res) => c.toBlob((b) => res(b as Blob), mimeType));
          c.width = c.height = 0;
          return bl;
        }
        if (r.how === "hit") ENC_HIT++; else ENC_MISS++;
        return r.blob;
      }).then(async (blob: Blob) => {
        if (!opts.ximg) { imageDef.bufferView = await writer.processBufferViewImage(blob); return; }
        const m = await ximgMeta(blob, mimeType);
        XIMG_ORDER.set(m.name, { ...m, blob });
        imageDef.uri = `img/${m.name}`;
      }),
    );
    const index = json.images.push(imageDef) - 1;
    cached[key] = index;
    return index;
  };
  return {};
};
(window as Any).exportNodes = async (uuids: string[], opts?: { ximg?: boolean }) => {
  XIMG_ORDER.clear();
  const tE0 = performance.now();
  ENCODE_MS = 0; ENCODE_N = 0; ENC_HIT = 0; ENC_MISS = 0; ENC_SKIP = 0;
  EXPORT_MARKS.length = 0;
  const scene: THREE.Scene = (window as Any).__scene;
  scene.updateMatrixWorld(true);
  const root = new THREE.Group();
  root.name = "decor_root";
  const want = new Set(uuids);
  scene.traverse((o) => {
    if (!want.has(o.uuid)) return;
    const c = o.clone(false) as Any;
    c.matrixAutoUpdate = false;
    o.matrixWorld.decompose(c.position, c.quaternion, c.scale);
    c.matrixAutoUpdate = true;
    c.name = `${o.name || o.type}__${o.uuid}`;
    root.add(c);
  });
  const tE1 = performance.now();
  const ex = new GLTFExporter();
  ex.register(encodeCachePlugin({ maxTextureSize: 2048, ximg: !!opts?.ximg }));
  const buf: ArrayBuffer = await ex.parseAsync(root, { binary: true, onlyVisible: false, maxTextureSize: 2048 }) as ArrayBuffer;
  const tE2 = performance.now();
  // base64 средствами браузера (`FileReader.readAsDataURL`): тот же текст, что давал цикл `btoa(String.fromCharCode…)`, но без миллионов строк (≈0,7 с → десятки мс)
  const out: string = await new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).slice(String(fr.result).indexOf(",") + 1));
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(new Blob([buf]));
  });
  const tE3 = performance.now();
  EXPORT_MARKS.push({ name: "export_clone", s: ((tE1 - tE0) / 1000).toFixed(2) }, { name: "export_parse", s: ((tE2 - tE1) / 1000).toFixed(2) },
    { name: "export_encode_in_parse", s: (ENCODE_MS / 1000).toFixed(2) }, { name: "export_encode_n", s: String(ENCODE_N) }, { name: "export_enc_hit", s: String(ENC_HIT) }, { name: "export_enc_miss", s: String(ENC_MISS) }, { name: "export_enc_skip", s: String(ENC_SKIP) },
    { name: "export_b64", s: ((tE3 - tE2) / 1000).toFixed(2) }, { name: "export_mb", s: (buf.byteLength / 1048576).toFixed(2) });
  return out;
};
