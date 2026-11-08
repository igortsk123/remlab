import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ФОТО СВОЕЙ КАМЕРЫ — ТОЧКА И ПОЗА (T-20261108-73/7, ведущий): `shotCamOk` страницы. С той же точки, но другой позой съёмки
// (`POSE_VER`: глаз, наклон, сдвиг) кадр другой, и вырезка телефона нынешней позы легла бы не на то место — такое фото
// «не своей камеры» (в пересъёмку). Функция исполняется из текста страницы: с `POSE_VER` (страница) и без него (прогрев
// `tools/ops/demo-warm.mjs` берёт блоки CAMANG и SHOTCAM) — тогда поза точки варианта (`v.cams[].pose`).
type C = { name: string; x: number; y: number; rot: number; fov: number; pose?: number };
type S = { camera?: string; cams?: C[] | null };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const cut = (n: string) => html.slice(html.indexOf(`// ${n} START`), html.indexOf(`// ${n} END`));
const poseVer = Number(/const POSE_VER=(\d+)/.exec(html)![1]);
const fn = (withPose: boolean) =>
  new Function(`${cut("CAMANG")}\n${withPose ? `const POSE_VER=${poseVer};` : ""}\n${cut("SHOTCAM")}\n;return shotCamOk;`)() as (s: S, l: C[]) => boolean;
const at = (pose?: number, x = 436): C[] => [{ name: "C1", x, y: 232, rot: -99, fov: 72, pose }, { name: "C2", x: 283, y: 303, rot: 31, fov: 72, pose }];

describe("фото своей камеры: точка и поза", () => {
  it("поза страницы — 3 (глаз 150, вниз 8°)", () => expect(poseVer).toBe(3));
  it("страница: та же точка, кадр позы 2 — не своей камеры; позы 3 — своей; другая точка — не своей", () => {
    const ok = fn(true);
    expect(ok({ camera: "C1", cams: at(2) }, at(3))).toBe(false);
    expect(ok({ camera: "C1", cams: at(2) }, at(undefined))).toBe(false);   // точки варианта без записи позы — поза страницы
    expect(ok({ camera: "C1", cams: at(3) }, at(3))).toBe(true);
    expect(ok({ camera: "C1", cams: at(3, 300) }, at(3))).toBe(false);
    expect(ok({ camera: "C2", cams: at(undefined) }, at(3))).toBe(false);   // кадр без версии позы — v1
  });
  it("без POSE_VER (прогрев): поза — из точки варианта", () => {
    const ok = fn(false);
    expect(ok({ camera: "C1", cams: at(2) }, at(3))).toBe(false);
    expect(ok({ camera: "C1", cams: at(3) }, at(3))).toBe(true);
    expect(ok({ camera: "C1", cams: at(undefined) }, at(undefined))).toBe(true);
  });
  it("кадр без записи точки — по-старому, годен", () => {
    expect(fn(true)({ camera: "C1", cams: null }, at(3))).toBe(true);
  });
});
