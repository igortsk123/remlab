// СТЕНД СНИМКОВ ПРИХОЖЕЙ (T-20261106-73, план hall-demo-01 этап 2): страница стенда зовёт `window.hallSnap(case)` — набор
// `compose_hall` встаёт в живую сцену ТЕМ ЖЕ путём, что вариант витрины (`createDemoScene` → мост `fromDemoVariant` →
// `planObjects` → `FlatViewer`), и снимается режимом «Фото» (`capture`). Вариант /demo не выдумывается: вход — банк стенда.
// Точки съёмки — подбор по правилу видов (`./views.ts`, правило `tools/scout/rules/hall-views.json`, проекция — блок CAMFIT демо,
// его текст передаёт драйвер). Драйвер — `tools/flat3d/hall-snap.mjs`.

import { createDemoScene, type DemoSceneOptions } from "@/lib/viewer3d/demo-scene";
import { camfitFrom, pickHallViews, type HallItem, type HallViewsRule, type ViewPick } from "./views";

interface SnapCase {
  room: DemoSceneOptions["room"];
  items: DemoSceneOptions["items"];
  /** Подбор видов: текст блока CAMFIT, правило и пропорция кадра, по которой проверяется «целиком» (кадр компьютера). */
  pick: { camfit: string; rule: HallViewsRule; aspect: number };
  width: number;
  height: number;
  lite: boolean;
}

interface SnapResult {
  frames: string[];
  clay: string[];
  views: ViewPick[];
  /** Браузер отобрал контекст WebGL за время съёмки (нехватка памяти) — кадры после этого чёрные. */
  lost: boolean;
  /** Кадр тёмный целиком (ярчайшая точка уменьшенной копии темнее 8 из 255) — чёрный кадр, а не снимок прихожей. */
  dark: boolean[];
}

declare global {
  interface Window {
    hallSnap: (c: SnapCase) => Promise<SnapResult>;
  }
}

/** Ярчайшая точка кадра, уменьшенного до 64 px по ширине: у живого кадра прихожей стены и пол светлые, у чёрного — 0. */
const peak = async (b: Blob): Promise<number> => {
  const bmp = await createImageBitmap(b);
  const w = 64;
  const h = Math.max(1, Math.round((bmp.height / bmp.width) * w));
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  if (!ctx) return 255;
  ctx.drawImage(bmp, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  let top = 0;
  for (let i = 0; i < px.length; i += 4) top = Math.max(top, px[i]!, px[i + 1]!, px[i + 2]!);
  return top;
};
const DARK_PEAK = 8;

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
  let lost = false;
  scene.on("contextlost", () => { lost = true; });
  scene.setSize(c.width, c.height);
  await scene.ready;
  const room = { w: Number(c.room.w), d: Number(c.room.d), openings: c.room.openings ?? [] };
  const views = pickHallViews(camfitFrom(c.pick.camfit, room), c.pick.rule, room, c.items as unknown as HallItem[], c.pick.aspect);
  const shot = await scene.capture(views.map((v) => v.pose), c.width, c.height);
  const frames = await Promise.all(shot.frames.map(toDataUrl));
  const dark = (await Promise.all(shot.frames.map(peak))).map((p) => p < DARK_PEAK);
  scene.dispose();
  return { frames, clay: shot.clay, views, lost, dark };
};
