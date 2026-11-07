import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
  new Function("D", `${block};return {camPair,camPairAll,camHard,camFrameState,CAM_KEY,camPairCorner,camStats,camCover,camMask,camAtWindow,camNear,camRole,CAM_B_CLEAR,CAM_MUST,CAM_COVER,CAM_ASPECT};`)({ room: fx.room }) as {
    camPair: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => Pair;
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => Pair & { per: (Omit<Pair, "level" | "how">)[] };
    camHard: (c: Cam, its: It[], strict: number, minDist?: number) => string | false | undefined;
    camFrameState: (c: Cam, it: It) => 0 | 1 | 2;
    CAM_KEY: string[];
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

// ОДНА РАССТАНОВКА И ОДНА ПАРА ТОЧЕК НА ВСЕ СТИЛИ (план demo-31, владелец 02.11: «всегда один и тот же ракурс, но разный стиль»).
// Слепок — сборка рядом 02.11 с `DEMO_ONE_LAYOUT=1` (`tools/scout/demo_one_layout.py`, подбор — `camPairAll`)
type FxOne = Fx & { variants: { id: string; style: string; items: It[]; cams_shared: Cam[] }[] };
const fxOne = load("tests/fixtures/demo-layouts-one-0211.json") as FxOne, apiOne = apiOf(fxOne);

describe("демо: одна расстановка, одна пара точек", () => {
  const { w: W, d: H } = fxOne.room;
  const L = fxOne.variants.map(its);
  it("диван, столик, ТВ-тумба и ковёр — у тех же стен и на одной оси во всех стилях", () => {
    const at = (list: It[], role: string) => list.find((it) => it.role === role);
    for (const [i, list] of L.entries()) {
      const id = fxOne.variants[i]!.id, sofa = at(list, "диван")!, tv = at(list, "тв-тумба")!;
      expect(sofa.y, `${id}: диван у южной стены`).toBeGreaterThan(H / 2);
      expect(tv.y, `${id}: ТВ у северной стены`).toBeLessThan(H / 2);
      for (const r of ["диван", "столик", "тв-тумба", "ковёр"]) {
        const it = at(list, r);
        if (it) expect(it.x, `${id}: ${r} на оси`).toBeCloseTo(L[0]!.find((x) => x.role === "диван")!.x, 1);
      }
    }
  });
  let memo: ReturnType<typeof apiOne.camPairAll> | null = null;
  const pairAll = () => (memo ??= apiOne.camPairAll(L, W, H, corners(W, H)));
  it("одна пара на все варианты: точки (x, y, направление, объектив) одни, у каждого варианта без нарушений camHard", { timeout: 120_000 }, () => {
    const all = pairAll();
    expect(all.how).toMatch(/вариантов 5/);
    expect(all.per).toHaveLength(L.length);
    const pts = (cams: Cam[]) => cams.map((c) => [c.x, c.y, c.rot, c.fov]);
    for (const [i, p] of all.per.entries()) {
      expect(pts(p.cams), fxOne.variants[i]!.id).toEqual(pts(all.cams));
      for (const c of p.cams) expect(apiOne.camHard(c, L[i]!, 0, apiOne.CAM_B_CLEAR), `${fxOne.variants[i]!.id} ${c.name}`).toBeFalsy();
    }
    // слепок записан той же функцией при сборке — подбор и сборка не разошлись
    expect(pts(all.cams)).toEqual(pts(fxOne.variants[0]!.cams_shared));
  });
  // правки ведущего 02.11 по эскизам: в C1 ТВ срезан правым краем у всех стилей, в C2 столик крупно и срезан, стулья — краем
  it("главный вид C1 — диван, столик и ТВ-тумба целиком; крупная мебель ни в одном виде не срезана краем — у всех вариантов", { timeout: 120_000 }, () => {
    const all = pairAll();
    for (const [i, p] of all.per.entries()) {
      const id = fxOne.variants[i]!.id, list = L[i]!, [c1, c2] = p.cams as [Cam, Cam];
      for (const it of list.filter((x) => apiOne.CAM_KEY.includes(apiOne.camRole(x))))
        expect(apiOne.camFrameState(c1, it), `${id} C1: ${it.role} целиком`).toBe(1);
      for (const c of [c1, c2])
        for (const it of list.filter((x) => apiOne.CAM_MUST.includes(apiOne.camRole(x)) || apiOne.camRole(x) === "стул"))
          expect(apiOne.camFrameState(c, it), `${id} ${c.name}: ${it.role} не срезан краем`).not.toBe(2);
    }
  });
});

describe("кадр: крупное целиком или вне кадра", () => {
  const list = its(fxOne.variants[0]!), at = (role: string) => list.find((it) => it.role === role)!;
  // точки — из эскизов первого цикла (дефекты, которые ведущий увидел глазами), и выбранные после правки
  it("C1 первого цикла: ТВ-тумба срезана правым краем; C1 после правки — целиком; вид в стену — вне кадра", () => {
    const tv = at("тв-тумба");
    expect(apiOne.camFrameState({ name: "C1", x: 436, y: 235, rot: -88, fov: 90 }, tv)).toBe(2);
    expect(apiOne.camFrameState({ name: "C1", x: 436, y: 242, rot: -80, fov: 78 }, tv)).toBe(1);
    expect(apiOne.camFrameState({ name: "t", x: 436, y: 242, rot: 100, fov: 78 }, tv)).toBe(0);
  });
  it("C2 первого цикла: столик крупно в углу — срезан; C2 после правки — столик вне кадра, обеденная зона целиком", () => {
    const old = { name: "C2", x: 306, y: 322, rot: -8, fov: 78 }, now = { name: "C2", x: 319, y: 265, rot: 20, fov: 78 };
    expect(apiOne.camFrameState(old, at("столик"))).toBe(2);
    expect(apiOne.camFrameState(now, at("столик"))).toBe(0);
    for (const it of list.filter((x) => x.role === "стол обеденный" || x.role.startsWith("стул"))) expect(apiOne.camFrameState(now, it), it.role).toBe(1);
  });
});

// ЗОНА СПАЛЬНИ → ДВА ВИДА (T-20261105-32, владелец 05.11): правило — данными `CAM_ZONES.bedroom`; вид 1 — на кровать (от входа или из
// ног кровати), вид 2 — вторая зона: шкаф/комод/столик ≥ 60 % рамки и кровать ≥ 75 % (T-32/2, ведущий: «встречный от изголовья» был
// пустой стеной); виды расходятся ≥ `apart` градусов (или ≥ `apartNear.deg` при точках дальше `apartNear.cm`, T-32/3); кровать и хотя
// бы одна тумба покрыты в каждом варианте. T-32/3: вид 1 — изголовье ≥ 75 % и тумба ≥ 60 %, окно телефона — по ним; обложка — `poster`
describe("камеры демо: спальня 1, виды зоны", () => {
  const fxB = load("tests/fixtures/demo-bedroom-1-1105.json");
  type Cv = { inF: number; vis: number }[] & { part?: Record<string, { inF: number; vis: number }> };
  type Box = { x0: number; x1: number; y0: number; y1: number } | null;
  const apiB = new Function("D", `${block};return {camPairAll,camViewFit,camCover,camCoverP,camHeadProj,camFixNear,camAng,CAM_ZONES};`)({ room: fxB.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => Pair & { per: (Omit<Pair, "level" | "how">)[] };
    camViewFit: (vw: unknown, c: Cam, its: It[], cv: Cv) => boolean;
    camCover: (c: Cam, its: It[], W: number, H: number) => Cv;
    camCoverP: (c: Cam, its: It[], W: number, H: number) => Cv;
    camHeadProj: (c: Cam, its: It[], i: number) => Box;
    camFixNear: (c: Cam) => string;
    camAng: (a: number, b: number) => number;
    CAM_ZONES: { bedroom: { views: unknown[]; apart: number; apartNear?: { deg: number; cm: number }; poster?: string }; living: { views?: unknown; poster?: unknown } };
  };
  const { w: W, d: H } = fxB.room, L = fxB.variants.map(its);
  let pr: (Pair & { per: (Omit<Pair, "level" | "how">)[] }) | undefined;
  const pair = () => (pr ??= apiB.camPairAll(L, W, H, corners(W, H)));
  const q = (c: Cam, list: It[], i: number) => { const r = apiB.camCover(c, list, W, H)[i]!; return Math.min(r.inF, r.vis); };
  // какая из двух точек — вид 2 (вторая зона) в этом варианте; -1 — ни одна
  const v2Of = (list: It[]) => {
    const [, v2] = apiB.CAM_ZONES.bedroom.views;
    return pair().cams.findIndex((c) => apiB.camViewFit(v2, c, list, apiB.camCoverP(c, list, W, H)));
  };
  it("гостиная без видов зоны (подбор как был), у спальни — два вида", () => {
    expect(apiB.CAM_ZONES.living.views).toBeUndefined();
    expect(apiB.CAM_ZONES.bedroom.views).toHaveLength(2);
  });
  it("одна пара на 5 вариантов: вид 1 и вид 2 зоны, кровать и ≥ 1 тумба в кадре, обязательное покрыто", () => {
    const p0 = pair();
    expect(p0.how).toContain("виды зоны,");
    const [v1, v2] = apiB.CAM_ZONES.bedroom.views;
    for (const list of L) {
      const cv = p0.cams.map((c) => apiB.camCoverP(c, list, W, H));
      const fit = (vw: unknown, k: number) => apiB.camViewFit(vw, p0.cams[k]!, list, cv[k]!);
      expect((fit(v1, 0) && fit(v2, 1)) || (fit(v1, 1) && fit(v2, 0))).toBe(true);
    }
    for (const [vi, p] of p0.per.entries()) {
      const miss = p.missing.map((m) => m.role);
      expect(p.missing.filter((m) => m.must), fxB.variants[vi]!.id).toEqual([]);
      expect(miss).not.toContain("кровать");
      expect(p.covered.length).toBeGreaterThanOrEqual(4);
    }
  }, 300_000);
  it("вид 2 — вторая зона: шкаф или комод видно ≥ 60 % рамки, кровать ≥ 75 % (до — пустая стена с окном, шкафа ни в одном)", () => {
    const zone2 = ["шкаф", "комод", "туалетный столик", "стол рабочий"];
    for (const [vi, list] of L.entries()) {
      const k = v2Of(list);
      expect(k, fxB.variants[vi]!.id).toBeGreaterThanOrEqual(0);
      const c = pair().cams[k]!, ids = list.map((it, i) => [it, i] as const);
      const bed = ids.find(([it]) => it.role === "кровать")![1];
      expect(q(c, list, bed), `${fxB.variants[vi]!.id}: кровать`).toBeGreaterThanOrEqual(0.75 - 1e-9);
      const z2 = ids.filter(([it]) => zone2.includes(it.role as string)).map(([, i]) => q(c, list, i));
      if (z2.length) expect(Math.max(...z2), `${fxB.variants[vi]!.id}: шкаф/комод`).toBeGreaterThanOrEqual(0.6 - 1e-9);
    }
  }, 300_000);
  it("виды смотрят в разные стороны: направления расходятся ≥ apart или ≥ apartNear.deg при точках дальше apartNear.cm", () => {
    const [a, b] = pair().cams, Z = apiB.CAM_ZONES.bedroom, d = apiB.camAng(a!.rot, b!.rot);
    expect(Z.apart).toBeGreaterThan(0);
    const near = !!Z.apartNear && d >= Z.apartNear.deg && Math.hypot(a!.x - b!.x, a!.y - b!.y) >= Z.apartNear.cm;
    expect(d >= Z.apart || near, `угол ${d}°`).toBe(true);
  }, 300_000);
  it("вид 1 — изголовье ≥ 75 % и тумба ≥ 60 % (T-32/3: «так снимают спальни», не середина кровати)", () => {
    const c = pair().cams[0]!;
    for (const [vi, list] of L.entries()) {
      const cv = apiB.camCoverP(c, list, W, H), bed = list.findIndex((it) => it.role === "кровать");
      const hb = cv.part?.[bed] ?? cv[bed]!;   // у низкой кровати изголовья нет — вся кровать
      expect(Math.min(hb.inF, hb.vis), `${fxB.variants[vi]!.id}: изголовье`).toBeGreaterThanOrEqual(0.75 - 1e-9);
      const tb = list.flatMap((it, i) => (/^тумба прикроватная/.test(it.role) ? [Math.min(cv[i]!.inF, cv[i]!.vis)] : []));
      expect(Math.max(...tb), `${fxB.variants[vi]!.id}: тумба`).toBeGreaterThanOrEqual(0.6 - 1e-9);
    }
  }, 300_000);
  it("узкое окно телефона вида 1 — изголовье целиком и тумба в окне (до — правая половина пустой стены)", () => {
    const c = pair().cams[0]!;
    for (const [vi, p] of pair().per.entries()) {
      const list = L[vi]!, bed = list.findIndex((it) => it.role === "кровать"), hp = apiB.camHeadProj(c, list, bed)!;
      const tbs = new Set(list.flatMap((it, i) => (/^тумба прикроватная/.test(it.role) ? [`item-${i}`] : [])));
      for (const k of ["0.531", "0.673"]) {
        const w = p.cams[0]!.crop![k] as { x: number; w: number; keep: string[] };
        expect(w.keep.some((id) => tbs.has(id)), `${fxB.variants[vi]!.id} ${k}: ${w.keep.join(",")}`).toBe(true);
        expect((Math.max(-1, hp.x0) + 1) / 2, `${fxB.variants[vi]!.id} ${k}: изголовье слева`).toBeGreaterThanOrEqual(w.x - 1e-9);
        expect((Math.min(1, hp.x1) + 1) / 2, `${fxB.variants[vi]!.id} ${k}: изголовье справа`).toBeLessThanOrEqual(w.x + w.w + 1e-9);
      }
    }
  }, 300_000);
  it("обложка на главной — правило зоны `poster`: помечена ровно одна точка; у гостиной правила нет", () => {
    expect(apiB.CAM_ZONES.bedroom.poster).toBe("more");
    expect(apiB.CAM_ZONES.living.poster).toBeUndefined();
    expect(pair().cams.filter((c) => (c as Cam & { poster?: boolean }).poster)).toHaveLength(1);
  }, 300_000);
  it("узкое окно телефона вида 2 — вокруг шкафа/комода (до — по кровати, шкаф срезан окном у лофта и джапанди)", () => {
    for (const [vi, p] of pair().per.entries()) {
      const list = L[vi]!, ids = new Set(list.flatMap((it, i) => (["шкаф", "комод"].includes(it.role) ? [`item-${i}`] : [])));
      for (const k of ["0.531", "0.673"]) {
        const keep = (p.cams[1]!.crop![k] as { keep: string[] }).keep;
        expect(keep.some((id) => ids.has(id)), `${fxB.variants[vi]!.id} ${k}: ${keep.join(",")}`).toBe(true);
      }
    }
  }, 300_000);
  it("вплотную к камере в кадре нет подоконника, шторы и радиатора: старая C1 у северного окна отсеяна, новые точки чистые", () => {
    // C1 T-32/1: в 3 см от северной стены, подоконник в 112 см — белая плита у левого края во всех 5 черновиках
    expect(apiB.camFixNear({ x: 554, y: 290, rot: -46, fov: 84 } as Cam)).toBe("подоконник");
    for (const c of pair().cams) expect(apiB.camFixNear(c)).toBe("");
  }, 300_000);
  it("изголовье не у стены с окном", () => {
    const wins = new Set((fxB.room.openings as { kind: string; wall: string }[]).filter((o) => o.kind === "window").map((o) => o.wall));
    for (const v of fxB.variants) {
      const bed = v.items.find((i) => i.role === "кровать")!;
      // rot — куда кровать смотрит лицом (0 → север, 90 → восток, `planner/candidates.py:_rot_towards`); изголовье — у стены за спиной
      const wall = ["south", "west", "north", "east"][((Math.round(bed.rot / 90) % 4) + 4) % 4]!;
      expect(wins.has(wall), `${v.id}: изголовье у стены ${wall}`).toBe(false);
    }
  });
});

// T-32/6 (ведущий: «комод срезан левым краем, в левом верхнем углу крючок карниза»): одна расстановка на 5 стилей (T-32/4) —
// у всех комод у северной стены рядом с окном; запас кромки `edge` и правило карниза `rodHook` зоны спальни
describe("камеры демо: спальня 1, одна расстановка — комод целиком, без «крючка» карниза", () => {
  const fx1 = load("tests/fixtures/demo-bedroom-1-one-1105.json");
  const api1 = new Function("D", `${block};return {camPairAll,camRodHook,camFrameState,camRole,CAM_ZONES};`)({ room: fx1.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => Pair;
    camRodHook: (c: Cam) => string;
    camFrameState: (c: Cam, it: It) => number;
    camRole: (it: It) => string;
    CAM_ZONES: { bedroom: { must: string[]; edge?: number }; living: { edge?: number; rodHook?: boolean; grid?: unknown; slide?: unknown } };
  };
  const { w: W, d: H } = fx1.room, L = fx1.variants.map(its);
  let pr: Pair | undefined;
  const pair = () => (pr ??= api1.camPairAll(L, W, H, corners(W, H)));
  it("у гостиной полей T-32/6 нет — её подбор не меняется", () => {
    const z = api1.CAM_ZONES.living;
    expect([z.edge, z.rodHook, z.grid, z.slide]).toEqual([undefined, undefined, undefined, undefined]);
  });
  it("старая C1 (T-32/5) — «крючок»: конец карниза в кадре, окна под ним нет; в новой паре карниза без окна нет", () => {
    expect(api1.camRodHook({ x: 537, y: 233, rot: -60, fov: 78 } as Cam)).toBe("карниз");
    for (const c of pair().cams) expect(api1.camRodHook(c)).toBe("");
  }, 300_000);
  it("обязательное в обоих видах — целиком с запасом кромки или вне кадра (старая C1: комод у края, −0,98)", () => {
    const old = { x: 537, y: 233, rot: -60, fov: 78 } as Cam, kom = L[0]!.find((it) => api1.camRole(it) === "комод")!;
    expect(api1.camFrameState(old, kom)).toBe(2);
    expect(pair().how).toContain("срезано краем 0");
    for (const [vi, list] of L.entries())
      for (const [k, c] of pair().cams.entries())
        for (const it of list) {
          if (!api1.CAM_ZONES.bedroom.must.includes(api1.camRole(it))) continue;
          expect(api1.camFrameState(c, it), `${fx1.variants[vi]!.id} вид ${k + 1}: ${it.role}`).not.toBe(2);
        }
    const c1 = pair().cams[0]!;
    for (const list of L) expect(api1.camFrameState(c1, list.find((it) => api1.camRole(it) === "комод")!)).toBe(1);
  }, 300_000);
});

// ОБЛОЖКА ПОКАЗЫВАЕТ ГЛАВНУЮ ВЕЩЬ (T-20261107-01, ведущий 07.11: «на всех 5 обложках спальни 2 в центре шкаф и окно, а кровать срезана
// у левого края»). Спальня 4,50×2,93: каждая точка, откуда кровать видна на 2/3, стоит к ней ближе 1,2 м, и `camBlock` считал кровать
// «предметом перед объективом» — годных точек с кроватью не было ни одной, пара уходила в угол шкафа и окна (ступень 0)
describe("камеры демо: спальня 2 — обложка с кроватью", () => {
  const fx2 = load("tests/fixtures/demo-bedroom-2-one-1107.json");
  const api2 = new Function("D", `${block};return {camPairAll,camCover,camBlock,camRole,camMainRoles,CAM_MAIN_MIN};`)({ room: fx2.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => Pair & { posterMiss?: boolean };
    camCover: (c: Cam, its: It[], W: number, H: number) => { inF: number; vis: number }[];
    camBlock: (c: Cam, its: It[]) => { cov: number; who: string };
    camRole: (it: It) => string;
    camMainRoles: () => string[];
    CAM_MAIN_MIN: number;
  };
  const { w: W, d: H } = fx2.room, L = fx2.variants.map(its);
  let pr: (Pair & { posterMiss?: boolean }) | undefined;
  const pair = () => (pr ??= api2.camPairAll(L, W, H, corners(W, H)));
  const bedQ = (c: Cam, list: It[]) => {
    const i = list.findIndex((it) => api2.camRole(it) === "кровать"), r = api2.camCover(c, list, W, H)[i]!;
    return Math.min(r.inF, r.vis);
  };
  it("главная вещь спальни — кровать; кровать себе не помеха, а шкаф вплотную — помеха", () => {
    expect(api2.camMainRoles()).toEqual(["кровать"]);
    const at = { x: 43, y: 83, rot: 114, fov: 90 } as Cam, loft = L[fx2.variants.findIndex((v) => v.id === "bedroom-2-loft")]!;
    expect(api2.camBlock(at, loft).cov).toBe(0);
    expect(api2.camBlock({ x: 405, y: 40, rot: -150, fov: 90 } as Cam, loft).who).toBe("шкаф");
  });
  it("прежняя C1 кровати не видела; обложка новой пары (C1 — пометки `poster` нет) показывает её ≥ 2/3 во всех 5 стилях", () => {
    const old = { x: 123, y: 83, rot: -162, fov: 84 } as Cam;
    for (const list of L) expect(bedQ(old, list)).toBeLessThan(0.05);
    const p = pair(), cover = p.cams.find((c) => (c as Cam & { poster?: boolean }).poster) ?? p.cams[0]!;
    for (const [vi, list] of L.entries()) expect(bedQ(cover, list), fx2.variants[vi]!.id).toBeGreaterThanOrEqual(api2.CAM_MAIN_MIN);
    expect(p.posterMiss).toBe(false);
    expect(p.how).toContain("главное в C1");
    expect(p.level).toBe(3);
  }, 300_000);
});

// СТИЛЬ НА ЗАПАСНОМ НЕ УХУДШАЕТ ПОКРЫТИЕ ОСТАЛЬНЫХ (T-20261107-11/3): слепок — гостиная сборки 07.11, неоклассика на запасном нейтральном
// ковре (`fill[].rug_universal`). Общая пара по худшему варианту отнимала торшер у сканди, современного и минимализма; `demo-cams.mjs`
// берёт пару с условием `opt.keep` — покрытое без стилей на запасном остаётся покрытым
describe("одна пара: стиль на запасном не ухудшает покрытие остальных", () => {
  type FxN = Omit<Fx, "variants"> & { variants: { id: string; style: string; items: It[]; fill?: { rug_universal?: boolean }[] }[] };
  const fxN = load("tests/fixtures/demo-layouts-neo-0711.json") as unknown as FxN;
  const apiN = new Function("D", `${block};return {camPairAll};`)({ room: fxN.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[], opt?: { keep: number[] }) =>
      (Pair & { per: (Omit<Pair, "level" | "how"> & { bits: number })[] }) | null;
  };
  const { w: W, d: H } = fxN.room;
  it("условие keep недостижимо — null, а не углы", () => {
    const list = its(fxN.variants[0]!);
    expect(apiN.camPairAll([list], W, H, corners(W, H), { keep: [1 << 30] })).toBeNull();
  }, 120_000);
  it("demo-cams: одна пара на 6 стилей, покрытие 5 стилей со своим набором не хуже пары без неоклассики", () => {
    const own = fxN.variants.filter((v) => !(v.fill ?? []).some((x) => x.rug_universal));
    expect(own).toHaveLength(5);
    const base = apiN.camPairAll(own.map(its), W, H, corners(W, H))!;
    const dir = mkdtempSync(join(process.env.REMLAB_TMP || tmpdir(), "cams-neo-")), f = join(dir, "demo-data.json");
    writeFileSync(f, readFileSync("tests/fixtures/demo-layouts-neo-0711.json"));
    const log = execFileSync("node", ["tools/flat3d/demo-cams.mjs", f], { encoding: "utf8" });
    expect(log).toMatch(/взята пара, где их покрытие не хуже/);
    const out = JSON.parse(readFileSync(f, "utf8")) as { variants: { id: string; cams: Cam[]; cam_cover: { missing: { id: string }[] } }[] };
    const pts = (cams: Cam[]) => cams.map((c) => [c.x, c.y, c.rot, c.fov]);
    for (const v of out.variants) expect(pts(v.cams), v.id).toEqual(pts(out.variants[0]!.cams));
    for (const [i, v] of own.entries()) {
      const was = new Set(base.per[i]!.covered), now = out.variants.find((x) => x.id === v.id)!;
      const lost = now.cam_cover.missing.map((m) => m.id).filter((id) => was.has(id));
      expect(lost, `${v.style}: потеряно покрытие`).toEqual([]);
    }
  }, 300_000);
});

// ВИДЫ СПАЛЬНИ С ДВУХ КОНЦОВ КОМНАТЫ (T-20261107-30, владелец 07.11 TG 345: «эти виды в спальнях должны быть с 2 разных сторон спальни,
// чтоб разглядывать её»). Слепки — живой /demo 07.11 (одна расстановка на 5 стилей). До правила спальня 1: C1 (530,250,−59°) и
// C2 (554,109,−90°) — обе у восточного окна, 31°, кнопки «Со стороны окна, слева / справа». Правило — `ends` зоны (`camEndsOk`)
describe("камеры демо: спальни — виды с двух концов комнаты", () => {
  type Z = { deg: number; mid?: number };
  type PairE = Pair & { per: (Omit<Pair, "level" | "how">)[]; endsMiss?: boolean; zoneMiss?: boolean; mm?: number };
  const mk = (fx: Fx) => new Function("D", `${block};return {camPairAll,camPairAll0,camEndsOk,camViewFit,camCoverP,camAng,CAM_ZONES};`)({ room: fx.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => PairE;
    camPairAll0: (L: It[][], W: number, H: number, cs: { x: number; y: number }[], opt?: { noEnds?: boolean }) => PairE;
    camEndsOk: (A: Cam, B: Cam, W: number, H: number, E: Z | null) => boolean;
    camViewFit: (vw: unknown, c: Cam, its: It[], cv: unknown) => boolean;
    camCoverP: (c: Cam, its: It[], W: number, H: number) => unknown;
    camAng: (a: number, b: number) => number;
    CAM_ZONES: Record<string, { views?: unknown[]; ends?: Z }>;
  };
  const ROOMS = [["спальня 1", "tests/fixtures/demo-bedroom-1-one-1107.json"], ["спальня 2", "tests/fixtures/demo-bedroom-2-one-1107.json"]] as const;
  it("правило — только у спальни: у гостиной, прихожей и кухни `ends` нет (их пары не меняются)", () => {
    const api = mk(load(ROOMS[0][1]));
    expect(api.CAM_ZONES.bedroom!.ends!.deg).toBeGreaterThanOrEqual(120);
    for (const k of ["living", "hall", "kitchen"]) expect(api.CAM_ZONES[k]!.ends, k).toBeUndefined();
  });
  it("мера концов: по разные стороны середины длинной оси, угол ≥ deg, отступ от середины ≥ mid", () => {
    const api = mk(load(ROOMS[0][1])), E = { deg: 120, mid: 50 };
    const at = (x: number, y: number, rot: number) => ({ name: "C", x, y, rot, fov: 72 }) as Cam;
    // прежняя пара спальни 1: обе точки у восточного торца, 31°
    expect(api.camEndsOk(at(530, 250, -59), at(554, 109, -90), 597, 293, E)).toBe(false);
    expect(api.camEndsOk(at(80, 250, 60), at(530, 60, -120), 597, 293, E)).toBe(true);
    expect(api.camEndsOk(at(280, 250, 60), at(530, 60, -120), 597, 293, E)).toBe(false);   // у середины ближе mid
    expect(api.camEndsOk(at(80, 250, 60), at(530, 60, 100), 597, 293, E)).toBe(false);     // 40° — не встречные
    expect(api.camEndsOk(at(80, 250, 60), at(530, 60, 100), 597, 293, null)).toBe(true);   // зона без правила
  });
  // пара с двух концов не хуже прежней: те же виды зоны (есть/нет), обязательного не покрыто не больше; виды зоны — в каждом варианте
  const check = (api: ReturnType<typeof mk>, fx: Fx, L: It[][], p: PairE, old: PairE, tag: string) => {
    const { w: W, d: H } = fx.room, E = api.CAM_ZONES.bedroom!.ends!, [a, b] = p.cams as [Cam, Cam];
    expect(p.endsMiss, `${tag}: ${p.how}`).toBeFalsy();
    expect(api.camEndsOk(a, b, W, H, E), `${tag}: C1 (${a.x},${a.y},${a.rot}) C2 (${b.x},${b.y},${b.rot})`).toBe(true);
    expect(api.camAng(a.rot, b.rot)).toBeGreaterThanOrEqual(E.deg);
    expect(p.zoneMiss ?? false, tag).toBe(old.zoneMiss ?? false);
    expect(p.mm ?? 0, tag).toBeLessThanOrEqual(old.mm ?? 0);
    if (!p.zoneMiss) {
      const [v1, v2] = api.CAM_ZONES.bedroom!.views!;
      for (const list of L) {
        const fit = (vw: unknown, k: number) => api.camViewFit(vw, p.cams[k]!, list, api.camCoverP(p.cams[k]!, list, W, H));
        expect((fit(v1, 0) && fit(v2, 1)) || (fit(v1, 1) && fit(v2, 0)), tag).toBe(true);
      }
    }
    for (const [vi, pv] of p.per.entries())
      expect(pv.missing.filter((m) => m.must).length, `${tag} ${vi}`).toBeLessThanOrEqual(old.per[vi]!.missing.filter((m) => m.must).length);
  };
  it("спальня 2: одна пара на 5 стилей — с двух концов, покрытие не хуже прежней пары", () => {
    const fx = load(ROOMS[1][1]), api = mk(fx), { w: W, d: H } = fx.room, L = fx.variants.map(its);
    check(api, fx, L, api.camPairAll(L, W, H, corners(W, H)), api.camPairAll0(L, W, H, corners(W, H), { noEnds: true }), "спальня 2");
  }, 900_000);
  // спальня 1: шкаф и комод у западного торца — вид 2 возможен только с востока; вид 1 с запада не годен во всех 5 стилях одной точкой
  // (минимализм — низкая кровать, сбоку видна на 21 %; у сканди и джапанди точка «из ног» в 17 см от комода) — у каждого стиля своя пара
  // (`demo-cams.mjs`, ведущий: вариант А). Здесь — самые трудные стили: сканди (2 годные западные точки) и минимализм (4)
  for (const style of ["сканди", "минимализм"]) {
    it(`спальня 1, ${style}: своя пара — с двух концов, вид 1 и вид 2 зоны, покрытие не хуже прежней`, () => {
      const fx = load(ROOMS[0][1]), api = mk(fx), { w: W, d: H } = fx.room, L = [its(fx.variants.find((v) => v.style === style)!)];
      check(api, fx, L, api.camPairAll(L, W, H, corners(W, H)), api.camPairAll0(L, W, H, corners(W, H), { noEnds: true }), `спальня 1 ${style}`);
    }, 900_000);
  }
  it("пары с двух концов без потери покрытия нет — прежняя пара с пометкой endsMiss (demo-cams пишет WARN), не молча", () => {
    const fx = load(ROOMS[0][1]), api = mk(fx), { w: W, d: H } = fx.room, L = [its(fx.variants[0]!)];
    api.CAM_ZONES.bedroom!.ends = { deg: 179, mid: 290 };   // недостижимо: точки у самых торцов и строго встречные
    const p = api.camPairAll(L, W, H, corners(W, H)), old = api.camPairAll0(L, W, H, corners(W, H), { noEnds: true });
    expect(p.endsMiss).toBe(true);
    expect(p.how).toMatch(/разные концы комнаты .* прежняя пара/);
    expect(p.cams.map((c) => [c.x, c.y, c.rot, c.fov])).toEqual(old.cams.map((c) => [c.x, c.y, c.rot, c.fov]));
  }, 900_000);
  // ПОДПИСИ КНОПОК (`vwCamNames`): у видов с двух концов имя даёт проём своей половины. Без этого у 4 стилей спальни 1 из 5 точка C1 у двери
  // (224 см — за порогом CAM_NAME_NEAR 220) звалась по северному окну, обе кнопки — «окно», и страница ставила «Ракурс 1 / 2».
  // Пары — из сборки с правилом 07.11 (`demo-cams.mjs` на живых данных)
  const namesSrc = html.slice(html.indexOf("const CAM_NAME_NEAR="), html.indexOf("// ПОДПИСИ КНОПОК РАКУРСА ЦЕЛИКОМ"));
  const namesOf = (room: Fx["room"]) => {
    const f = new Function("D", `${block};const LANG='ru';let cams=null,CS=[];const loadCams=()=>CS;function curRoom(){return D.room;}
${namesSrc};return (cs)=>{CS=cs;return vwCamNames();};`)({ room: room }) as (cs: Cam[]) => string[];
    return (...xy: [number, number][]) => f(xy.map(([x, y], k) => ({ name: `C${k + 1}`, x, y, rot: 0, fov: 72 })));
  };
  it("подписи: спальня 1 — у всех 5 стилей «Со стороны двери / окна»; прежняя пара — прежние «окна, слева / справа»", () => {
    const nm = namesOf(load(ROOMS[0][1]).room);
    const pairs: [number, number][][] = [[[78, 165], [554, 190]], [[77, 224], [554, 190]], [[77, 230], [554, 117]], [[71, 218], [548, 170]], [[71, 222], [554, 129]]];
    for (const [a, b] of pairs) expect(nm(a!, b!), `C1 (${a})`).toEqual(["Со стороны двери", "Со стороны окна"]);
    expect(nm([530, 250], [554, 109])).toEqual(["Со стороны окна, слева", "Со стороны окна, справа"]);
  });
  it("подписи: спальня 2 и гостиная — как до правила", () => {
    expect(namesOf(load(ROOMS[1][1]).room)([43, 83], [387, 103])).toEqual(["Со стороны окна", "Со стороны двери"]);
    expect(namesOf(load("tests/fixtures/demo-layouts-neo-0711.json").room)([409, 205], [346, 322])).toEqual(["Со стороны двери, справа", "Со стороны двери, слева"]);
  });
});
