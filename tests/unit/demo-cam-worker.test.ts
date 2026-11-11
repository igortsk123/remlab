import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ЗАПАСНОЙ ПОДБОР РАКУРСОВ В WEB WORKER (T-20261111-23, блок CAMWORK страницы демо): источник потока (`camWorkerSrc`) исполняем здесь
// без браузера — поток отвечает той же парой, что подбор сборки (`tools/flat3d/demo-cams.mjs`: `camPairAll([мебель], W, H, углы)`),
// в том же виде записи `v.cams` (целые x/y/rot, объектив, поза), и не падает на кривом входе (ответ с `err`, а не тишина).
type It = { role: string; x: number; y: number; rot: number; w: number; d: number };
type Cam = { name: string; x: number; y: number; rot: number; fov?: number; pose?: number; pshift?: number; crop?: unknown; poster?: boolean };
type Fx = { room: { w: number; d: number }; variants: { id: string; items: It[] }[] };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const cw = html.slice(html.indexOf("// CAMWORK START"), html.indexOf("// CAMWORK END"));
const src = (new Function(`${cw.slice(cw.indexOf("function camWorkerSrc"), cw.indexOf("const CAMW="))};return camWorkerSrc;`)() as (b: string) => string)(block);
const fx = JSON.parse(readFileSync("tests/fixtures/demo-layouts-neo-0711.json", "utf8")) as Fx;

function worker() {
  const out: { id: number; r: { level?: number; cams?: Cam[]; err?: string } }[] = [];
  const on = new Function("postMessage", `let onmessage; ${src}; return onmessage;`)((m: (typeof out)[number]) => out.push(m)) as
    (e: { data: unknown }) => void;
  return { on, out };
}

describe("подбор ракурсов в потоке (CAMWORK)", () => {
  it("та же пара, что у подбора сборки, в виде записи v.cams", () => {
    const { on, out } = worker();
    const geo = fx.room, v = fx.variants[0]!;
    const its = v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
    on({ data: { D: { room: geo } } });
    on({ data: { id: 7, rid: "living", geo, its } });
    expect(out).toHaveLength(1);
    const m = out[0]!;
    expect(m.id).toBe(7);
    const api = new Function("D", `${block};return {camPairAll, POSE_VER};`)({ room: geo }) as {
      camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[], o: object) => { level: number; cams: Cam[] }; POSE_VER: number };
    const W = geo.w, H = geo.d, p = 3;
    const pr = api.camPairAll([its], W, H, [{ x: p, y: p }, { x: W - p, y: p }, { x: W - p, y: H - p }, { x: p, y: H - p }], {});
    const r = m.r;
    expect(r.err).toBeUndefined();
    expect(r.level).toBe(pr.level);
    expect(r.cams).toHaveLength(2);
    r.cams!.forEach((c, i) => {
      const e = pr.cams[i]!;
      expect(c).toMatchObject({ name: e.name, x: Math.round(e.x), y: Math.round(e.y), rot: Math.round(e.rot || 0), fov: e.fov || 72, pose: api.POSE_VER });
      for (const k of ["x", "y", "rot"] as const) expect(Number.isInteger(c[k])).toBe(true);
    });
  });

  it("кривой вход — ответ с ошибкой, а не тишина (страница не ждёт вечно)", () => {
    const { on, out } = worker();
    on({ data: { D: { room: fx.room } } });
    on({ data: { id: 1, rid: "x", geo: null, its: [] } });
    expect(out).toHaveLength(1);
    expect(out[0]!.r.err).toBeTruthy();
  });
});
