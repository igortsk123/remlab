// СТЕНД СНИМКОВ НАБОРА КУХНИ (план onb-09 часть А): страница стенда зовёт `window.snap(case)` — набор `buildKitchen`
// встаёт у задней стены на сером полу, камера в три четверти берёт его целиком. Драйвер — `tools/flat3d/kitchen-snap.mjs`.

import * as THREE from "three";

import type { Material } from "@/contracts/configurator";
import { CM, type KitCtx } from "@/lib/viewer3d/kits/common";
import { buildKitchen, type KitchenSpec } from "@/lib/viewer3d/kits/kitchen";
import { createMaterialCtx } from "@/lib/viewer3d/materials";

import { placeKit, roomCamera, roomShell, type SnapRoom } from "./room";

interface SnapCase {
  spec: KitchenSpec;
  materials: Material[];
  /** Фото источника рядом с кадром (сравнение цвета и пропорций); нет — только кадр. */
  photo?: string;
  caption?: string;
  /** Кухня на квартире: комната с проёмами, набор по посадке, камера сверху / из двери / два вида (`./room.ts`). */
  room?: SnapRoom;
}

declare global {
  interface Window {
    snap: (c: SnapCase) => Promise<void>;
  }
}

const WALL = new THREE.MeshStandardMaterial({ color: 0xf1efea, roughness: 0.9 });
const FLOOR = new THREE.MeshStandardMaterial({ color: 0xb9b6b0, roughness: 0.85 });

async function texturesReady(cache: Map<string, THREE.Texture>, ms = 6000): Promise<void> {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if ([...cache.values()].every((t) => t.image)) return;
    await new Promise((r) => setTimeout(r, 100));
  }
}

window.snap = async (c: SnapCase): Promise<void> => {
  const photo = document.getElementById("photo") as HTMLImageElement;
  const cap = document.getElementById("cap") as HTMLElement;
  photo.style.display = c.photo ? "" : "none";
  if (c.photo) {
    photo.src = c.photo;
    await photo.decode().catch(() => undefined);
  }
  cap.textContent = c.caption ?? "";
  document.body.classList.toggle("pair", !!c.photo);

  const host = document.getElementById("view") as HTMLElement;
  const w = host.clientWidth;
  const h = host.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(w, h);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  host.replaceChildren(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe9edf0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(1.5, 3.5, 3);
  sun.castShadow = true;
  scene.add(sun);

  const byId = new Map(c.materials.map((m) => [m.id, m]));
  const fallback: Material = { id: "fallback", titleRu: "", titleEn: "", colorHex: "#d3d3d3", roughness: 0.6, metalness: 0, tileCm: [100, 100], surfaces: [] };
  const mctx = createMaterialCtx(4, true);
  const ctx: KitCtx = { materials: mctx, byId: (id) => byId.get(id), fallback };
  const kit = buildKitchen(ctx, c.spec);
  scene.add(kit);
  if (c.room) {
    placeKit(kit, c.room);
    scene.add(roomShell(c.room));
    sun.position.set((c.room.w / 2) * CM + 1, 4, (c.room.d / 2) * CM + 1.5);
    sun.target.position.set((c.room.w / 2) * CM, 0, (c.room.d / 2) * CM);
    scene.add(sun.target);
    kit.traverse((o) => { o.castShadow = true; });
    await texturesReady(mctx.cache);
    renderer.render(scene, roomCamera(c.room, w / h));
    document.body.dataset.ready = String(Date.now());
    return;
  }

  // задняя стена, боковая (для угловой, кроме полуострова — он стоит в комнате) и пол — как в комнате, иначе кадр не сравнить с фото
  const box = new THREE.Box3().setFromObject(kit);
  const back = -c.spec.depthCm / 2;
  const span = (box.max.x - box.min.x) / CM + 80;
  const wall = new THREE.Mesh(new THREE.BoxGeometry(span * CM, 2.6, 0.04), WALL);
  wall.position.set(((box.max.x + box.min.x) / 2), 1.3, back * CM - 0.02);
  wall.receiveShadow = true;
  scene.add(wall);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(span * CM, 6), FLOOR);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(wall.position.x, 0, back * CM + 3);
  floor.receiveShadow = true;
  scene.add(floor);
  if (c.spec.shape === "corner" && !c.spec.peninsula) {
    const side = new THREE.Mesh(new THREE.BoxGeometry(0.04, 2.6, 4), WALL);
    const atEnd = (c.spec.cornerAt ?? ((c.spec.columnsAt ?? "start") === "end" ? "start" : "end")) === "end";
    side.position.set((atEnd ? c.spec.widthCm / 2 : -c.spec.widthCm / 2) * CM + (atEnd ? 0.02 : -0.02), 1.3, back * CM + 2);
    scene.add(side);
  }

  // камера: три четверти слева, на высоте глаз, кадр — весь набор с запасом
  const cam = new THREE.PerspectiveCamera(45, w / h, 0.05, 50);
  const centre = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const fitW = size.x / 2 / Math.tan(THREE.MathUtils.degToRad(45 / 2) ) / Math.min(1, w / h);
  const fitH = size.y / 2 / Math.tan(THREE.MathUtils.degToRad(45 / 2));
  const dist = Math.max(fitW, fitH) * 1.18 + size.z / 2;
  cam.position.set(centre.x - size.x * 0.12, 1.55, centre.z + dist);
  cam.lookAt(centre.x, Math.min(1.1, centre.y), centre.z);

  await texturesReady(mctx.cache);
  renderer.render(scene, cam);
  document.body.dataset.ready = String(Date.now());
};
