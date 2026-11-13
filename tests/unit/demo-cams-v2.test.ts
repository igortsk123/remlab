import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// ПРАВИЛО ВИДОВ v2 (T-20261108-73/4; владелец 08.11 TG 668 → план TG 670 → «Да» TG 671; план `room-cams-ends-01` § «Решение v2»).
// Вид 1 «Со стороны двери» — точка в проёме входа комнаты (глубина ≤ 75 см, на ступени 6 — 100; сдвиг вдоль двери ≤ 20 % её ширины),
// взгляд внутрь. Вид 2 «Другой ракурс» — по смыслу: гостиная — обеденный стол и его стулья целиком (нет стола — полоса у окна),
// спальня и прихожая — дальняя от двери зона; у любого смысла точка вида 2 — у противоположной от входа стены, взгляд обратно к
// входу (T-20261112-30, `oppCheck`). Виды не дубли (разворот ≥ 30° или точки 3D дальше 120 см). Мера — точный силуэт в окнах
// показа (`camV2Raw`: живое 3D телефона и компьютера, кадр фото позой съёмки и фото на телефоне — T-73/6); крупное (≥ 5 % окна) и
// обязательное не срезаны (окно телефона — мягко: доля главного на экране, `phoneQ`). Не вышло
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
  camZ: () => { intent?: { c2: string[]; hero?: { roles: string[]; face: number } } };
  camLiveSpot: (c: Cam, W: number, H: number) => { x: number; y: number };
  camAng: (a: number, b: number) => number;
  CAM_ZONES: Record<string, { intent?: unknown; ends?: unknown; views?: unknown }>;
  CAM_V2: { depth: number[]; depthWide: number[]; shift: number; inward: number; turn: number; apart: number; big: number; far: number; farWide: number;
    band: { side: number; depth: number[] }; back: number; pairFar: number };
  CAM_V2_BAND: number;
  JPH: number;
};
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// CAMFIT START"), html.indexOf("// CAMFIT END"));
const load = (f: string) => JSON.parse(readFileSync(f, "utf8")) as Fx;
const apiOf = (room: Room) =>
  new Function("D", `${block};return {camPairAll,camV2Raw,camV2Set,camEntry,camZ,camLiveSpot,camAng,CAM_ZONES,CAM_V2,CAM_V2_BAND,JPH,
    has:n=>{try{return typeof eval(n)!=='undefined';}catch(e){return false;}}};`)({ room }) as Api & { has: (n: string) => boolean };
const its = (v: { items: It[] }) => v.items.map((it) => ({ ...it, x: +it.x, y: +it.y, w: +it.w, d: +it.d, rot: +it.rot || 0 }));
const corners = (W: number, H: number) => [{ x: 3, y: 3 }, { x: W - 3, y: 3 }, { x: W - 3, y: H - 3 }, { x: 3, y: H - 3 }];
const FX = {
  living: "tests/fixtures/demo-layouts-neo-0711.json",
  bed1: "tests/fixtures/demo-bedroom-1-one-1107.json",
  bed2: "tests/fixtures/demo-bedroom-2-one-1107.json",
  hall: "tests/fixtures/demo-hall-1107.json",
};
// вид 1 в проёме входа: глубина от плоскости двери, сдвиг вдоль неё, взгляд внутрь; `band` — полоса у стены двери (ступень
// `CAM_V2_BAND`, T-73/5): до `band.side` см от края проёма, глубина `band.depth`
const doorCheck = (api: Api, room: Room, c: Cam, tag: string, band = false) => {
  const G = api.CAM_V2, o = api.camEntry()!.o, W = room.w, H = room.d, u = o.offset_cm + o.width_cm / 2;
  const [px, py, nx, ny, tx, ty] = o.wall === "west" ? [0, u, 1, 0, 0, 1] : o.wall === "east" ? [W, u, -1, 0, 0, 1] : o.wall === "south" ? [u, 0, 0, 1, 1, 0] : [u, H, 0, -1, 1, 0];
  const depth = (c.x - px) * nx + (c.y - py) * ny, shift = Math.abs((c.x - px) * tx + (c.y - py) * ty);
  expect(depth, `${tag}: глубина от двери`).toBeLessThanOrEqual(Math.max(...(band ? G.band.depth : G.depthWide)) + 1e-9);
  expect(depth, `${tag}: в комнате`).toBeGreaterThanOrEqual(band ? Math.min(...G.band.depth) - 1e-9 : 0);
  if (band) expect(shift - o.width_cm / 2, `${tag}: от края проёма вдоль стены`).toBeLessThanOrEqual(G.band.side + 1);
  else expect(shift, `${tag}: сдвиг вдоль двери`).toBeLessThanOrEqual(G.shift * o.width_cm + 1);
  const a = (c.rot * Math.PI) / 180;
  expect(Math.sin(a) * nx - Math.cos(a) * ny, `${tag}: взгляд внутрь`).toBeGreaterThanOrEqual(Math.cos((G.inward * Math.PI) / 180) - 1e-9);
  return { px, py };
};
// ВИД 2 — С ПРОТИВОПОЛОЖНОЙ СТОРОНЫ (T-20261112-30, владелец: «ракурсы должны быть с противоположных стен, а сейчас ты просто
// поворачиваешь камеру на месте»): глубина точки вида 2 от стены входа по нормали проёма ≥ `farWide` глубины комнаты (иначе — WARN
// `zone_any`, и тогда хотя бы дальше вида 1), взгляд обратно к входу (≤ `back`°), точки пары разнесены ≥ `pairFar` диагонали
const oppCheck = (api: Api, room: Room, c1: Cam, c2: Cam, ws: string, tag: string) => {
  const G = api.CAM_V2, o = api.camEntry()!.o, W = room.w, H = room.d, u = o.offset_cm + o.width_cm / 2;
  const [px, py, nx, ny] = o.wall === "west" ? [0, u, 1, 0] : o.wall === "east" ? [W, u, -1, 0] : o.wall === "south" ? [u, 0, 0, 1] : [u, H, 0, -1];
  const dep = (x: number, y: number) => (x - px) * nx + (y - py) * ny;
  const depN = Math.max(...[[0, 0], [W, 0], [W, H], [0, H]].map(([x, y]) => dep(x!, y!)));
  if (/zone_any/.test(ws)) expect(dep(c2.x, c2.y), `${tag}: вид 2 дальше вида 1 от стены входа`).toBeGreaterThan(dep(c1.x, c1.y));
  else {
    expect(dep(c2.x, c2.y) / depN, `${tag}: вид 2 у противоположной стены`).toBeGreaterThanOrEqual(G.farWide - 1e-9);
    expect(Math.hypot(c1.x - c2.x, c1.y - c2.y), `${tag}: точки пары разнесены`).toBeGreaterThanOrEqual(G.pairFar * Math.hypot(W, H) - 1e-9);
  }
  const back = (Math.atan2(px - c2.x, -(py - c2.y)) * 180) / Math.PI;   // взгляд позы: (sin rot, −cos rot)
  expect(api.camAng(c2.rot, back), `${tag}: вид 2 смотрит к входу`).toBeLessThanOrEqual(G.back + 1e-9);
};
// не дубль: разворот ≥ turn° или точки живого 3D дальше apart
const notDup = (api: Api, a: Cam, b: Cam, W: number, H: number, tag: string) => {
  const la = api.camLiveSpot(a, W, H), lb = api.camLiveSpot(b, W, H);
  const ok = api.camAng(a.rot, b.rot) >= api.CAM_V2.turn - 1e-9 || Math.hypot(la.x - lb.x, la.y - lb.y) > api.CAM_V2.apart;
  expect(ok, `${tag}: разворот ${api.camAng(a.rot, b.rot)}°`).toBe(true);
};
// целиком — во всех окнах показа, кроме фото на телефоне (его досматривают пальцем; мера — доля главного на экране `phoneQ`)
const whole = (api: Api, c: Cam, list: It[], W: number, H: number, ids: number[]) =>
  api.camV2Raw(c, list, W, H, ids).map((r) => r.every((x, j) => j === api.JPH || x.s === 1));
const phoneQ = (api: Api, c: Cam, list: It[], W: number, H: number, ids: number[]) =>
  Math.max(0, ...api.camV2Raw(c, list, W, H, ids).map((r) => (r[api.JPH]!.s ? r[api.JPH]!.q : 0)));
// крупное (≥ big окна) не срезано ни в одном окне показа (кроме телефона)
// ЗОНА ОТДЫХА ЛИЦОМ (R1+, T-20261112-111/6): главное зоны (`intent.hero.roles`) целиком в кадре фото и угол между его лицом
// (локальный +y, повёрнутый на rot: (sin rot, cos rot)) и направлением на камеру ≤ `face`°
const heroFront = (api: Api, c: Cam, list: It[], W: number, H: number) => {
  const hero = api.camZ().intent!.hero!, S = api.camV2Set(list, api.camZ().intent), raw = api.camV2Raw(c, list, W, H, S.ids);
  const photo = 2;   // `CAM_V2_WIN`: ['phone_live','desk_live','photo','phone_photo']
  return S.ids.some((i, k) => {
    const it = list[i]!;
    if (!hero.roles.includes(it.role) || raw[k]![photo]!.s !== 1) return false;
    const a = (it.rot * Math.PI) / 180, ux = c.x - it.x, uy = c.y - it.y;
    return (Math.sin(a) * ux + Math.cos(a) * uy) / (Math.hypot(ux, uy) || 1) >= Math.cos((hero.face * Math.PI) / 180) - 1e-9;
  });
};
const bigCuts = (api: Api, c: Cam, list: It[], W: number, H: number) => {
  const S = api.camV2Set(list, api.camZ().intent);
  return api.camV2Raw(c, list, W, H, S.ids).flatMap((r, k) => (r.some((x, j) => j !== api.JPH && x.s === 2 && x.fr >= api.CAM_V2.big) ? [list[S.ids[k]!]!.role] : []));
};

describe("правило видов v2: данные и снятое", () => {
  const api = apiOf(load(FX.bed1).room);
  // T-20261112-76/2: смысл видов — у каждого типа комнаты (кухня, санузел, прочие — профили `demo-cams-kinds.test.ts`)
  it("смысл видов — у гостиной, спальни, прихожей и кухни; правило «с двух концов» и виды зоны спальни сняты", () => {
    for (const k of ["living", "bedroom", "hall", "kitchen"]) expect(api.CAM_ZONES[k]!.intent, k).toBeTruthy();
    for (const k of ["living", "bedroom", "hall", "kitchen"]) expect(api.CAM_ZONES[k]!.ends, k).toBeUndefined();
    expect(api.CAM_ZONES.bedroom!.views).toBeUndefined();
    expect(api.has("camEndsOk")).toBe(false);
  });
  // R1+ (T-20261112-111/6): «зона отдыха лицом» — только у гостиной; спальни, прихожая, кухня подбираются как были
  it("главное лицом (intent.hero) — только у гостиной: диван, ≤ 60°", () => {
    expect((api.CAM_ZONES.living!.intent as { hero?: unknown }).hero).toEqual({ roles: ["диван"], face: 60 });
    for (const k of ["bedroom", "hall", "kitchen"]) expect((api.CAM_ZONES[k]!.intent as { hero?: unknown }).hero, k).toBeUndefined();
  });
  it("вход комнаты: is_entrance; одна дверь — она; несколько без метки — самая широкая с WARN entry_ambiguous", () => {
    expect(apiOf(load(FX.hall).room).camEntry()!.o.wall).toBe("south");
    expect(apiOf(load(FX.bed1).room).camEntry()!.warn).toBe("");
    const two: Room = { w: 400, d: 300, openings: [{ kind: "door", wall: "south", offset_cm: 20, width_cm: 80 }, { kind: "door", wall: "east", offset_cm: 100, width_cm: 90 }] };
    const e = apiOf(two).camEntry()!;
    expect([e.o.wall, e.warn]).toEqual(["east", "entry_ambiguous"]);
  });
  // T-20261112-30: у туров по плану вход гостиной и спальни — проём без полотна (`kind: opening`, `pipeline.py`); прежде вход искался
  // только среди дверей → `no_entry` и прежняя пара (обе точки у одной стены в 10–60 см)
  it("вход — и проём без двери (kind opening), окно — не вход", () => {
    const room: Room = { w: 335, d: 380, openings: [{ kind: "window", wall: "south", offset_cm: 90, width_cm: 150 }, { kind: "opening", wall: "north", offset_cm: 80, width_cm: 255 }] };
    const e = apiOf(room).camEntry()!;
    expect([e.o.kind, e.o.wall, e.warn]).toEqual(["opening", "north", ""]);
    expect(apiOf({ ...room, openings: room.openings.slice(0, 1) }).camEntry()).toBeNull();
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
    // T-20261112-30: вид 2 теперь у противоположной от двери (окно) стены и смотрит обратно — строго (ступень 0) не выходит:
    // ближняя к глазу мебель у окна в кадр целиком не входит (доля целиком < `fullMin`), крупное режется краем; это цена «видов с
    // противоположных стен» — ступень и WARN по виду, крупное без срезов — у вида 1
    // R1+ (T-20261112-111/6): у всех 6 стилей слепка диван спинкой к стене двери — от двери он сбоку; пара обязана держать его лицом
    // хотя бы в одном виде (WARN `hero_front_c1|c2` — какой держит), иначе WARN `living_front_missing`. Вид 2 'dining' — пока вид 1
    // может держать диван (`hero_front_c1`, в полосе у стены двери); иначе вид 2 — зона отдыха ('window')
    it(`${v.style}: вид 1 у двери, вид 2 — с противоположной стороны к входу, стол и стулья целиком; диван лицом; ступень > 0 — с WARN`, () => {
      const p = pairOf(vi), list = its(v), [c1, c2] = p.cams as [Cam, Cam], S = api.camV2Set(list, api.camZ().intent), ws = p.warns.join(" ");
      expect(p.intent).toBe(/reason=hero_front_c2/.test(ws) ? "window" : "dining");
      if (p.relax > 0) expect(p.warns.length, `ступень ${p.relax} без WARN (${p.how})`).toBeGreaterThan(0);
      for (const w of p.warns) expect(w).toMatch(/^view=(C[12]|pair)( intent=\w+)? relax=\d reason=/);
      if (!/living_front_missing/.test(ws)) expect(heroFront(api, c1, list, W, H) || heroFront(api, c2, list, W, H), `${v.style}: диван лицом (${p.how})`).toBe(true);
      if (/reason=hero_front_c1/.test(ws)) expect(heroFront(api, c1, list, W, H), `${v.style}: вид 1 держит диван лицом`).toBe(true);
      doorCheck(api, fx.room, c1, v.style, /door_wall_band/.test(ws));
      oppCheck(api, fx.room, c1, c2, ws, v.style);
      expect(S.tbl, "стол в наборе").toBeGreaterThanOrEqual(0);
      if (p.intent === "dining") {
        expect(whole(api, c2, list, W, H, [S.tbl!]), `стол целиком (${p.how})`).toEqual([true]);
        expect(whole(api, c2, list, W, H, S.chairs).every(Boolean), "стулья целиком").toBe(true);
      }
      expect(whole(api, c1, list, W, H, S.mains).some(Boolean), "главное в виде 1 целиком").toBe(true);
      notDup(api, c1, c2, W, H, v.style);
      // крупное в виде 1 не режется; исключение R1+ — вид 1 держит диван лицом (`hero_front_c1`) и чистой такой точки нет: срез —
      // только не самого дивана и только названный в WARN вида 1 (`major_cut object=…`)
      const cut1 = bigCuts(api, c1, list, W, H), heroC1 = /reason=hero_front_c1/.test(ws);
      if (!heroC1) expect(cut1, `${v.style} C1`).toEqual([]);
      for (const r of cut1) {
        expect(r, `${v.style} C1: диван не режется`).not.toBe("диван");
        expect(ws, `${v.style} C1: срез ${r} назван в WARN`).toMatch(new RegExp(`view=C1 relax=\\d reason=.*major_cut object=${r} `));
      }
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
  // T-73/6 (владелец TG 690): кадр фото — поза съёмки (глаз 150, вниз 8°), низ кадра режет; фото на телефоне — окно экрана по
  // кровати. Замер 08.11: с позой 2 и мерой «низ не режет» кровать «целиком», а в кадре было 0,52–0,82 и на телефоне 0,34–0,51.
  // Теперь кровать целиком в кадре обоих видов, на телефоне ≥ 0,8; строго не выходит — тумбу у кровати режет низ кадра вида 1
  // (ступень 9, WARN по виду)
  it("спальня 1: одна пара на 5 стилей — вид 1 от двери, вид 2 — дальняя зона; кровать целиком в кадре обоих видов, на телефоне ≥ 0,8", () => {
    const fx = load(FX.bed1), api = apiOf(fx.room), { w: W, d: H } = fx.room, L = fx.variants.map(its);
    const p = api.camPairAll(L, W, H, corners(W, H)), [c1, c2] = p.cams as [Cam, Cam], ws = p.warns.join(" ");
    expect(p.intent).toBe("far");
    if (p.relax > 0) expect(ws, `ступень ${p.relax} без WARN`).toMatch(/view=C1 relax=\d reason=/);
    doorCheck(api, fx.room, c1, "спальня 1", /door_wall_band/.test(ws));
    oppCheck(api, fx.room, c1, c2, ws, "спальня 1");
    notDup(api, c1, c2, W, H, "спальня 1");
    expect(api.camAng(c1.rot, c2.rot), "виды смотрят на разные стены").toBeGreaterThanOrEqual(90);
    for (const list of L) {
      const S = api.camV2Set(list, api.camZ().intent);
      expect(whole(api, c1, list, W, H, S.mains), "кровать в виде 1").toEqual([true]);
      expect(whole(api, c2, list, W, H, S.mains), "кровать в виде 2").toEqual([true]);
      for (const c of [c1, c2]) expect(phoneQ(api, c, list, W, H, S.mains), `${c.name}: кровать на телефоне`).toBeGreaterThanOrEqual(0.8);
      for (const c of [c1, c2]) for (const r of bigCuts(api, c, list, W, H)) expect(r, c.name).toBe("тумба прикроватная");
    }
  }, 300_000);
  // спальня 2 (4,50 × 2,93): дверь в середине южной стены, изножье кровати в 30 см от глаза живого 3D у двери — из проёма кровать
  // целиком не видна. T-73/5 (ведущий): вид 1 — в полосе у стены двери (ступень `CAM_V2_BAND` и выше, WARN `door_wall_band`).
  // T-73/6: мера — кадр позы съёмки (низ режет) и фото на телефоне. Замер 08.11: было в кадре 0,36–0,65, на телефоне 0,24–0,47;
  // стало — кровать целиком хотя бы в одном виде, в каждом виде ≥ 0,9 кадра и ≥ 0,7 на телефоне; что не вышло — WARN по виду
  // [кадр, телефон] вида 1 и вида 2. Замер 12.11 (вид 2 у стены напротив двери): вид 1 — кадр 0,91–1,00, телефон 0,80–0,90; вид 2 —
  // кадр 0,41–0,99, телефон 0,25–0,70 (хуже всех джапанди: кровать изголовьем к стене вида 2, с той стороны видна сбоку)
  const BED2_MIN: [number, number][] = [[0.9, 0.7], [0.4, 0.25]];
  it("спальня 2, своя пара стиля: вид 1 у двери или у стены двери — кровать целиком хотя бы в одном виде, вид 2 — у стены напротив; что не вышло — WARN", () => {
    const fx = load(FX.bed2), api = apiOf(fx.room), { w: W, d: H } = fx.room;
    // доля кровати в худшем окне показа, кроме телефона
    const q = (c: Cam, list: It[], ids: number[]) =>
      Math.max(0, ...api.camV2Raw(c, list, W, H, ids).map((r) => Math.min(...r.filter((_, j) => j !== api.JPH).map((x) => (x.s ? x.q : 0)))));
    const got: string[] = [], low: string[] = [];
    for (const v of fx.variants) {
      const list = its(v), p = api.camPairAll([list], W, H, corners(W, H)), [c1, c2] = p.cams as [Cam, Cam], S = api.camV2Set(list, api.camZ().intent);
      const ws = p.warns.join(" "), band = /reason=.*door_wall_band/.test(ws);
      if (band) expect(p.relax, `${v.style}: полоса у стены двери не раньше своей ступени`).toBeGreaterThanOrEqual(api.CAM_V2_BAND);
      doorCheck(api, fx.room, c1, v.style, band);
      oppCheck(api, fx.room, c1, c2, ws, v.style);
      notDup(api, c1, c2, W, H, v.style);
      const w1 = whole(api, c1, list, W, H, S.mains)[0], w2 = whole(api, c2, list, W, H, S.mains)[0];
      // T-20261112-30: вид 2 — у стены напротив двери (северной), взгляд к двери; кровать изголовьем к этой стене с той стороны
      // целиком в кадр не входит, а у джапанди кровать целиком была видна только от окна (западная стена — сбоку, не напротив):
      // теперь «почти целиком» (≥ 0,95 кадра) хотя бы в одном виде; пороги вида 2 — `BED2_MIN` (замер 12.11)
      expect(w1 || w2 || Math.max(q(c1, list, S.mains), q(c2, list, S.mains)) >= 0.95, `${v.style}: кровать (почти) целиком хотя бы в одном виде (${p.how})`).toBe(true);
      for (const [k, c] of [c1, c2].entries()) {
        const fr = q(c, list, S.mains), ph = phoneQ(api, c, list, W, H, S.mains), [lf, lp] = BED2_MIN[k]!;
        got.push(`${v.style} ${c.name} кадр ${fr.toFixed(2)} телефон ${ph.toFixed(2)}`);
        if (fr < lf || ph < lp) low.push(got.at(-1)!);
      }
      if (!w1) expect(ws, `${v.style}: вид 1 без кровати целиком — WARN`).toMatch(/view=C1 relax=\d reason=.*main_not_whole/);
      if (p.relax > 0) expect(p.warns.length, `${v.style}: ступень ${p.relax} без WARN`).toBeGreaterThan(0);
      for (const w of p.warns) expect(w).toMatch(/^view=C[12]( intent=\w+)? relax=\d reason=/);
      const k = p.cams.findIndex((c) => c.poster);
      expect(whole(api, p.cams[k]!, list, W, H, S.mains)[0] || q(p.cams[k]!, list, S.mains) >= 0.95, `${v.style}: обложка с кроватью`).toBe(true);
    }
    expect(low, got.join("; ")).toEqual([]);
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
    const out = JSON.parse(readFileSync(f, "utf8")) as Fx, api = apiOf(out.room), lines = log.split("\n");
    for (const v of out.variants) {
      expect(v.cams, v.id).toHaveLength(2);
      // вид 1 в полосе у стены двери — только со строкой WARN `door_wall_band` своего стиля (`demo-cams.mjs`: `style=${style || id}`)
      const band = lines.some((s) => s.startsWith("WARN:demo_cams room=") && s.includes(`style=${v.style || v.id} `) && s.includes("door_wall_band"));
      doorCheck(api, out.room, v.cams![0]!, v.id, band);
    }
  }, 600_000);
});
