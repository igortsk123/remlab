import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// СТРОГО ФОТО НЕЙРОСЕТИ (T-20261107-35/1 часть 0; владелец TG 341, TG 378; план photo-before-publish-01 § А). Чистая функция — блок
// REALSHOT страницы демо (`realPubPick`, обёртка `realisticPublishedShot`); тест читает блок из страницы, как QUIZPICK.
const SRC = "tools/scout/flat215-demo/index.html";
type Shot = { url?: string; quality?: string; stateId?: string; vid?: string; camera?: string; ts?: number; bad?: boolean };

const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// REALSHOT START"), src.indexOf("// REALSHOT END"));
const realPubPick = new Function(`${block};return realPubPick;`)() as (
  list: Shot[], st: string, vid: string, cam: string, camOk: (x: Shot) => boolean,
) => Shot | null;
const camOk = (x: Shot) => !x.bad;   // в странице — `shotCamOk(x, v.cams)`: точка кадра совпадает с нынешней
const pick = (list: Shot[], cam = "C1") => realPubPick(list, "S-now", "set1", cam, camOk)?.url ?? null;
const sh = (url: string, o: Partial<Shot>): Shot => ({ url, quality: "realistic", vid: "set1", camera: "C1", ts: 1, ...o });

describe("realisticPublishedShot — порядок и запреты", () => {
  it("1) фото нейросети этой расстановки; точка cam важнее, нет её — другая точка того же состояния", () => {
    const list = [sh("old", { stateId: "S-old", ts: 9 }), sh("now-c2", { stateId: "S-now", camera: "C2" }), sh("now-c1", { stateId: "S-now" })];
    expect(pick(list)).toBe("now-c1");
    expect(pick([sh("now-c2", { stateId: "S-now", camera: "C2" })])).toBe("now-c2");
  });
  it("2) этой нет — последнее (по времени) фото того же варианта и той же точки из прежних расстановок", () => {
    const list = [sh("old-1", { stateId: "S-a", ts: 5 }), sh("old-2", { stateId: "S-b", ts: 7 }), sh("old-c2", { stateId: "S-c", camera: "C2", ts: 9 }),
      sh("other-v", { stateId: "S-d", vid: "set6", ts: 10 })];
    expect(pick(list)).toBe("old-2");
    expect(pick(list, "C2")).toBe("old-c2");
  });
  it("3) нет ни того, ни другого — null (вариант не показываем)", () => {
    expect(pick([])).toBeNull();
    expect(pick([sh("other-v", { stateId: "S-x", vid: "set6" })])).toBeNull();
  });
  it("черновик (3D) — никогда, даже этой расстановки и единственный", () => {
    expect(pick([sh("draft-now", { stateId: "S-now", quality: "draft" })])).toBeNull();
    expect(pick([sh("draft-now", { stateId: "S-now", quality: "draft", ts: 9 }), sh("old", { stateId: "S-old" })])).toBe("old");
    expect(pick([sh("live", { stateId: "S-now", quality: "live" })])).toBeNull();
  });
  it("точка этой расстановки не совпадает с нынешней — на шаге 1 кадр не годится, на шаге 2 годится (прежнее — это картинка)", () => {
    // сборка 15:19 сдвинула точку 1: у гостиных C1 не совпадает, C2 совпадает — раньше шаг 2 требовал и ту же точку, и совпадение → null
    // кадр этой расстановки с несовпадающей точкой на шаге 1 не берётся, но это фото того же варианта — на шаге 2 годится; совпадающее
    // фото прежней расстановки той же точки его опережает
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true })])).toBe("now-bad");
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true, ts: 9 }), sh("old-ok", { stateId: "S-old", ts: 2 })])).toBe("old-ok");
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true, ts: 2 }), sh("old-bad", { stateId: "S-old", bad: true, ts: 5 })])).toBe("old-bad");
    expect(pick([sh("old-c1-bad", { stateId: "S-a", ts: 9, bad: true }), sh("old-c2", { stateId: "S-a", camera: "C2", ts: 5 })])).toBe("old-c1-bad");
  });
  it("шаг 2 — порядок: та же точка и совпадает → та же точка → любая совпадающая → любая; внутри — свежее", () => {
    const a = sh("c1-ok", { stateId: "S-a", ts: 1 }), b = sh("c1-bad", { stateId: "S-b", ts: 8, bad: true });
    const c = sh("c2-ok", { stateId: "S-c", camera: "C2", ts: 9 }), d = sh("c3-bad", { stateId: "S-d", camera: "C3", ts: 10, bad: true });
    expect(pick([a, b, c, d])).toBe("c1-ok");
    expect(pick([b, c, d])).toBe("c1-bad");
    expect(pick([c, d])).toBe("c2-ok");
    expect(pick([d])).toBe("c3-bad");
    expect(pick([sh("c1-new", { stateId: "S-a", ts: 7, bad: true }), sh("c1-old", { stateId: "S-b", ts: 3, bad: true })])).toBe("c1-new");
  });
  it("шаг 2 — только тот же вариант и только фото нейросети", () => {
    expect(pick([sh("other-v", { stateId: "S-x", vid: "set6", camera: "C2" })])).toBeNull();
    expect(pick([sh("draft-old", { stateId: "S-x", quality: "draft", camera: "C2" })])).toBeNull();
  });
  it("кадр без адреса или без номера состояния на шаге 1 не считается кадром этой расстановки", () => {
    expect(pick([sh("", { stateId: "S-now" })])).toBeNull();
    expect(pick([sh("nostate", { stateId: "" , vid: "set6" })])).toBeNull();
  });
});

// ФОТО ВИДА В ОКНЕ — ТОЛЬКО СО СВОЕЙ ТОЧКИ (T-20261108-73, ведущий 08.11: «подпись не должна врать» — после пересборки видов «Со стороны
// окна» стояло над фото, снятым от двери). `vwPubShotAt`: годен кадр с именем точки `C<k+1>` и той же точкой (`shotCamOk`); иначе null —
// у вида фото нет, как у любого вида без фото. Карточке главной прежнее фото другой точки по-прежнему годно (шаг 2 выше, TG 378)
describe("vwPubShotAt — фото вида в окне только со своей точки", () => {
  const cut = (a: string, b: string) => src.slice(src.indexOf(a), src.indexOf(b));
  const at = src.indexOf("function vwPubShotAt("), fnSrc = src.slice(at, src.indexOf("\n}", at) + 2);
  const vwPubShotAt = new Function(`${src.slice(src.indexOf("const camAng="), src.indexOf("\n", src.indexOf("const camAng=")))};
${cut("// SHOTCAM START", "// SHOTCAM END")};${block};${fnSrc};return vwPubShotAt;`)() as (
    list: Shot[], st: string, vid: string, cs: { name: string; x: number; y: number; rot: number; fov: number }[], k: number) => Shot | null;
  const door = { x: 436, y: 232, rot: -82, fov: 84 }, win = { x: 60, y: 205, rot: 50, fov: 90 }, oldC2 = { x: 409, y: 205, rot: -100, fov: 78 };
  const now = [{ name: "C1", ...door }, { name: "C2", ...win }];
  const shot = (url: string, camera: string, c2: typeof win, o: Partial<Shot> = {}) =>
    ({ ...sh(url, { stateId: "S-now", camera, ...o }), cams: [{ name: "C1", ...door }, { name: "C2", ...c2 }] }) as Shot;
  it("кадр C2 снят с прежней точки (у двери) — у вида «От окна» фото нет; та же точка — есть", () => {
    expect(vwPubShotAt([shot("c2-old", "C2", oldC2)], "S-now", "set1", now, 1)).toBeNull();
    expect(vwPubShotAt([shot("c2-now", "C2", win)], "S-now", "set1", now, 1)?.url).toBe("c2-now");
    // точка C1 у этих кадров та же — C1 годен, хотя у C2 в той же сборке точка сменилась
    expect(vwPubShotAt([shot("c1", "C1", oldC2)], "S-now", "set1", now, 0)?.url).toBe("c1");
  });
  it("чужая точка вместо своей не подставляется: у C2 нет своего кадра — C1 не берём; прежней расстановки той же точки — берём", () => {
    expect(vwPubShotAt([shot("c1", "C1", win)], "S-now", "set1", now, 1)).toBeNull();
    expect(vwPubShotAt([shot("c2-prev", "C2", win, { stateId: "S-old" })], "S-now", "set1", now, 1)?.url).toBe("c2-prev");
    expect(vwPubShotAt([shot("c2-prev-old", "C2", oldC2, { stateId: "S-old" })], "S-now", "set1", now, 1)).toBeNull();
  });
  // ПЕРЕСЪЁМКА (T-20261108-73/3, владелец TG 666): ночь (`tools/ops/demo-realistic.mjs`) снимает пару, если хоть у одного вида нет фото
  // своей точки (`vwRealMissing`). Прежде — только если фото нет ни у одного: C1 на месте, C2 сдвинут — пару не снимали никогда
  const fm = src.indexOf("function vwRealMissing("), vwRealMissing = new Function(`${src.slice(fm, src.indexOf("\n}", fm) + 2)};return vwRealMissing;`)() as
    (have: Shot[], cs: { name?: string }[]) => string[];
  const have = (list: Shot[]) => now.map((_, k) => vwPubShotAt(list, "S-now", "set1", now, k)).filter((x): x is Shot => !!x);
  it("пересъёмка: C1 своей точки, C2 снят с прежней — нужно фото вида C2 (пара в очереди), хотя одно фото у пары есть", () => {
    const part = have([shot("c1", "C1", oldC2), shot("c2-old", "C2", oldC2)]);
    expect(part.map((x) => x.url)).toEqual(["c1"]);
    expect(vwRealMissing(part, now)).toEqual(["C2"]);
    expect(vwRealMissing(have([shot("c1", "C1", win), shot("c2", "C2", win)]), now)).toEqual([]);
    expect(vwRealMissing([], now)).toEqual(["C1", "C2"]);
    expect(vwRealMissing([], [{}, {}])).toEqual(["C1", "C2"]);
  });
  it("ночной отбор пересъёмки — по `vwRealMissing`, не «нет ни одного фото»", () => {
    const night = readFileSync("tools/ops/demo-realistic.mjs", "utf8");
    expect(night).toMatch(/vwRealMissing\(vwRealShots\(\), cams \|\| loadCams\(\)\)/);
    expect(night).toMatch(/const want = force \? [^\n]*: miss\.length > 0;/);
    expect(night).not.toMatch(/: !vwRealShots\(\)\.length;/);
  });
});

describe("страница: главная, вкладки и опрос берут только строгую функцию", () => {
  const fn = (name: string) => { const at = src.indexOf(`function ${name}(`); return src.slice(at, src.indexOf("\nfunction ", at + 10)); };
  it("homeModel (карточки и вкладки) и photoOf (опрос) — realisticPublishedShot, не pubShot", () => {
    expect(fn("homeModel")).toContain("realisticPublishedShot(");
    expect(fn("homeModel")).not.toContain("pubShot(");
    const quiz = src.slice(src.indexOf("function photoOf("), src.indexOf("function photoOf(") + 200);
    expect(quiz).toContain("realisticPublishedShot(");
    expect(quiz).not.toContain("pubShot(");
  });
  it("карточка главной: ни черновика pubShot, ни кадра 3D liveShot", () => {
    const draw = fn("drawHome");
    expect(draw).toContain("realisticPublishedShot(");
    expect(draw).not.toMatch(/pubShot\(|liveShot\(/);
  });
});
