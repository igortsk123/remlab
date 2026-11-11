import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// «ПОВЕРНУТЬ» В 3D: шаг 90° (владелец TG 1586, T-20261111-05/7). Функцию берём прямо из страницы демо (блок ROTSTEP).
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// ROTSTEP START"), html.indexOf("// ROTSTEP END"));
const api = new Function(`${block};return {rotNext,ROT_STEP};`)() as {
  rotNext: (rot: number) => number;
  ROT_STEP: number;
};

describe("поворот предмета в 3D: шаг 90°", () => {
  it("шаг — 90°, кнопка так и подписана", () => {
    expect(api.ROT_STEP).toBe(90);
    expect(html).toContain("'Повернуть на 90°'");
    expect(html).not.toContain("'Повернуть на 45°'");
  });
  it("по часовой (на плане минус): 0 → 270 → 180 → 90 → 0, полный круг за 4 нажатия", () => {
    const seen: number[] = [];
    let r = 0;
    for (let k = 0; k < 4; k++) seen.push((r = api.rotNext(r)));
    expect(seen).toEqual([270, 180, 90, 0]);
  });
  it("косой угол из данных первым нажатием встаёт ровно по стенам (ближайший кратный 90° по часовой)", () => {
    expect(api.rotNext(45)).toBe(0);
    expect(api.rotNext(315)).toBe(270);
    expect(api.rotNext(100)).toBe(90);
    expect(api.rotNext(-45)).toBe(270);
    for (const r of [0, 12, 45, 89.9, 135, 200, 359]) expect(api.rotNext(r) % 90).toBe(0);
  });
  it("почти кратный (погрешность округления) считается ровным и поворачивается на полный шаг", () => {
    expect(api.rotNext(90.2)).toBe(0);
    expect(api.rotNext(359.8)).toBe(270);
  });
});
