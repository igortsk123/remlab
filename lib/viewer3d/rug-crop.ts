// ПОЛЯ ФОТО КОВРА (T-20261111-15, владелец TG 1455): ковёр в 3D — плита с фото товара (`kits/bedroom.ts:buildRug`), а фото
// магазина — карточка: ковёр посередине, вокруг ровный белый или кремовый фон. Натянутое целиком, оно давало под ковром
// светлую рамку («белая подложка»). Правило одно для всех ковров: фон карточки — цвет углов (как у серверного
// «фото-ковра», `tools/scout/draft_render.py:_paste_rug`, владелец 31.08), поля — строки и столбцы с краю, где почти всё
// совпадает с фоном; их срезаем, на плиту идёт только сам ковёр. Углы разные или пёстрые (ковёр во всё фото, снимок в
// комнате) — фона нет, фото не трогаем.

import type * as THREE from "three";

/** Прямоугольник содержимого в пикселях: [x0, y0, x1, y1), правая и нижняя граница не включаются. */
export type Box = [number, number, number, number];

/** Пиксель «не фон»: евклидово расстояние до цвета фона больше этого (тот же порог 22, что у `_paste_rug`). */
const FG_DIST = 22;
/** Строка или столбец — поле, пока «не фон» в нём меньше этой доли (логотип, пылинка, шум JPEG не держат поле). */
const EDGE_FRAC = 0.03;
/** Углы — фон, если внутри угла разброс не больше и четыре угла между собой не дальше этого. */
const CORNER_SPREAD = 18;
/** Срезанное меньше этой доли фото — подозрительно (не ковёр, а узор на ковре): фото не трогаем. */
const MIN_SHARE = 0.3;

function cornerMean(px: ArrayLike<number>, w: number, x0: number, y0: number, k: number): { c: number[]; spread: number } {
  const c = [0, 0, 0];
  for (let y = y0; y < y0 + k; y++) for (let x = x0; x < x0 + k; x++) for (let j = 0; j < 3; j++) c[j] += px[(y * w + x) * 4 + j];
  for (let j = 0; j < 3; j++) c[j] /= k * k;
  let spread = 0;
  for (let y = y0; y < y0 + k; y++) for (let x = x0; x < x0 + k; x++) {
    const i = (y * w + x) * 4;
    spread = Math.max(spread, Math.hypot(px[i] - c[0], px[i + 1] - c[1], px[i + 2] - c[2]));
  }
  return { c, spread };
}

/**
 * Прямоугольник ковра на фото карточки (RGBA, `w×h`) или `null` — полей нет или фона нет (фото оставить как есть).
 * Края срезаются ещё на ~0,6 % стороны: размытая полупрозрачная кромка JPEG тоже светлая.
 */
export function contentBox(px: ArrayLike<number>, w: number, h: number): Box | null {
  if (w < 16 || h < 16) return null;
  const k = Math.max(2, Math.round(Math.min(w, h) * 0.02));
  const cs = [cornerMean(px, w, 0, 0, k), cornerMean(px, w, w - k, 0, k), cornerMean(px, w, 0, h - k, k), cornerMean(px, w, w - k, h - k, k)];
  if (cs.some((q) => q.spread > CORNER_SPREAD * 2)) return null;
  for (const a of cs) for (const b of cs) if (Math.hypot(a.c[0] - b.c[0], a.c[1] - b.c[1], a.c[2] - b.c[2]) > CORNER_SPREAD) return null;
  const bg = [0, 1, 2].map((j) => cs.reduce((s, q) => s + q.c[j], 0) / 4);
  const fg = new Uint8Array(w * h);
  const rows = new Float64Array(h);
  const cols = new Float64Array(w);
  const lim = FG_DIST * FG_DIST;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    const dr = px[i] - bg[0], dg = px[i + 1] - bg[1], db = px[i + 2] - bg[2];
    if (dr * dr + dg * dg + db * db > lim) { fg[y * w + x] = 1; rows[y]++; cols[x]++; }
  }
  let y0 = 0, y1 = h, x0 = 0, x1 = w;
  while (y0 < h && rows[y0] < EDGE_FRAC * w) y0++;
  while (y1 > y0 && rows[y1 - 1] < EDGE_FRAC * w) y1--;
  while (x0 < w && cols[x0] < EDGE_FRAC * h) x0++;
  while (x1 > x0 && cols[x1 - 1] < EDGE_FRAC * h) x1--;
  if (x1 <= x0 || y1 <= y0) return null;
  const inset = Math.max(1, Math.round(Math.min(x1 - x0, y1 - y0) * 0.006));
  [x0, y0, x1, y1] = [x0 + inset, y0 + inset, x1 - inset, y1 - inset];
  if ((x1 - x0) * (y1 - y0) < MIN_SHARE * w * h) return null;
  // срезать нечего (поле тоньше 1 % стороны) — фото не трогаем
  if (x0 < w * 0.01 && y0 < h * 0.01 && w - x1 < w * 0.01 && h - y1 < h * 0.01) return null;
  return [x0, y0, x1, y1];
}

/**
 * Срезать поля карточки у загруженной текстуры: картинка заменяется вырезкой (холст), копии текстуры получают её же через
 * `materials.ts:texture`. Нет документа (тесты), чужой адрес без CORS (холст «испорчен») или фона нет — текстура как была.
 */
export function trimTextureToContent(t: THREE.Texture): void {
  const img = t.image as (CanvasImageSource & { width: number; height: number }) | null;
  if (!img || typeof document === "undefined" || !img.width || !img.height) return;
  try {
    const { width: w, height: h } = img;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    if (!g) return;
    g.drawImage(img, 0, 0);
    const box = contentBox(g.getImageData(0, 0, w, h).data, w, h);
    if (!box) return;
    const [x0, y0, x1, y1] = box;
    const out = document.createElement("canvas");
    out.width = x1 - x0;
    out.height = y1 - y0;
    out.getContext("2d")?.drawImage(c, x0, y0, x1 - x0, y1 - y0, 0, 0, x1 - x0, y1 - y0);
    t.image = out;
    t.needsUpdate = true;
  } catch {
    // холст без права чтения (картинка с чужого сайта) — оставляем фото целиком
  }
}
