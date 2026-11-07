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
  it("точка не совпадает с нынешней (ракурс пересчитан) — кадр не годится ни на шаге 1, ни на шаге 2", () => {
    expect(pick([sh("now-bad", { stateId: "S-now", bad: true }), sh("old-bad", { stateId: "S-old", bad: true })])).toBeNull();
  });
  it("кадр без адреса или без номера состояния на шаге 1 не считается кадром этой расстановки", () => {
    expect(pick([sh("", { stateId: "S-now" })])).toBeNull();
    expect(pick([sh("nostate", { stateId: "" , vid: "set6" })])).toBeNull();
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
