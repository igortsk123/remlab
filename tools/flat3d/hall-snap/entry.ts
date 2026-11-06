// СТЕНД СНИМКОВ ПРИХОЖЕЙ (T-20261106-73, план hall-demo-01 этап 2): страница стенда зовёт `window.hallSnap(case)` — набор
// `compose_hall` встаёт в живую сцену ТЕМ ЖЕ путём, что вариант витрины (`createDemoScene` → мост `fromDemoVariant` →
// `planObjects` → `FlatViewer`), и снимается режимом «Фото» (`capture`). Вариант /demo не выдумывается: вход — банк стенда.
// Драйвер — `tools/flat3d/hall-snap.mjs`.

import { createDemoScene, type DemoSceneOptions } from "@/lib/viewer3d/demo-scene";
import type { PhotoPose } from "@/lib/viewer3d/viewer";

interface SnapCase {
  room: DemoSceneOptions["room"];
  items: DemoSceneOptions["items"];
  poses: PhotoPose[];
  width: number;
  height: number;
  lite: boolean;
}

declare global {
  interface Window {
    hallSnap: (c: SnapCase) => Promise<{ frames: string[]; clay: string[] }>;
  }
}

const toDataUrl = (b: Blob): Promise<string> =>
  new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => fail(r.error);
    r.readAsDataURL(b);
  });

window.hallSnap = async (c: SnapCase) => {
  const canvas = document.getElementById("view") as HTMLCanvasElement;
  canvas.width = c.width;
  canvas.height = c.height;
  const scene = createDemoScene(canvas, { room: c.room, items: c.items, base: location.href, lite: c.lite, walk: false });
  scene.setSize(c.width, c.height);
  await scene.ready;
  const shot = await scene.capture(c.poses, c.width, c.height);
  const frames = await Promise.all(shot.frames.map(toDataUrl));
  scene.dispose();
  return { frames, clay: shot.clay };
};
