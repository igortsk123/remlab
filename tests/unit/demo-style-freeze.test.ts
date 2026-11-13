import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// СМЕНА СТИЛЯ НЕ ВЕШАЕТ СТРАНИЦУ (T-20261113-16, владелец 08:55 голосом: «при переключении стиля он зависает»). Замер на живом /demo
// (375, CPU ×4, 3D включён): окно выбора закрывалось через 1,0–1,3 с, а через 1,5–5 с после тапа съёмка «кадров заранее» строила 3D и
// снимала два кадра 1536×1117 — задачи по 1,3–3,8 с, хотя в «Фото» сцену не видно. Функции берём со страницы демо, окружение — заглушки
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const cut = (from: string, to: string) => {
  const a = html.indexOf(from), b = html.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`нет блока ${from}`);
  return html.slice(a, b);
};

describe("кадры заранее: не в «Фото»", () => {
  const block = cut("function vwPreOk(){", "function vwPreFresh(");
  const ok = (mode: string) => new Function("VW", "TRIAL", "trPhotoHere", "document", "LIVE", "liveSoftGL", "D", "items", "navigator", "liveHere",
    `${block};return vwPreOk();`)(
    { mode }, () => false, () => true,
    { hidden: false, getElementById: () => ({ classList: { contains: () => true } }) },
    { ok: true, state: "ready", force: false }, () => false, {}, [], {}, () => null,
  ) as boolean;
  it("«Фото» — нет: сцену там не видно, «Сделать фото» снимет по нажатию", () => expect(ok("photo")).toBe(false));
  it("«3D» — да, как раньше", () => expect(ok("walk")).toBe(true));
});

describe("кадры заранее в 3D: только после 3 с без касаний", () => {
  const block = cut("const VPF_QUIET_MS", "function vwPreKey(");
  function load() {
    const on: Record<string, () => void> = {}, clock = { t: 10_000 };
    let soon = 0;
    const api = new Function("document", "performance", "vwPreSoon", `${block};return {VPF, vwPreTouched, VPF_QUIET_MS};`)(
      { addEventListener: (t: string, f: () => void) => { on[t] = f; } }, { now: () => clock.t }, () => { soon++; },
    ) as { VPF: { t: number; touch: number }; vwPreTouched: () => boolean; VPF_QUIET_MS: number };
    return { api, on, clock, soon: () => soon };
  }
  it("тишина — 3 с; касание, колесо и клавиша — слушаются", () => {
    const t = load();
    expect(t.api.VPF_QUIET_MS).toBe(3000);
    expect(Object.keys(t.on).sort()).toEqual(["keydown", "pointerdown", "touchstart", "wheel"]);
  });
  it("после касания 3 с съёмка считается «тронутой», потом — нет", () => {
    const t = load();
    t.on.touchstart?.();
    t.clock.t += 2999; expect(t.api.vwPreTouched()).toBe(true);
    t.clock.t += 2; expect(t.api.vwPreTouched()).toBe(false);
  });
  it("касание при ждущей съёмке переставляет её отсчёт; без ждущей — ничего не запускает", () => {
    const t = load();
    t.on.pointerdown?.(); expect(t.soon()).toBe(0);
    t.api.VPF.t = 7; t.on.pointerdown?.(); expect(t.soon()).toBe(1);
  });
});

describe("по одному кадру за задачу", () => {
  const block = cut("async function vwCapturePoses(", "async function vwUploadViews(");
  function load() {
    const calls: unknown[][] = [];
    const LIVE = { scene: { capture: async (poses: unknown[]) => { calls.push(poses); return { frames: [`f${calls.length}`], clay: ["стул"] }; } } };
    const fn = new Function("LIVE", `${block};return vwCapturePoses;`)(LIVE) as
      (p: unknown[], w: number, h: number, o: { touched?: () => boolean; stale?: () => boolean }) => Promise<{ frames: string[]; clay: string[] } | null>;
    return { fn, calls };
  }
  it("два ракурса — два вызова по одному ракурсу, кадры вместе, как у одного вызова", async () => {
    const t = load();
    const r = await t.fn(["C1", "C2"], 1536, 1117, {});
    expect(t.calls).toEqual([["C1"], ["C2"]]);
    expect(r).toEqual({ frames: ["f1", "f2"], clay: ["стул"] });
  });
  it("заранее: человек тронул страницу после первого кадра — второй не снимаем", async () => {
    const t = load();
    let touched = false;
    const p = t.fn(["C1", "C2"], 1536, 1117, { touched: () => touched });
    touched = true;
    expect(await p).toBeNull();
    expect(t.calls).toEqual([["C1"]]);
  });
});
