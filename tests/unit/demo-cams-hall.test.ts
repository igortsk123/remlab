import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// РАКУРСЫ ПРИХОЖЕЙ НА ВИТРИНЕ (T-20261107-05/4, ведущий: «на обоих ракурсах в кадре ≥ 4 предмета из 5–6, никакого „в упор в дверцу“»).
// Правило — данными `CAM_ZONES.hall` (смысл стенда `rules/hall-views.json`): вид 1 — к входу, зеркало целиком и хранение у него; вид 2 —
// главное хранение целиком и предмет коридора рядом; узкая комната — пороги «близко» × `near`, главная вещь вплотную — помеха
// (`mainBlock`); подвес настенного (`elev`) — в проекции и маске. У каждого стиля прихожей своя расстановка — пара на стиль
// (`demo-cams.mjs`, метка геометрии `cams_own`). Расстановки — сборка рядом 07.11 (5 стилей, коридор 153 × 620).
// С 08.11 (T-20261108-73/4) пару прихожей ставит правило видов v2 (`camPairV2`): вид 1 — от входной двери, вид 2 — дальняя часть;
// виды зоны (`views`, `camViewFit`) остались у прежнего подбора — запасного; меры кадра («в упор», подвес зеркала, срез 3D) — те же.
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null; elev?: number };
type Cam = { name: string; x: number; y: number; rot: number; fov: number; poster?: boolean };
type Pair = { cams: Cam[]; how: string };
type Fx = { room: { w: number; d: number; kind: string; openings: unknown[]; cams_own?: boolean }; variants: { id: string; items: It[] }[] };
type Cv = { inF: number; vis: number }[];
// окно показа живого «3D»: пропорция холста, видимая полоса, низ над шторкой (`live-eye.ts`, `viewer.ts`)
type Frame = { asp: number; top: number; bot: number; vis: number };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const fx = JSON.parse(readFileSync("tests/fixtures/demo-hall-1107.json", "utf8")) as Fx;
const api = new Function("D", `${block};return {camPair,camCover,camBlock,camNear,camRole,camIsMain,camNearK,camElev,camCutLive,camEntry,camV2Raw,camV2Set,camZ,CAM_ZONES,CAM_NEAR};`)({ room: fx.room }) as {
  camEntry: () => { o: { wall: string; offset_cm: number; width_cm: number; is_entrance?: boolean }; warn: string } | null;
  camV2Raw: (c: Cam, its: It[], W: number, H: number, ids: number[]) => { s: number; fr: number; q: number }[][];
  camV2Set: (its: It[], I: unknown) => { mains: number[]; need: number[] };
  camZ: () => { intent?: unknown };
  camCutLive: (c: Cam, it: It, its: It[], fr: Frame, W: number, H: number) => { frame: number; own: number; near: number };
  camPair: (its: It[], W: number, H: number, cs: { x: number; y: number }[]) => Pair;
  camCover: (c: Cam, its: It[], W: number, H: number) => Cv;
  camBlock: (c: Cam, its: It[]) => { cov: number; who: string };
  camNear: (c: Cam, it: It) => number;
  camRole: (it: It) => string;
  camIsMain: (it: It) => boolean;
  camNearK: () => number;
  camElev: (it: It) => number;
  CAM_ZONES: Record<string, { views?: unknown[]; near?: number; mainBlock?: boolean }>;
  CAM_NEAR: number;
};
const { w: W, d: H } = fx.room;
const corners = [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
type Cut = { cm: number; frame: number; hi: number; live: Frame[] };
const pairs = new Map<string, Pair>();
const pairOf = (v: { id: string; items: It[] }) => {
  if (!pairs.has(v.id)) pairs.set(v.id, api.camPair(its(v), W, H, corners));
  return pairs.get(v.id)!;
};

describe("камеры демо: прихожая, виды зоны", () => {
  it("поля узкой комнаты — только у прихожей: гостиная и спальни с прежними порогами", () => {
    expect(fx.room.kind).toBe("hall");
    expect(fx.room.cams_own).toBe(true);
    expect(api.CAM_ZONES.hall!.near).toBeLessThan(1);
    expect(api.CAM_ZONES.hall!.mainBlock).toBe(true);
    for (const z of ["living", "bedroom", "kitchen"]) {
      const Z = api.CAM_ZONES[z]! as { near?: number; mainBlock?: boolean; moreTol?: number; views?: { cutNear?: Cut }[] };
      expect(Z.near).toBeUndefined();
      expect(Z.mainBlock).toBeUndefined();
      expect(Z.moreTol).toBeUndefined();
      expect((Z.views || []).flat().some((x) => x && x.cutNear)).toBe(false);
    }
  });

  // T-20261107-05/7 (лист 07.11: на виде 2 в углу кадра крупным планом кусок банкетки, консоли или вешалки в метре от глаза): вид на
  // хранение не берёт точку, где ближняя мебель срезана краем ЖИВОГО «3D» — на телефоне и на компьютере (`cutNear.live`: глаз «3D»
  // отходит от стен и наклонён к мебели, лист 1627 — мера по камере фото консоль модерна не видела). Узкий коридор: глаз посередине,
  // строгой точки нет у 4 стилей из 5 — допуск ступенями (`CAM_CUT_LADDER`, пометка «обрезана до N % кадра»); достигнуто — не выше
  // 10 % кадра, без отката «без cutNear». Пороги — фиксация, не цель.
  // T-20261107-05/8 (вариант Б): у прихожей наклон «3D» не круче −25° (`livePitchMin`) — в кадре больше комнаты, но ближняя обувница
  // модерна (свои 84 % в кадре) берёт ступень 20 %: фиксация по стилю, остальные — 10 %.
  const CUT_LIM: Record<string, number> = { 'hall-modern': 0.2 };
  for (const v of fx.variants) {
    it(`${v.id}: вид на хранение — ближняя мебель в живом «3D» не обрезана краем сверх допуска`, () => {
      const pr = pairOf(v), list = its(v), c2 = pr.cams[1]!;
      const g = (api.CAM_ZONES.hall!.views![1] as { cutNear: Cut }).cutNear;
      expect(g.cm).toBeGreaterThanOrEqual(100);
      expect(g.live.some((f) => f.asp < 1 && f.vis < 1)).toBe(true);   // телефон: холст выше ширины, низ под шторкой
      expect(g.live.some((f) => f.asp > 1)).toBe(true);                // компьютер
      expect(pr.how).not.toMatch(/без cutNear/);
      const m = pr.how.match(/обрезана до (\d+) % кадра/), lim = Math.max(g.frame, m ? +m[1]! / 100 : 0);
      expect(lim).toBeLessThanOrEqual(CUT_LIM[v.id] ?? 0.1);
      const cut = g.live.flatMap((fr) => list.filter((it) => (it.h ?? 0) > 2).map((it) => ({ it, q: api.camCutLive(c2, it, list, fr, W, H) }))
        .filter(({ q }) => q.near <= g.cm && q.own < g.hi && q.frame >= lim).map(({ it, q }) => `${it.role} ${fr.asp} ${q.frame.toFixed(3)}`));
      expect(cut).toEqual([]);
    });
  }

  it("зеркало висит на своей высоте: консоль под ним его не заслоняет", () => {
    const v = fx.variants.find((x) => x.id === "hall-modern")!, list = its(v);
    const m = list.findIndex((it) => api.camRole(it) === "зеркало");
    expect(api.camElev(list[m]!)).toBeGreaterThan(100);
    // из дальнего конца коридора на вход: зеркало на восточной стене над консолью видно
    const cv = api.camCover({ name: "C1", x: 60, y: 530, rot: -16, fov: 72 }, list, W, H);
    expect(Math.min(cv[m]!.inF, cv[m]!.vis)).toBeGreaterThanOrEqual(0.9);
  });

  // ПРАВИЛО ВИДОВ v2 (T-20261108-73/4, владелец TG 668/671; `camPairV2`): вид 1 — у входной двери (`is_entrance`, хоть боковые двери
  // ближе к середине), взгляд внутрь, главное хранение целиком; вид 2 — дальняя часть коридора, в кадре целиком хоть один предмет
  // `intent.need` (зеркало, обувница, вешалка, консоль, банкетка). Целиком — во всех трёх окнах показа (`camV2Raw`)
  const whole = (c: Cam, list: It[], ids: number[]) => api.camV2Raw(c, list, W, H, ids).map((r) => r.every((x) => x.s === 1));
  for (const v of fx.variants) {
    it(`${v.id}: вид 1 у входной двери и шкаф в нём целиком, вид 2 — в дальней части, предмет коридора целиком`, () => {
      const pr = pairOf(v), list = its(v), [c1, c2] = pr.cams as [Cam, Cam];
      const en = api.camEntry()!, dw = en.o.width_cm, cx = en.o.offset_cm + dw / 2;
      expect(en.o.is_entrance).toBe(true);
      expect(en.o.wall).toBe("south");
      expect(pr.how).toMatch(/^v2: C1 со стороны двери \(south\)/);
      expect(c1.y, "глубина от плоскости двери").toBeLessThanOrEqual(100);
      expect(Math.abs(c1.x - cx), "сдвиг вдоль двери").toBeLessThanOrEqual(0.2 * dw + 1);
      expect(-Math.cos((c1.rot * Math.PI) / 180), "взгляд внутрь").toBeGreaterThanOrEqual(Math.cos((75 * Math.PI) / 180) - 1e-9);
      const S = api.camV2Set(list, api.camZ().intent);
      expect(whole(c1, list, S.mains).some(Boolean), `${v.id} C1: шкаф целиком`).toBe(true);
      expect(Math.hypot(c2.x - cx, c2.y), "вид 2 — дальше половины наибольшего расстояния до двери").toBeGreaterThanOrEqual(0.5 * Math.hypot(Math.max(cx, W - cx), H));
      expect(whole(c2, list, S.need).some(Boolean), `${v.id} C2: предмет коридора целиком`).toBe(true);
    });

    it(`${v.id}: ни один вид не «в упор» — главная вещь вплотную считается помехой, ближе 50 см к глазу мебели в кадре нет`, () => {
      const list = its(v);
      for (const c of pairOf(v).cams) {
        expect(api.camBlock(c, list).cov).toBeLessThanOrEqual(0.04);
        const cv = api.camCover(c, list, W, H);
        list.forEach((it, i) => {
          if (cv[i]!.inF > 0.05 && cv[i]!.vis > 0.05) expect(api.camNear(c, it)).toBeGreaterThanOrEqual(30);
        });
      }
    });
  }

  it("главная вещь вплотную — помеха только при mainBlock: перед дверцей шкафа-купе точка отсекается", () => {
    const v = fx.variants.find((x) => x.id === "hall-scandi")!, list = its(v);
    const wi = list.findIndex((it) => api.camIsMain(it)), w = list[wi]!;
    // в 40 см перед лицом шкафа, взгляд в дверцу
    const c = { name: "C1", x: w.x - w.d / 2 - 40, y: w.y, rot: 90, fov: 72 };
    expect(api.camNear(c, w)).toBeLessThan(api.CAM_NEAR);
    expect(api.camBlock(c, list).cov).toBeGreaterThan(0.04);
  });
});
