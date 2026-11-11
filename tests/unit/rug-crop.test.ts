import { describe, expect, it } from "vitest";

import { contentBox } from "@/lib/viewer3d/rug-crop";

// ПОЛЯ ФОТО КОВРА (T-20261111-15, TG 1455): ковёр в 3D — плита с фото карточки; белые или кремовые поля вокруг ковра
// срезаются по цвету углов, ковёр во всё фото и снимок без ровного фона не трогаются.

type Rgb = [number, number, number];

/** Фото w×h: фон `bg`, внутри прямоугольник [x0,y0,x1,y1) — «ковёр» с узором (клетка двух цветов). */
function photo(w: number, h: number, bg: Rgb, rug: [number, number, number, number] | null, a: Rgb, b: Rgb): Uint8ClampedArray {
  const px = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const inRug = !rug || (x >= rug[0] && x < rug[2] && y >= rug[1] && y < rug[3]);
    const c = inRug ? ((Math.floor(x / 7) + Math.floor(y / 7)) % 2 ? a : b) : bg;
    px.set([c[0], c[1], c[2], 255], (y * w + x) * 4);
  }
  return px;
}

const WHITE: Rgb = [250, 250, 250];
const BEIGE: Rgb = [190, 160, 130];
const BROWN: Rgb = [150, 110, 80];

describe("contentBox — поля карточки ковра", () => {
  it("белые поля срезаются: остаётся прямоугольник ковра (с запасом на кромку в 1–2 px)", () => {
    const box = contentBox(photo(400, 300, WHITE, [30, 25, 370, 275], BEIGE, BROWN), 400, 300);
    expect(box).not.toBeNull();
    const [x0, y0, x1, y1] = box!;
    for (const [v, want] of [[x0, 30], [y0, 25], [x1, 370], [y1, 275]] as const) expect(Math.abs(v - want)).toBeLessThanOrEqual(3);
  });

  it("кремовый фон карточки — тоже поле (фон по углам, не «белый» порог)", () => {
    const box = contentBox(photo(400, 300, [236, 228, 214], [40, 30, 360, 270], BEIGE, BROWN), 400, 300);
    expect(box).not.toBeNull();
    expect(box![0]).toBeGreaterThanOrEqual(40);
    expect(box![2]).toBeLessThanOrEqual(360);
  });

  it("светлый ковёр на белом (кромка отличается на 25 из 255) — поля всё равно срезаются", () => {
    const box = contentBox(photo(400, 300, WHITE, [20, 20, 380, 280], [225, 222, 215], [215, 210, 200]), 400, 300);
    expect(box).not.toBeNull();
    expect(box![0]).toBeGreaterThanOrEqual(20);
  });

  it("ковёр во всё фото (углы — узор) — фото не трогаем", () => {
    expect(contentBox(photo(400, 300, WHITE, null, BEIGE, BROWN), 400, 300)).toBeNull();
  });

  it("ровный ковёр во всё фото (углы одного цвета, полей нет) — не трогаем", () => {
    expect(contentBox(photo(400, 300, BEIGE, null, BEIGE, BEIGE), 400, 300)).toBeNull();
  });

  it("поле тоньше 1 % стороны — срезать нечего", () => {
    expect(contentBox(photo(400, 300, WHITE, [2, 1, 398, 299], BEIGE, BROWN), 400, 300)).toBeNull();
  });

  it("углы разного цвета (снимок в комнате, не карточка) — не трогаем", () => {
    const px = photo(400, 300, WHITE, [30, 25, 370, 275], BEIGE, BROWN);
    for (let y = 0; y < 60; y++) for (let x = 0; x < 60; x++) px.set([90, 90, 90, 255], (y * 400 + x) * 4);
    expect(contentBox(px, 400, 300)).toBeNull();
  });

  it("логотип в поле (меньше 3 % строки) не держит поле", () => {
    const px = photo(400, 300, WHITE, [30, 25, 370, 275], BEIGE, BROWN);
    for (let y = 5; y < 12; y++) for (let x = 190; x < 200; x++) px.set([20, 20, 20, 255], (y * 400 + x) * 4);
    const box = contentBox(px, 400, 300);
    expect(box).not.toBeNull();
    expect(box![1]).toBeGreaterThanOrEqual(25);
  });
});
