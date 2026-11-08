import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ДВЕ ТОЧКИ СЪЁМКИ ПОДБИРАЮТСЯ ПАРОЙ (план demo-12), ПОКРЫТИЕ КАЖДОГО ПРЕДМЕТА — ПЕРВЫМ (план demo-22). Функции — прямо из блока
// CAMFIT страницы демо (его же исполняет `tools/flat3d/demo-cams.mjs`); расстановки — слепки 17.10 и опубликованные 22.10.
// С правила видов v2 (T-20261108-73/4, `camPairV2`; его тесты — `demo-cams-v2.test.ts`) гостиная, спальни и прихожая идут новым
// подбором; прежний (`camPairAll0`) остался запасным — зоны без `intent` (кухня), смысл видов не выполнить, `opt.v1`. Здесь — его
// фиксации (`apiOf` зовёт его с `v1`) и общие меры кадра; правила «с двух концов», видов зоны спальни и подписей по проёму сняты
// вместе с кодом (тесты удалены).
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
  new Function("D", `${block};return {camPair:(its,W,H,cs)=>camPairAll([its],W,H,cs,{v1:true}),camPairAll:(L,W,H,cs,o)=>camPairAll(L,W,H,cs,Object.assign({},o,{v1:true})),camHard,camFrameState,CAM_KEY,camPairCorner,camStats,camCover,camMask,camAtWindow,camNear,camRole,CAM_B_CLEAR,CAM_MUST,CAM_COVER,CAM_ASPECT,camBigCut,CAM_ZONES,camLiveBigCut,camIsMain,camZ};`)({ room: fx.room }) as {
    camLiveBigCut: (c: Cam, its: It[], W: number, H: number, skip: Set<number>, big: (it: It) => boolean) => { i: number; fr: number }[];
    camIsMain: (it: It) => boolean; camZ: () => { core?: Record<string, number> };
    camBigCut: (c: Cam, its: It[], cv: { inF: number; vis: number }[]) => { n: number; main: boolean; fr: number };
    CAM_ZONES: Record<string, unknown>;
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
  // T-73/6: маска — поза съёмки (глаз 150, взгляд вниз 8°): при сдвиге 0 пола в кадре больше, чем потолка
  it("маска: в пустой комнате при сдвиге 0 пола больше потолка (взгляд вниз), у стены в упор — стена у края", () => {
    const { w: W, d: H } = fx17.room, c = { name: "t", x: W / 2, y: H / 2, rot: 0, fov: 72 };
    const s0 = api17.camStats(c, [], W, H, { w: 64, h: 88, sn: 0 });
    expect(s0.floor - s0.ceil).toBeGreaterThan(0.05);
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
  // (T-73/6: с позой съёмки 150↓8 недобора нет и у лофта — проверка «не больше» осталась)
  it("недобор двумя видами — не больше чем у лофта 22.10 (ТВ, диван и обеденную зону вместе не видит ни одна точка), и в нём не больше одного предмета", () => {
    const { w: W, d: H } = fx22.room;
    const short = fx22.variants.map((v) => [v.style, api22.camPair(its(v), W, H, corners(W, H))] as const).filter(([, p]) => p.how.startsWith("недобор"));
    for (const [st] of short) expect(st).toBe("лофт");
    for (const [, p] of short) expect(p.missing.filter((m) => m.must).length).toBeLessThanOrEqual(1);
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
    // (до — пустая стена; T-73/6: с позой 150↓8 в прежний вид попадает один предмет — новый показывает больше)
    const before = (v as unknown as { cams_before: Cam[] }).cams_before[1]!, nMust = (c: Cam) => list.filter((it, i) => api22.CAM_MUST.includes(api22.camRole(it)) && q(c, i) >= 0.9).length;
    expect(nMust(before)).toBeLessThanOrEqual(1);
    expect(nMust(c2)).toBeGreaterThan(nMust(before));
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
// крупное для среза краем — как в `camBigCut`: главное или вес ядра зоны ≥ 1
const bigOne = (it: It) => apiOne.camIsMain(it) || ((apiOne.camZ().core ?? {})[apiOne.camRole(it)] ?? 0) >= 1;

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
  });
  // правки ведущего 02.11 по эскизам: в C1 ТВ срезан правым краем у всех стилей, в C2 столик крупно и срезан, стулья — краем
  it("главный вид C1 — диван, столик и ТВ-тумба целиком; крупная мебель ни в одном виде не срезана краем — у всех вариантов", { timeout: 120_000 }, () => {
    const all = pairAll();
    for (const [i, p] of all.per.entries()) {
      const id = fxOne.variants[i]!.id, list = L[i]!, [c1, c2] = p.cams as [Cam, Cam];
      for (const it of list.filter((x) => apiOne.CAM_KEY.includes(apiOne.camRole(x))))
        expect(apiOne.camFrameState(c1, it), `${id} C1: ${it.role} целиком`).toBe(1);
      // срез — мерой T-68 (`camBigCut`: кусок срезанного крупного ≥ 1 % кадра и срезано > 15 %). С двух концов (T-20261108-73)
      // край кадра задевает полоску ТВ-тумбы или дивана меньше 1 % кадра и стул — у прежней пары у восточной двери их не было
      // Срез краем живого «3D» (T-20261108-73, `camLiveBigCut` в `camBigCut`) — отдельно: в кадре фото срезов нет, в 3D у вида C2
      // «От окна» есть (обеденный стол в углу у ТВ виден от окна только взглядом вдоль стены с ТВ; `demo-cams.mjs` пишет WARN)
      for (const c of [c1, c2]) {
        const bc = apiOne.camBigCut(c, list, apiOne.camCover(c, list, W, H)), live = apiOne.camLiveBigCut(c, list, W, H, new Set(), bigOne).length;
        expect(bc.n - live, `${id} ${c.name}: крупное не срезано краем кадра фото (кусок ${bc.fr.toFixed(3)} кадра)`).toBe(0);
      }
      expect(apiOne.camLiveBigCut(c1, list, W, H, new Set(), bigOne), `${id} C1: в 3D ничего не срезано`).toEqual([]);
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

// T-32/6 (ведущий: «комод срезан левым краем, в левом верхнем углу крючок карниза»): одна расстановка на 5 стилей (T-32/4) —
// у всех комод у северной стены рядом с окном; запас кромки `edge` и правило карниза `rodHook` зоны спальни
describe("камеры демо: спальня 1, одна расстановка — комод целиком, без «крючка» карниза", () => {
  const fx1 = load("tests/fixtures/demo-bedroom-1-one-1105.json");
  const api1 = new Function("D", `${block};return {camPairAll,camRodHook,camFrameState,camRole,camV2Raw,CAM_ZONES};`)({ room: fx1.room }) as {
    camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[]) => Pair;
    camV2Raw: (c: Cam, its: It[], W: number, H: number, ids: number[]) => { s: number; fr: number }[][];
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
    // (T-73/6: с позой 150↓8 у старой точки −60° f78 конец карниза ушёл за верх кадра — контроль на соседней позе, где он в кадре)
    expect(api1.camRodHook({ x: 537, y: 233, rot: -55, fov: 90 } as Cam)).toBe("карниз");
    for (const c of pair().cams) expect(api1.camRodHook(c)).toBe("");
  }, 300_000);
  it("обязательное в обоих видах — целиком с запасом кромки или вне кадра (старая C1: комод у края, −0,98)", () => {
    const old = { x: 537, y: 233, rot: -60, fov: 78 } as Cam, kom = L[0]!.find((it) => api1.camRole(it) === "комод")!;
    expect(api1.camFrameState(old, kom)).toBe(2);
    // правило v2 (T-20261108-73/4): крупное и обязательное не срезано ни в одном окне показа (`camPairV2`, «срезано крупного 0/0»);
    // прежнее «вид 1 — комод целиком» снято вместе с видами зоны спальни: вид 1 теперь от двери
    // (мера — та же, что у подбора: окна показа, `camV2Raw`)
    // T-73/6: кадр фото — поза съёмки (глаз 150, вниз 8°), низ режет; у вида 1 у двери низ кадра срезает край тумбы у кровати
    // (замер 08.11: кусок 0,04–0,06 кадра) — она одна может быть срезана; пара от этого на ступени 9, где у обязательного допустим
    // малый срез (кусок < `mustCut` 0,02 окна, ступень 7: край комода в живом 3D); окно «фото на телефоне» (индекс 3) — мягкое
    for (const [vi, list] of L.entries())
      for (const [k, c] of pair().cams.entries()) {
        const ids = list.flatMap((it, i) => (api1.CAM_ZONES.bedroom.must.includes(api1.camRole(it)) && api1.camRole(it) !== "тумба прикроватная" ? [i] : []));
        api1.camV2Raw(c, list, W, H, ids).forEach((r, j) =>
          expect(r.filter((x, w) => w !== 3 && x.s === 2 && x.fr >= 0.02).length, `${fx1.variants[vi]!.id} вид ${k + 1}: ${list[ids[j]!]!.role}`).toBe(0));
      }
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
  // СРЕЗ КРАЕМ ЖИВОГО 3D (T-20261108-73, ведущий 08.11 по снимку set9 375×667 «От окна»: у левого края тёмный кусок тумбы с ТВ ~1/6 ширины).
  // Мера фото-кадра его не видела (тумба в маске 0–2 %): живое 3D смотрит со своего места — глаз 152 см, в 50 см от стен, с наклоном вниз,
  // холст телефона во весь экран. Мера — `camLiveBigCut` (окна и пороги — как у прихожей `cutNear`), входит в `camBigCut`
  const apiL = new Function("D", `${block};return {camLiveBigCut,camBigCut,camCover,camRole,camIsMain,camZ};`)({ room: fxN.room }) as {
    camLiveBigCut: (c: Cam, its: It[], W: number, H: number, skip: Set<number>, big: (it: It) => boolean) => { i: number; fr: number }[];
    camBigCut: (c: Cam, its: It[], cv: { inF: number; vis: number }[]) => { n: number; main: boolean; fr: number };
    camCover: (c: Cam, its: It[], W: number, H: number) => { inF: number; vis: number }[];
    camRole: (it: It) => string; camIsMain: (it: It) => boolean; camZ: () => { core?: Record<string, number> };
  };
  const tvLiveCut = (c: Cam, list: It[]) => {
    const big = (it: It) => apiL.camIsMain(it) || ((apiL.camZ().core ?? {})[apiL.camRole(it)] ?? 0) >= 1;
    const p = apiL.camLiveBigCut(c, list, W, H, new Set(), big).find((q) => apiL.camRole(list[q.i]!) === "тв-тумба");
    return p ? p.fr : 0;
  };
  // T-73/3, точная мера: тумба с ТВ у левого края этого вида — настоящая (снимок 375 «От окна»), кусок 15 % кадра; вид считается срезом
  // (`camBigCut`), и подбор берёт его только когда чище нет — со сторожем WARN (тест выше)
  it("живое 3D: вид «От окна» (120,90 → 96°) режет ТВ-тумбу левым краем — кусок ≥ 10 % кадра, срез в ключе пары (`camBigCut`)", () => {
    const list = its(fxN.variants.find((v) => v.style === "минимализм")!), old = { name: "C2", x: 120, y: 90, rot: 96, fov: 78 };
    expect(tvLiveCut(old, list)).toBeGreaterThan(0.1);
    expect(apiL.camBigCut(old, list, apiL.camCover(old, list, W, H)).n).toBeGreaterThan(0);
    // тот же предмет, когда край его не задевает (вид от двери на ТВ) — не срез
    expect(tvLiveCut({ name: "C1", x: 436, y: 232, rot: -87, fov: 90 }, list)).toBe(0);
  });
});

// ТОЧНАЯ МЕРА СРЕЗА КРАЕМ ЖИВОГО 3D (T-20261108-73/3): прежняя брала прямоугольник вокруг проекций точек коробки, обрезанных ближней
// плоскостью, — у предмета вплотную сбоку от глаза точки уходят далеко за край, и прямоугольник ложился на треть кадра. Спальня 1
// «Лофт», вид «От двери» сборки 08.11 (83,230 54° 72°): шкаф у западной стены рядом с глазом — «срезан на 41 % кадра», на снимке
// живого 3D шкафа нет. Теперь — силуэт граней, обрезанных пирамидой взгляда (`camLiveArea`)
describe("живое 3D: точная мера среза краем", () => {
  const fx1 = load("tests/fixtures/demo-bedroom-1-one-1107.json");
  type Cut = { frame: number; own: number; near: number };
  type Win = { asp: number; top: number; bot: number; vis?: number };
  const api1 = new Function("D", `${block};return {camCutLive,camLiveBigCut,camRole,CAM_LIVE_WIN};`)({ room: fx1.room }) as {
    camCutLive: (c: Cam, it: It, its: It[], fr: Win, W: number, H: number) => Cut;
    camLiveBigCut: (c: Cam, its: It[], W: number, H: number, skip: Set<number>, big: (it: It) => boolean) => { i: number; fr: number }[];
    camRole: (it: It) => string; CAM_LIVE_WIN: Win[];
  };
  const { w: W, d: H } = fx1.room, list = its(fx1.variants.find((v) => v.id === "bedroom-1-loft")!);
  const cam = { name: "C1", x: 83, y: 230, rot: 54, fov: 72 }, wi = list.findIndex((it) => api1.camRole(it) === "шкаф");
  it("шкаф сбоку от глаза (в 1 м, вне кадра) — срез 0 в окне телефона и компьютера; в списке срезанного его нет", () => {
    expect(wi).toBeGreaterThanOrEqual(0);
    for (const fr of api1.CAM_LIVE_WIN) {
      const q = api1.camCutLive(cam, list[wi]!, list, fr, W, H);
      expect(q.near, "шкаф ближе порога cutNear — мера его проверяет").toBeLessThanOrEqual(150);
      expect(q.frame, `окно ${fr.asp}: доля кадра`).toBe(0);
    }
    expect(api1.camLiveBigCut(cam, list, W, H, new Set(), () => true).map((q) => api1.camRole(list[q.i]!))).not.toContain("шкаф");
  });
  it("тот же шкаф, когда глаз смотрит вдоль него, — в кадре срезан краем (мера не слепая)", () => {
    const along = { name: "t", x: 83, y: 230, rot: -20, fov: 72 };
    const f = Math.max(...api1.CAM_LIVE_WIN.map((fr) => api1.camCutLive(along, list[wi]!, list, fr, W, H).frame));
    expect(f).toBeGreaterThan(0.02);
  });
});
