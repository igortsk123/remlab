// ПРОБА T-20261117-02/2: сцена /demo без страницы — тот же движок (`FlatViewer`), тот же мост (`liveApartment` → `fromDemoVariant`),
// тот же расчёт мест (`resolveScene`: картины, шторы, люстра, подушки) — и выгрузка того, что реально стоит в 3D, в GLB.
// Сборка: esbuild (см. demo_scene_build.sh); запуск — demo_scene_dump.mjs. Ничего из прода не правится, свои правила здесь не добавлены.
import * as THREE from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { liveApartment } from "@/lib/viewer3d/demo-scene";
import { DESKTOP_QUALITY, FlatViewer } from "@/lib/viewer3d/viewer";
import { defaultConfiguration, resolveScene } from "@/lib/configurator/resolve";
import { setRuntimeMeshes } from "@/lib/configurator/mesh-url";

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
    while (p) { chain.push(p.name || p.type); if (!slot && p.userData?.slotId) slot = String(p.userData.slotId); p = p.parent; }
    out.push({ uuid: o.uuid, type: o.type, name: o.name, chain: chain.slice(0, 6).join("<"), slot, visible: o.visible,
      min: box.min.toArray().map((v) => +v.toFixed(2)), max: box.max.toArray().map((v) => +v.toFixed(2)),
      mat: ((o as Any).material?.name) || "", emissive: (o as Any).material?.emissive?.getHexString?.() ?? null });
  });
  return out;
}

(window as Any).__scene = null;
(window as Any).buildDemoScene = async (a: { room: Any; items: Any[]; decor: Any[]; base: string }) => {
  setRuntimeMeshes({});            // полные исходники галереи, не лёгкие копии
  const first = liveApartment(a.room, a.items, a.base, a.decor);
  if (!first) throw new Error("пустая расстановка");
  const cv = document.createElement("canvas");
  cv.width = 640; cv.height = 480;
  document.body.appendChild(cv);
  const viewer = new FlatViewer(cv, first.apartment, first.catalogue, DESKTOP_QUALITY, {}, { curtains: true });
  const sc = resolveScene(first.apartment, first.catalogue, defaultConfiguration(first.apartment, first.catalogue));
  viewer.buildShell(sc);
  await viewer.syncObjects(sc);
  await new Promise((r) => setTimeout(r, 1500));
  (window as Any).__scene = viewer.scene;
  (window as Any).__sc = sc;
  return {
    slots: sc.items.map((i: Any) => ({ slotId: i.slotId, roomId: i.roomId, role: i.photoRole, kind: i.asset?.kind, kit: i.asset?.kit, unplaced: !!i.unplaced,
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
