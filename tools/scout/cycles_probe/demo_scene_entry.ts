// ПРОБА T-20261117-02/2: сцена /demo без страницы — тот же движок (`FlatViewer`), тот же мост (`liveApartment` → `fromDemoVariant`),
// тот же расчёт мест (`resolveScene`: картины, шторы, люстра, подушки) — и выгрузка того, что реально стоит в 3D, в GLB.
// Сборка: esbuild (см. demo_scene_build.sh); запуск — demo_scene_dump.mjs. Ничего из прода не правится, свои правила здесь не добавлены.
import * as THREE from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
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

(window as Any).buildDemoScene = async (a: { room: Any; items: Any[]; decor: Any[]; base: string; runtime?: Any; lite?: boolean; cams?: Any[]; style?: string }) => {
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
  const cv = document.createElement("canvas");
  cv.width = 640; cv.height = 480;
  document.body.appendChild(cv);
  const viewer = new FlatViewer(cv, first.apartment, first.catalogue, a.lite ? LITE_QUALITY : DESKTOP_QUALITY, {}, { curtains: true });
  (window as Any).__viewer = viewer;
  mark("FlatViewer_ctor");
  (window as Any).__cams = a.cams ?? [];
  (window as Any).__tBuild = performance.now();
  const sc = resolveScene(first.apartment, first.catalogue, defaultConfiguration(first.apartment, first.catalogue));
  viewer.buildShell(sc);
  mark("buildShell");
  await viewer.syncObjects(sc);
  mark("syncObjects_glb");
  await viewer.plantsSettled();    // растения догружаются после мебели (`kits/plants.ts`); в экспорт идут журнал и узлы с флагом `plant`
  mark("plantsSettled");
  await new Promise((r) => setTimeout(r, 1500));
  mark("pause_1500");
  (window as Any).__export = { ...(window as Any).__export, plants: viewer.plantReport() };
  (window as Any).__scene = viewer.scene;
  (window as Any).__sc = sc;
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
(window as Any).exportNodes = async (uuids: string[]) => {
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
  const buf: ArrayBuffer = await new GLTFExporter().parseAsync(root, { binary: true, onlyVisible: false, maxTextureSize: 2048 }) as ArrayBuffer;
  let s = "";
  const u = new Uint8Array(buf);
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
};
