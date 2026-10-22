import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ДВЕ ТОЧКИ СЪЁМКИ ПОДБИРАЮТСЯ ПАРОЙ (план demo-12), ПОКРЫТИЕ КАЖДОГО ПРЕДМЕТА — ПЕРВЫМ (план demo-22). Функции — прямо из блока
// CAMFIT страницы демо (его же исполняет `tools/flat3d/demo-cams.mjs`); расстановки — слепки 17.10 и опубликованные 22.10.
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null };
type Crop = { x: number; y: number; w: number; h: number; keep?: string[] };
type Cam = { name: string; x: number; y: number; rot: number; fov: number; pshift?: number; crop?: Record<string, Crop> };
type Stats = { ceil: number; floor: number; empty: number; nearWall: number; fore: number; midY: number; win: boolean; bins: Set<number> };
type Pair = { level: number; cams: Cam[]; how: string; covered: string[]; missing: { id: string; role: string; must: boolean; reason: string }[] };
type Fx = { room: { w: number; d: number; openings: unknown[] }; variants: { id: string; style: string; items: It[] }[] };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const load = (f: string) => JSON.parse(readFileSync(f, "utf8")) as Fx;
const apiOf = (fx: Fx) =>
  new Function("D", `${block};return {camPair,camPairCorner,camStats,camCover,camMask,camAtWindow,camNear,camRole,CAM_B_CLEAR,CAM_MUST,CAM_COVER,CAM_ASPECT};`)({ room: fx.room }) as {
    camPair: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => Pair;
    camPairCorner: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => { level: number; cams: Cam[] };
    camStats: (c: Cam, its: It[], W: number, H: number, o?: { w?: number; h?: number; sn?: number }) => Stats;
    camCover: (c: Cam, its: It[], W: number, H: number) => { inF: number; vis: number }[];
    camAtWindow: (x: number, y: number, W: number, H: number) => boolean;
    camNear: (c: Cam, it: It) => number;
    camRole: (it: It) => string;
    CAM_B_CLEAR: number; CAM_MUST: string[]; CAM_COVER: number; CAM_ASPECT: number;
  };
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const corners = (W: number, H: number) => [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
// лучшее из двух видов: доля в кадре и доля не заслонённого (покрыт — обе ≥ 0.9)
const best = (api: ReturnType<typeof apiOf>, cams: Cam[], list: It[], W: number, H: number, i: number) =>
  Math.max(...cams.map((c) => { const r = api.camCover(c, list, W, H)[i]!; return Math.min(r.inF, r.vis); }));

const fx17 = load("tests/fixtures/demo-layouts-1710.json"), fx22 = load("tests/fixtures/demo-layouts-2210.json");
const api17 = apiOf(fx17), api22 = apiOf(fx22);

describe("камеры демо: пара", () => {
  it("маска: в пустой комнате пол и потолок симметричны при сдвиге 0, у стены в упор — стена у края", () => {
    const { w: W, d: H } = fx17.room, c = { name: "t", x: W / 2, y: H / 2, rot: 0, fov: 72 };
    const s0 = api17.camStats(c, [], W, H, { w: 64, h: 88, sn: 0 });
    expect(Math.abs(s0.floor - s0.ceil)).toBeLessThan(0.02);
    expect(api17.camStats({ name: "t", x: 10, y: 10, rot: 20, fov: 72 }, [], W, H).nearWall).toBeGreaterThan(0.02);
  });
  // правила кадра и места — на обоих слепках; покрытие — где оно достижимо двумя видами (лофт 22.10 — нет: см. ниже)
  for (const [tag, fx, api] of [["17.10", fx17, api17], ["22.10", fx22, api22]] as const)
    for (const v of fx.variants)
      it(`${tag} ${v.style}: обязательная мебель ≥ 90 % в кадре и не заслонена хотя бы в одном виде; кадры по правилам`, () => {
        const { w: W, d: H } = fx.room, list = its(v), pr = api.camPair(list, W, H, corners(W, H));
        const st = pr.cams.map((c) => api.camStats(c, list, W, H));
        for (const [i, s] of st.entries()) {
          expect(s.nearWall, `${v.style} C${i + 1} стена у края`).toBeLessThanOrEqual(0.02);
          expect(s.fore, `${v.style} C${i + 1} крупный план`).toBeLessThanOrEqual(0.12);
          expect(s.ceil, `${v.style} C${i + 1} потолок`).toBeLessThanOrEqual(0.3);
        }
        for (const c of pr.cams) {
          expect(api.camAtWindow(c.x, c.y, W, H), `${v.style} ${c.name} у окна`).toBe(false);
          for (const it of list) if ((it.h ?? 10) > 2 && it.role !== "ковёр") expect(api.camNear(c, it)).toBeGreaterThanOrEqual(api.CAM_B_CLEAR);
        }
        const must = list.map((it, i) => [it, i] as const).filter(([it]) => api.CAM_MUST.includes(api.camRole(it)));
        if (pr.how.startsWith("недобор")) {
          // недобор — только с отчётом: каждое непокрытое обязательное названо, причина указана
          const miss = must.filter(([, i]) => best(api, pr.cams, list, W, H, i) < api.CAM_COVER).map(([, i]) => `item-${i}`);
          expect(miss.length, pr.how).toBeGreaterThan(0);
          expect(pr.missing.filter((m) => m.must).map((m) => m.id).sort()).toEqual(miss.sort());
          return;
        }
        for (const [it, i] of must) expect(best(api, pr.cams, list, W, H, i), `${v.style}: ${it.role}`).toBeGreaterThanOrEqual(api.CAM_COVER);
        expect(pr.missing.filter((m) => m.must)).toEqual([]);
      });
  it("недобор двумя видами — только у лофта 22.10 (ТВ, диван и обеденную зону вместе не видит ни одна точка), и в нём не больше одного предмета", () => {
    const { w: W, d: H } = fx22.room;
    const short = fx22.variants.map((v) => [v.style, api22.camPair(its(v), W, H, corners(W, H))] as const).filter(([, p]) => p.how.startsWith("недобор"));
    expect(short.map(([s]) => s)).toEqual(["лофт"]);
    expect(short[0]![1].missing.filter((m) => m.must).length).toBeLessThanOrEqual(1);
  });
  it("регрессия владельца 22.10: стеллаж минимализма в углу у окна виден целиком (до — 0 % в кадре)", () => {
    const { w: W, d: H } = fx22.room, v = fx22.variants.find((x) => x.style === "минимализм")!, list = its(v);
    const i = list.findIndex((it) => it.role === "стеллаж");
    expect(best(api22, (v as unknown as { cams_before: Cam[] }).cams_before, list, W, H, i)).toBeLessThan(0.5);
    expect(best(api22, api22.camPair(list, W, H, corners(W, H)).cams, list, W, H, i)).toBeGreaterThanOrEqual(0.9);
  });
  it("регрессия: стеллаж, повёрнутый по диагонали в углу, виден целиком", () => {
    const { w: W, d: H } = fx22.room, v = fx22.variants.find((x) => x.style === "минимализм")!;
    const list = its(v).map((it) => (it.role === "стеллаж" ? { ...it, x: 40, y: 290, rot: 135 } : it));
    const i = list.findIndex((it) => it.role === "стеллаж");
    expect(best(api22, api22.camPair(list, W, H, corners(W, H)).cams, list, W, H, i)).toBeGreaterThanOrEqual(0.9);
  });
  it("регрессия: высокий шкаф в углу у окна виден целиком (раньше высокое у края выкидывалось из кадра целиком)", () => {
    const { w: W, d: H } = fx22.room, v = fx22.variants.find((x) => x.style === "сканди")!;
    const list = [...its(v), { role: "шкаф", x: 43, y: 30, w: 80, d: 60, h: 210, rot: 0 }];   // юго-западный угол, окно — на западной стене
    const pr = api22.camPair(list, W, H, corners(W, H));
    expect(best(api22, pr.cams, list, W, H, list.length - 1), pr.how).toBeGreaterThanOrEqual(0.9);
  });
  it("регрессия: второй вид лофта — не пустая стена: пустых столбцов ≤ 0.4 и в нём целиком обязательное, которого нет в первом (до — ничего)", () => {
    const { w: W, d: H } = fx22.room, v = fx22.variants.find((x) => x.style === "лофт")!, list = its(v);
    const pr = api22.camPair(list, W, H, corners(W, H)), [c1, c2] = pr.cams as [Cam, Cam];
    expect(api22.camStats(c2, list, W, H).empty).toBeLessThanOrEqual(0.4);
    const q = (c: Cam, i: number) => { const r = api22.camCover(c, list, W, H)[i]!; return Math.min(r.inF, r.vis); };
    const only2 = list.filter((it, i) => api22.CAM_MUST.includes(api22.camRole(it)) && q(c2, i) >= 0.9 && q(c1, i) < 0.9);
    expect(only2.length).toBeGreaterThanOrEqual(1);
    const before = (v as unknown as { cams_before: Cam[] }).cams_before[1]!;
    expect(list.filter((it, i) => api22.CAM_MUST.includes(api22.camRole(it)) && q(before, i) >= 0.9).length).toBe(0);
  });
  it("окно превью: на каждую пропорцию, внутри кадра, нужной пропорции; главное вида целиком везде, где оно помещается в окно", () => {
    const { w: W, d: H } = fx22.room;
    for (const v of fx22.variants) {
      const list = its(v), pr = api22.camPair(list, W, H, corners(W, H));
      for (const k of ["1.500", "1.416", "0.673", "0.531"]) {
        for (const c of pr.cams) {
          const r = c.crop![k]!;
          expect(r.x).toBeGreaterThanOrEqual(0); expect(r.y).toBeGreaterThanOrEqual(0);
          expect(r.x + r.w).toBeLessThanOrEqual(1.0005); expect(r.y + r.h).toBeLessThanOrEqual(1.0005);
          expect(Math.abs((r.w * api22.CAM_ASPECT) / r.h - +k), `${v.style} ${c.name} ${k}`).toBeLessThan(0.01);
        }
        for (const c of pr.cams) {
          // главное вида (ведущий 22.10): диван, если он в кадре ≥ 50 %; иначе ТВ-тумба; иначе обеденный стол
          const st = api22.camStats(c, list, W, H) as Stats & { vis: Record<string, number>; ext: Record<string, { x0: number; x1: number; y0: number; y1: number }> };
          const cv = api22.camCover(c, list, W, H);
          const m = ["диван", "тв-тумба", "стол обеденный"].map((role) => list.findIndex((it, i) => it.role === role && !!st.ext[String(i)] && (st.vis[String(i)] ?? 0) >= 4
            && (role !== "диван" || cv[i]!.inF >= 0.5))).find((i) => i >= 0);
          if (m === undefined) continue;
          const e = st.ext[String(m)]!, r = c.crop![k]!, horiz = r.h === 1;
          const L = horiz ? r.w : r.h, span = horiz ? e.x1 - e.x0 : e.y1 - e.y0;
          if (span <= L * (1 - 2 * 0.06)) expect(r.keep, `${v.style} ${c.name} ${k}: ${list[m]!.role}`).toContain(`item-${m}`);
        }
      }
    }
  });
  it("окно превью на узком телефоне — вокруг главного вида, даже если он не помещается: у минимализма C1 0.531 диван в окне (ведущий 22.10)", () => {
    const { w: W, d: H } = fx22.room, v = fx22.variants.find((x) => x.style === "минимализм")!, list = its(v);
    const pr = api22.camPair(list, W, H, corners(W, H)), c1 = pr.cams[0]!;
    const i = list.findIndex((it) => it.role === "диван");
    const e = (api22.camStats(c1, list, W, H) as Stats & { ext: Record<string, { x0: number; x1: number }> }).ext[String(i)]!;
    for (const k of ["0.673", "0.531"]) {
      const r = c1.crop![k]!, ov = Math.max(0, Math.min(r.x + r.w, e.x1) - Math.max(r.x, e.x0)) / Math.min(r.w, e.x1 - e.x0);
      expect(ov, `${k}: доля ширины дивана в окне`).toBeGreaterThanOrEqual(0.95);
      const mc = (e.x0 + e.x1) / 2;
      expect(mc, `${k}: середина дивана в средней трети`).toBeGreaterThanOrEqual(r.x + r.w / 3 - 0.01);
      expect(mc).toBeLessThanOrEqual(r.x + (2 * r.w) / 3 + 0.01);
    }
  });
  it("портрет телефона: подобранный сдвиг ставит пол и потолок примерно поровну, пол не больше 0.35", () => {
    const { w: W, d: H } = fx17.room;
    for (const v of fx17.variants) {
      const list = its(v);
      for (const c of api17.camPair(list, W, H, corners(W, H)).cams) {
        expect(c.pshift, `${v.style} ${c.name}`).toBeGreaterThanOrEqual(-0.15);
        expect(c.pshift!).toBeLessThanOrEqual(0.05);
        const s = api17.camStats(c, list, W, H, { w: 64, h: 88, sn: -2 * c.pshift! });
        expect(Math.abs(s.floor - s.ceil), `${v.style} ${c.name} пол/потолок`).toBeLessThanOrEqual(0.06);
        // мебель низкая, глаз на 135 см: поднять её медиану в среднюю треть можно лишь ценой пола > 0.35 (замер 17.10)
        expect(s.floor, `${v.style} ${c.name} пол`).toBeLessThanOrEqual(0.35);
        expect(s.midY, `${v.style} ${c.name} мебель по высоте`).toBeGreaterThan(1 / 3);
        expect(s.midY).toBeLessThan(0.8);
      }
    }
  });
  it("подбор парой — по умолчанию (владелец «включай» 17.10), и без флага окружения", () => {
    const { w: W, d: H } = fx17.room, list = its(fx17.variants[0]!);
    expect(api17.camPair(list, W, H, corners(W, H)).how).toMatch(/^(пара|недобор)/);
  });
});
