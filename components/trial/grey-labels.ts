// Подписи комнат серого тура (план agent-trial-01, T-C/2): проекция точки комнаты на холст. Общее правило видимости:
// подпись скрыта, если она за камерой, её прямоугольник выходит за край холста или пересекает панель кнопок.
// Маленькая на экране комната — только «?» (у флажков) без названия.

import * as THREE from "three";
import type { GreyScene } from "@/lib/trial/grey-scene";

type Rect = { l: number; t: number; r: number; b: number };
const overlaps = (a: Rect, b: Rect) => a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;

/** Прямоугольник элемента в координатах холста `box` (элемент — потомок `box`). */
export function rectIn(box: HTMLElement, el: HTMLElement): Rect {
  const a = box.getBoundingClientRect(), b = el.getBoundingClientRect();
  return { l: b.left - a.left, t: b.top - a.top, r: b.right - a.left, b: b.bottom - a.top };
}

export function placeLabels(
  gs: GreyScene, cam: THREE.Camera, box: HTMLElement, layer: HTMLElement, tools: HTMLElement | null, selected: string | null,
) {
  const w = box.clientWidth, h = box.clientHeight;
  const bar = tools ? rectIn(box, tools) : null;
  const v = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3();
  for (const r of gs.rooms) {
    const el = layer.querySelector<HTMLElement>(`[data-room="${CSS.escape(r.id)}"]`);
    if (!el) continue;
    v.copy(r.label).project(cam);
    a.set(r.center.x - r.size.x / 2, 0, r.center.z).project(cam);
    b.set(r.center.x + r.size.x / 2, 0, r.center.z).project(cam);
    const span = Math.hypot((a.x - b.x) * w, (a.y - b.y) * h) / 2;
    el.dataset.compact = span < 64 && r.id !== selected ? "1" : "0";
    el.style.display = "";
    const x = ((v.x + 1) / 2) * w, y = ((1 - v.y) / 2) * h;
    const hw = el.offsetWidth / 2, hh = el.offsetHeight / 2;
    const rect = { l: x - hw, t: y - hh, r: x + hw, b: y + hh };
    const fits = v.z < 1 && rect.l >= 0 && rect.t >= 0 && rect.r <= w && rect.b <= h && !(bar && overlaps(rect, bar));
    el.style.display = fits ? "" : "none";
    el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
  }
}
