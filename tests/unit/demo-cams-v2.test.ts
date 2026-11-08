import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// ПРАВИЛО ВИДОВ v2 (T-20261108-73/4; владелец 08.11 TG 668 → план TG 670 → «Да» TG 671; план `room-cams-ends-01` § «Решение v2»).
// Вид 1 «Со стороны двери» — точка в проёме входа комнаты (глубина ≤ 75 см, на ступени 6 — 100; сдвиг вдоль двери ≤ 20 % её ширины),
// взгляд внутрь. Вид 2 «Другой ракурс» — по смыслу: гостиная — обеденный стол и его стулья целиком (нет стола — полоса у окна),
// спальня и прихожая — дальняя от двери зона. Виды не дубли (разворот ≥ 30° или точки 3D дальше 120 см). Мера — точный силуэт в трёх
// окнах показа (`camV2Raw`: живое 3D телефона и компьютера, кадр фото); крупное (≥ 5 % окна) и обязательное не срезаны. Не вышло
// строго — ступень лестницы и машинная строка WARN. Функции — из блока CAMFIT страницы (его же исполняет `tools/flat3d/demo-cams.mjs`).
type It = { role: string; x: number; y: number; rot: number; w: number; d: number; h: number | null };
type Cam = { name: string; x: number; y: number; rot: number; fov: number; poster?: boolean };
type Door = { kind: string; wall: string; offset_cm: number; width_cm: number; is_entrance?: boolean };
type Room = { w: number; d: number; kind?: string; openings: Door[] };
type Fx = { room: Room; one_layout?: boolean; variants: { id: string; style: string; items: It[]; cams?: Cam[] }[] };
type St = { s: number; fr: number; q: number };
type V2 = { cams: Cam[]; how: string; relax: number; warns: string[]; intent: string; keys: number[][]; per: { cams: Cam[] }[] };
type Api = {
  camPairAll: (L: It[][], W: number, H: number, cs: { x: number; y: number }[], o?: { prev?: Cam[] }) => V2;
  camV2Raw: (c: Cam, its: It[], W: number, H: number, ids: number[]) => St[][];
  camV2Set: (its: It[], I: unknown) => { ids: number[]; mains: number[]; tbl?: number; chairs: number[]; need: number[] };
  camEntry: () => { o: Door; warn: string } | null;
  camZ: () => { intent?: { c2: string[] } };
  camLiveSpot: (c: Cam, W: number, H: number) => { x: number; y: number };
  camAng: (a: number, b: number) => number;
  CAM_ZONES: Record<string, { intent?: unknown; ends?: unknown; views?: unknown }>;
  CAM_V2: { depth: number[]; depthWide: number[]; shift: number; inward: number; turn: number; apart: number; big: number; far: number; farWide: number };
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const load = (f: string) => JSON.parse(readFileSync(f, "utf8")) as Fx;
const apiOf = (room: Room) =>
  new Function("D", `${block};return {camPairAll,camV2Raw,camV2Set,camEntry,camZ,camLiveSpot,camAng,CAM_ZONES,CAM_V2,
    has:n=>{try{return typeof eval(n)!=='undefined';}catch(e){return false;}}};`)({ room }) as Api & { has: (n: string) => boolean };
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const corners = (W: number, H: number) => [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
const FX = {
  living: "tests/fixtures/demo-layouts-neo-0711.json",
  bed1: "tests/fixtures/demo-bedroom-1-one-1107.json",
  bed2: "tests/fixtures/demo-bedroom-2-one-1107.json",
  hall: "tests/fixtures/demo-hall-1107.json",
};
// вид 1 в проёме входа: глубина от плоскости двери, сдвиг вдоль неё, взгляд внутрь
const doorCheck = (api: Api, room: Room, c: Cam, tag: string) => {
  const G = api.CAM_V2, o = api.camEntry()!.o, W = room.w, H = room.d, u = o.offset_cm + o.width_cm / 2;
  const [px, py, nx, ny, tx, ty] = o.wall === "west" ? [0, u, 1, 0, 0, 1] : o.wall === "east" ? [W, u, -1, 0, 0, 1] : o.wall === "south" ? [u, 0, 0, 1, 1, 0] : [u, H, 0, -1, 1, 0];
  const depth = (c.x - px) * nx + (c.y - py) * ny, shift = Math.abs((c.x - px) * tx + (c.y - py) * ty);
  expect(depth, `${tag}: глубина от двери`).toBeLessThanOrEqual(Math.max(...G.depthWide) + 1e-9);
  expect(depth, `${tag}: в комнате`).toBeGreaterThanOrEqual(0);
  expect(shift, `${tag}: сдвиг вдоль двери`).toBeLessThanOrEqual(G.shift * o.width_cm + 1);
  const a = (c.rot * Math.PI) / 180;
  expect(Math.sin(a) * nx - Math.cos(a) * ny, `${tag}: взгляд внутрь`).toBeGreaterThanOrEqual(Math.cos((G.inward * Math.PI) / 180) - 1e-9);
  return { px, py };
};
// не дубль: разворот ≥ turn° или точки живого 3D дальше apart
const notDup = (api: Api, a: Cam, b: Cam, W: number, H: number, tag: string) => {
  const la = api.camLiveSpot(a, W, H), lb = api.camLiveSpot(b, W, H);
  const ok = api.camAng(a.rot, b.rot) >= api.CAM_V2.turn - 1e-9 || Math.hypot(la.x - lb.x, la.y - lb.y) > api.CAM_V2.apart;
  expect(ok, `${tag}: разворот ${api.camAng(a.rot, b.rot)}°`).toBe(true);
};
const whole = (api: Api, c: Cam, list: It[], W: number, H: number, ids: number[]) => api.camV2Raw(c, list, W, H, ids).map((r) => r.every((x) => x.s === 1));
// крупное (≥ big окна) не срезано ни в одном окне показа
const bigCuts = (api: Api, c: Cam, list: It[], W: number, H: number) => {
  const S = api.camV2Set(list, api.camZ().intent);
  return api.camV2Raw(c, list, W, H, S.ids).flatMap((r, k) => (r.some((x) => x.s === 2 && x.fr >= api.CAM_V2.big) ? [list[S.ids[k]!]!.role] : []));
};

describe("правило видов v2: данные и снятое", () => {
  const api = apiOf(load(FX.bed1).room);
  it("смысл видов — у гостиной, спальни и прихожей; у кухни нет (прежний подбор); правило «с двух концов» и виды зоны спальни сняты", () => {
    for (const k of ["living", "bedroom", "hall"]) expect(api.CAM_ZONES[k]!.intent, k).toBeTruthy();
    expect(api.CAM_ZONES.kitchen!.intent).toBeUndefined();
    for (const k of ["living", "bedroom", "hall", "kitchen"]) expect(api.CAM_ZONES[k]!.ends, k).toBeUndefined();
    expect(api.CAM_ZONES.bedroom!.views).toBeUndefined();
    expect(api.has("camEndsOk")).toBe(false);
  });
  it("вход комнаты: is_entrance; одна дверь — она; несколько без метки — самая широкая с WARN entry_ambiguous", () => {
    expect(apiOf(load(FX.hall).room).camEntry()!.o.wall).toBe("south");
    expect(apiOf(load(FX.bed1).room).camEntry()!.warn).toBe("");
    const two: Room = { w: 400, d: 300, openings: [{ kind: "door", wall: "south", offset_cm: 20, width_cm: 80 }, { kind: "door", wall: "east", offset_cm: 100, width_cm: 90 }] };
    const e = apiOf(two).camEntry()!;
    expect([e.o.wall, e.warn]).toEqual(["east", "entry_ambiguous"]);
  });
});

describe("правило видов v2: гостиная (слепок 07.11, 6 стилей)", () => {
  const fx = load(FX.living), api = apiOf(fx.room), { w: W, d: H } = fx.room;
  const memo = new Map<string, V2>();
  const pairOf = (vi: number) => {
    const v = fx.variants[vi]!;
    if (!memo.has(v.id)) memo.set(v.id, api.camPairAll([its(v)], W, H, corners(W, H)));
    return memo.get(v.id)!;
  };
  for (const [vi, v] of fx.variants.entries()) {
    it(`${v.style}: вид 1 у двери, вид 2 — стол и стулья целиком, разворот, крупное не срезано, строго (ступень 0)`, () => {
      const p = pairOf(vi), list = its(v), [c1, c2] = p.cams as [Cam, Cam], S = api.camV2Set(list, api.camZ().intent);
      expect(p.intent).toBe("dining");
      expect(p.relax, p.how).toBe(0);
      expect(p.warns).toEqual([]);
      doorCheck(api, fx.room, c1, v.style);
      expect(S.tbl, "стол в наборе").toBeGreaterThanOrEqual(0);
      expect(whole(api, c2, list, W, H, [S.tbl!]), "стол целиком").toEqual([true]);
      expect(whole(api, c2, list, W, H, S.chairs).every(Boolean), "стулья целиком").toBe(true);
      expect(whole(api, c1, list, W, H, S.mains).some(Boolean), "главное в виде 1 целиком").toBe(true);
      notDup(api, c1, c2, W, H, v.style);
      for (const c of [c1, c2]) expect(bigCuts(api, c, list, W, H), `${v.style} ${c.name}`).toEqual([]);
      expect(p.cams.filter((c) => c.poster)).toHaveLength(1);
    }, 120_000);
  }
  it("детерминированно: тот же вход — те же точки", () => {
    const a = api.camPairAll([its(fx.variants[0]!)], W, H, corners(W, H)), b = pairOf(0);
    expect(a.cams.map((c) => [c.x, c.y, c.rot, c.fov])).toEqual(b.cams.map((c) => [c.x, c.y, c.rot, c.fov]));
  }, 120_000);
  it("без стола — вид 2 у окна: точка в полосе 50–120 см от окна (на ступени 6 — 30–160), взгляд от окна в комнату", () => {
    const list = its(fx.variants[0]!).filter((it) => it.role !== "стол обеденный" && !it.role.startsWith("стул"));
    const p = api.camPairAll([list], W, H, corners(W, H)), c2 = p.cams[1]!;
    expect(p.intent).toBe("window");
    // окно гостиной — западная стена
    expect(c2.x, p.how).toBeGreaterThanOrEqual(p.relax >= 6 ? 30 : 50);
    expect(c2.x, p.how).toBeLessThanOrEqual(p.relax >= 6 ? 160 : 120);
    expect(Math.sin((c2.rot * Math.PI) / 180)).toBeGreaterThan(0);
  }, 120_000);
  it("комнаты без двери — прежняя годная пара (last-known-good) и WARN, не случайная", () => {
    const noDoor: Room = { ...fx.room, openings: fx.room.openings.filter((o) => o.kind !== "door") };
    const list = its(fx.variants[0]!), prev = pairOf(0).cams.map((c) => ({ ...c }));
    const p = apiOf(noDoor).camPairAll([list], W, H, corners(W, H), { prev });
    expect(p.cams.map((c) => [c.x, c.y, c.rot, c.fov])).toEqual(prev.map((c) => [c.x, c.y, c.rot, c.fov]));
    expect(p.warns.join(" ")).toMatch(/reason=no_entry keep=last_good/);
  }, 120_000);
});

describe("правило видов v2: спальни (слепки 07.11, 5 стилей)", () => {
  it("спальня 1: одна пара на 5 стилей — вид 1 от двери вдоль стены с кроватью (ступень 6, WARN wall_graze), кровать целиком; вид 2 — дальняя зона", () => {
    const fx = load(FX.bed1), api = apiOf(fx.room), { w: W, d: H } = fx.room, L = fx.variants.map(its);
    const p = api.camPairAll(L, W, H, corners(W, H)), [c1, c2] = p.cams as [Cam, Cam];
    expect(p.intent).toBe("far");
    expect(p.relax, p.how).toBeLessThanOrEqual(6);
    if (p.relax === 6) expect(p.warns.join(" ")).toMatch(/view=C1 relax=6 reason=.*wall_graze/);
    const { px, py } = doorCheck(api, fx.room, c1, "спальня 1");
    const maxD = Math.max(...[[0, 0], [W, 0], [W, H], [0, H]].map(([x, y]) => Math.hypot(x! - px, y! - py)));
    expect(Math.hypot(c2.x - px, c2.y - py), "вид 2 — дальняя зона").toBeGreaterThanOrEqual(api.CAM_V2.far * maxD - 1e-9);
    notDup(api, c1, c2, W, H, "спальня 1");
    for (const list of L) {
      const S = api.camV2Set(list, api.camZ().intent);
      expect(whole(api, c1, list, W, H, S.mains), "кровать в виде 1").toEqual([true]);
      expect(whole(api, c2, list, W, H, S.mains), "кровать в виде 2").toEqual([true]);
      for (const c of [c1, c2]) expect(bigCuts(api, c, list, W, H), c.name).toEqual([]);
    }
  }, 300_000);
  // спальня 2 (4,50 × 2,93): дверь в середине южной стены, изножье кровати в 30 см от глаза живого 3D у двери — целиком её от двери не
  // видно ни из одной точки (фиксация: ступень 8 и WARN по виду 1); дальние углы заняты кроватью, тумбами и шкафом — кровать целиком
  // видна в виде 2, и обложка — он
  it("спальня 2, своя пара стиля: вид 1 от двери, вид 2 — кровать целиком, обложка — вид 2; что не вышло — WARN по виду", () => {
    const fx = load(FX.bed2), api = apiOf(fx.room), { w: W, d: H } = fx.room;
    for (const v of fx.variants) {
      const list = its(v), p = api.camPairAll([list], W, H, corners(W, H)), [c1, c2] = p.cams as [Cam, Cam], S = api.camV2Set(list, api.camZ().intent);
      doorCheck(api, fx.room, c1, v.style);
      notDup(api, c1, c2, W, H, v.style);
      expect(whole(api, c2, list, W, H, S.mains), `${v.style}: кровать в виде 2 (${p.how})`).toEqual([true]);
      if (p.relax > 0) expect(p.warns.length, `${v.style}: ступень ${p.relax} без WARN`).toBeGreaterThan(0);
      for (const w of p.warns) expect(w).toMatch(/^view=C[12]( intent=\w+)? relax=\d reason=/);
      const k = p.cams.findIndex((c) => c.poster);
      expect(whole(api, p.cams[k]!, list, W, H, S.mains), `${v.style}: обложка с кроватью`).toEqual([true]);
    }
  }, 600_000);
});

// ПОДПИСИ ВИДОВ — ПО НОМЕРУ (`vwCamNames`): вид 1 — «Со стороны двери», вид 2 — «Другой ракурс»; не зависят от точки
describe("правило видов v2: подписи", () => {
  const src = html.slice(html.indexOf("const CAM_VIEW_NAMES="), html.indexOf("// ПОДПИСИ КНОПОК РАКУРСА ЦЕЛИКОМ"));
  const names = (lang: string, short: boolean, cs: Cam[]) =>
    (new Function("CS", `const LANG='${lang}';let cams=null;const loadCams=()=>CS;${src};return vwCamNames(${short});`) as (cs: Cam[]) => string[])(cs);
  const at = (x: number, y: number) => ({ name: "C", x, y, rot: 0, fov: 72 });
  it("RU и EN, полные и короткие; одинаковые при любых точках", () => {
    for (const cs of [[at(436, 232), at(203, 83)], [at(3, 3), at(500, 280)]]) {
      expect(names("ru", false, cs)).toEqual(["Со стороны двери", "Другой ракурс"]);
      expect(names("ru", true, cs)).toEqual(["От двери", "Другой ракурс"]);
      expect(names("en", false, cs)).toEqual(["From the door", "Another view"]);
      expect(names("en", true, cs)).toEqual(["Door", "Another view"]);
    }
  });
});

// СБОРКА (`demo-cams.mjs`): общая пара на стили не вышла строго — у стиля своя, если она лучше; каждая ступень > 0 итоговой пары —
// строка `WARN:demo_cams room=… style=… view=C… relax=N reason=…`
describe("правило видов v2: demo-cams.mjs", () => {
  it("гостиная 07.11: у каждого стиля пара с видом 1 у двери; WARN — машинной строкой; за бюджет 300 с", () => {
    const dir = mkdtempSync(join(process.env.REMLAB_TMP || tmpdir(), "cams-v2-")), f = join(dir, "demo-data.json");
    writeFileSync(f, readFileSync(FX.living));
    const t = Date.now(), log = execFileSync("node", ["tools/flat3d/demo-cams.mjs", f], { encoding: "utf8" });
    expect(Date.now() - t).toBeLessThan(300_000);
    for (const s of log.split("\n").filter((x) => x.startsWith("WARN:demo_cams room=")))
      expect(s).toMatch(/^WARN:demo_cams room=\S+ style=\S+ view=(C1|C2|pair)( intent=\w+)? relax=\d reason=/);
    const out = JSON.parse(readFileSync(f, "utf8")) as Fx, api = apiOf(out.room);
    for (const v of out.variants) {
      expect(v.cams, v.id).toHaveLength(2);
      doorCheck(api, out.room, v.cams![0]!, v.id);
    }
  }, 600_000);
});
