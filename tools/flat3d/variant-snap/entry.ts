// СТЕНД СНИМКОВ ВАРИАНТА ВИТРИНЫ ЖИВОЙ СЦЕНОЙ (T-20261117-07): страница зовёт `window.variantSnap(case)` — вариант из `demo-data.json`
// встаёт в сцену ТЕМ ЖЕ путём, что в окне демо (`createDemoScene`, `walk: true`), модели — настоящие (с прода через прокси драйвера).
// Кадры — экранной камерой (`setPhotoPose` → `exportFrame`): то, что видит человек в «Ракурсе», с растениями кашпо и ваз; обрезки
// вокруг предметов нужных ролей — из кадра вдвое крупнее. `window.plantSheet` — лист-превью моделей растений на нейтральном фоне.
// Драйвер — `../variant-snap.mjs`.

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

import type { RuntimeEntry } from "@/lib/configurator/mesh-url";
import { createDemoScene, type DemoSceneOptions } from "@/lib/viewer3d/demo-scene";
import type { PhotoPose } from "@/lib/viewer3d/viewer";

type RuntimeMeshes = Record<string, RuntimeEntry>;

interface Case {
  room: DemoSceneOptions["room"];
  items: DemoSceneOptions["items"];
  decor: DemoSceneOptions["decor"];
  rt: RuntimeMeshes;
  /** Отделка по умолчанию из карточки квартиры (как на живой странице); нет — стандарт сцены. */
  floor?: DemoSceneOptions["floor"];
  wall?: DemoSceneOptions["wall"];
  lite: boolean;
  plants: boolean;
  style?: string;
  poses: PhotoPose[];
  /** Роли предметов, вокруг которых вырезаются обрезки («кашпо», «ваза»). */
  focus: string[];
  width: number;
  height: number;
}

interface Result {
  frames: string[];
  /** Обрезки вокруг предметов: поза кадра, роль, картинка. */
  crops: { pose: number; role: string; url: string }[];
  /** мс от создания сцены до `ready` (модели мебели), и до догрузки растений (0 — их нет). */
  readyMs: number;
  plantsMs: number;
  lost: boolean;
  plantLog: unknown[];
}

declare global {
  interface Window {
    variantSnap: (c: Case) => Promise<Result>;
    plantSheet: (urls: string[], w: number, h: number) => Promise<string>;
  }
}

const toDataUrl = (b: Blob): Promise<string> =>
  new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => fail(r.error);
    r.readAsDataURL(b);
  });
const frames = (n: number): Promise<void> => new Promise((ok) => { const f = (i: number): void => { if (i <= 0) ok(); else requestAnimationFrame(() => f(i - 1)); }; f(n); });

window.variantSnap = async (c: Case) => {
  const canvas = document.getElementById("view") as HTMLCanvasElement;
  canvas.width = c.width;
  canvas.height = c.height;
  const t0 = performance.now();
  const scene = createDemoScene(canvas, { room: c.room, items: c.items, decor: c.decor, base: location.href, runtimeMeshes: c.rt, lite: c.lite, floor: c.floor, wall: c.wall,
    walk: true, plants: c.plants, style: c.style });
  let lost = false;
  scene.on("contextlost", () => { lost = true; });
  scene.setSize(c.width, c.height);
  await scene.ready;
  scene.start();
  if (c.height > c.width) scene.setTilt(true);   // портрет телефона — взгляд к мебели, как в окне демо
  const readyMs = Math.round(performance.now() - t0);
  await scene.plantsSettled();
  const plantsMs = c.plants ? Math.round(performance.now() - t0) : 0;
  const roleAt = (i: number): string => String((i < c.items.length ? c.items[i] : (c.decor ?? [])[i - c.items.length])?.role ?? "");
  const out: string[] = [];
  const crops: Result["crops"] = [];
  for (const [n, pose] of c.poses.entries()) {
    scene.setPhotoPose(pose);
    await frames(30);   // сцена догрузила тени и текстуры
    out.push(await toDataUrl(await scene.exportFrame(c.width, c.height, "image/jpeg", 0.9)));
    const pins = scene.pins().filter((p) => p.visible && p.box && c.focus.some((r) => roleAt(p.index).startsWith(r)));
    if (!pins.length) continue;
    const big = await createImageBitmap(await scene.exportFrame(c.width * 2, c.height * 2, "image/png"));
    for (const p of pins) {
      const [l, t, r, b] = p.box!;
      // рамка предмета растёт вверх: растение выше носителя, а рамка (до растения) его не включает — берём запас сверху
      const cx = ((l + r) / 2) * 2, w = Math.max((r - l) * 2 * 2.4, 360), top = t * 2 - w * 0.9, bottom = b * 2 + w * 0.25;
      const sx = Math.max(0, cx - w / 2), sy = Math.max(0, top), sw = Math.min(big.width - sx, w), sh = Math.min(big.height - sy, bottom - sy);
      if (sw < 40 || sh < 40) continue;
      const cv = new OffscreenCanvas(720, Math.round((720 * sh) / sw));
      cv.getContext("2d")!.drawImage(big, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
      crops.push({ pose: n, role: roleAt(p.index).replace(/\s+/g, ""), url: await toDataUrl(await cv.convertToBlob({ type: "image/jpeg", quality: 0.92 })) });
    }
  }
  const plantLog = [...scene.plantReport()];
  scene.dispose();
  return { frames: out, crops, readyMs, plantsMs, lost, plantLog };
};

/** Лист-превью: каждое растение в своей клетке на светлом фоне, в одном масштабе (метр = высота клетки / 0,7), вид слегка сверху. */
window.plantSheet = async (urls: string[], w: number, h: number) => {
  const canvas = document.createElement("canvas");
  canvas.width = w * urls.length;
  canvas.height = h;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(w * urls.length, h, false);
  renderer.setClearColor(0xeceae6);
  renderer.setScissorTest(true);
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  for (const [i, url] of urls.entries()) {
    const gltf = await loader.loadAsync(url);
    const scene = new THREE.Scene();
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1, 2, 1.5);
    scene.add(new THREE.HemisphereLight(0xffffff, 0xb8b2a8, 1.6), sun);
    scene.add(gltf.scene);
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const size = box.getSize(new THREE.Vector3());
    const cam = new THREE.PerspectiveCamera(30, w / h, 0.01, 20);
    const dist = (Math.max(size.y, size.x * 0.9, size.z * 0.9) / 2) / Math.tan((15 * Math.PI) / 180) * 1.25;
    cam.position.set(dist * 0.35, size.y * 0.75 + dist * 0.18, dist);
    cam.lookAt(0, size.y * 0.45, 0);
    renderer.setViewport(i * w, 0, w, h);
    renderer.setScissor(i * w, 0, w, h);
    renderer.render(scene, cam);
  }
  return canvas.toDataURL("image/jpeg", 0.92);
};
