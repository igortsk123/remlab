import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ПЕРЕКЛЮЧАТЕЛЬ «ФОТО | 3D» ВИДЕН ВСЕГДА (T-20261113-16, владелец TG 1516/1519; П1.53). Раньше в /demo «Фото» без снимка этой расстановки
// пряталось вместе со всем переключателем: сменил стиль комнаты на тот, где фото нет (гостиная × неоклассика), и кнопок «Фото» и «3D» не
// стало, пока фото не появится. Теперь правило одно для /demo и тура: переключатель на месте, «Фото» без снимка — карточка «Фото этой
// расстановки ещё нет» с «Сделать фото» (в туре без права на фото — как его получить, TG 930). Функции берём со страницы демо (блок от
// «ПЕРЕКЛЮЧЕНИЕ РЕЖИМА» до `vwRealShots`), окружение — заглушки
const html = readFileSync(process.env.DEMO_HTML ?? "tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// ПЕРЕКЛЮЧЕНИЕ РЕЖИМА МЕНЯЕТ ТОЛЬКО ОБЛАСТЬ СЦЕНЫ"), html.indexOf("function vwRealShots(){"));

type El = { hidden: boolean; dataset: Record<string, string>; className: string; innerHTML: string; onclick: null | (() => void);
  remove: () => void; querySelector: (s: string) => El | null };
function el(data: Record<string, string> = {}): El {
  const e: El = { hidden: false, dataset: { ...data }, className: "", innerHTML: "", onclick: null, remove: () => {},
    querySelector: (s: string) => {
      if (s !== "button") return null;
      const m = /data-trph="(\w+)"/.exec(e.innerHTML);
      return m?.[1] ? el({ trph: m[1] }) : null;
    } };
  return e;
}

type Env = { trial: boolean; shots: number; agentKey?: string; photoOk?: boolean };
function load(env: Env) {
  const ph = el({ vm: "photo" }), walk = el({ vm: "walk" }), vm = el();
  ph.hidden = walk.hidden = vm.hidden = false;
  let card: El | null = null;
  const wrap = { querySelector: () => card, appendChild: (x: El) => { card = x; x.remove = () => { card = null; }; } };
  const shot = {
    classList: { toggle: () => {}, contains: () => true },
    querySelector: (s: string) => (s === '[data-vm="photo"]' ? ph : s === ".vmodes" ? vm : null),
    querySelectorAll: () => [ph, walk].map((x) => ({ ...x, classList: { toggle: () => {} } })),
  };
  const doc = {
    getElementById: (id: string) => (id === "shot" ? shot : null),
    querySelector: (s: string) => (s === "#shot .shotwrap" ? wrap : null),
    createElement: () => el(),
  };
  const VW: Record<string, unknown> = { mode: "walk" };
  const noop = () => {};
  const api = new Function(
    "document", "VW", "VJ", "LANG", "TRIAL", "TR_EN", "trPhotoHere", "trKey", "CTA_REAL", "CTA_REAL_EN", "vwPhotoShots", "vwJobHere",
    "VW_PHONE", "requestAnimationFrame", "vwLayout", "vwCtaUi", "vwCamsUi", "vwPhWaitUi", "vwStaleUi", "vwPlanDraw", "e2Head", "vwCamN",
    "vwPhotoShow", "liveHide", "vwRealistic", "trGoPlan",
    `${block};return {vwModeUi, vwMode, trPhotoStubUi};`,
  )(
    doc, VW, { job: null }, "ru", () => env.trial, () => false, () => !!env.photoOk, () => env.agentKey ?? "", "Сделать фото", "Take photo",
    () => Array(env.shots).fill({ camera: "C1" }), () => false,
    () => false, noop, noop, noop, noop, noop, noop, noop, noop, () => 2,
    () => { if (VW.mode === "photo" && !env.shots) api.trPhotoStubUi(); }, noop, noop, noop,
  ) as { vwModeUi: () => void; vwMode: (m: string) => void; trPhotoStubUi: () => void };
  return { api, VW, ph, vm, card: () => card };
}

describe("переключатель «Фото | 3D» — всегда, и в /demo, и в туре", () => {
  it("/demo, у расстановки нет фото (сменили стиль на неоклассику): переключатель и «Фото» видны", () => {
    const t = load({ trial: false, shots: 0 });
    t.api.vwModeUi();
    expect(t.vm.hidden).toBe(false);
    expect(t.ph.hidden).toBe(false);
  });
  it("/demo, фото нет: «Фото» открывается — карточка «Фото этой расстановки ещё нет» и «Сделать фото»", () => {
    const t = load({ trial: false, shots: 0 });
    t.api.vwMode("photo");
    expect(t.VW.mode).toBe("photo");
    const c = t.card();
    expect(c?.innerHTML).toContain("Фото этой расстановки ещё нет");
    expect(c?.innerHTML).toContain('data-trph="shot"');
    expect(c?.innerHTML).toContain("Сделать фото");
  });
  it("/demo, фото есть: переключатель виден, карточки нет", () => {
    const t = load({ trial: false, shots: 2 });
    t.api.vwMode("photo");
    expect(t.vm.hidden).toBe(false);
    expect(t.card()).toBeNull();
  });
  it("тур без права на фото у агента — как раньше: «подтвердите планировку» и переход к ней", () => {
    const t = load({ trial: true, shots: 0, agentKey: "K".repeat(22), photoOk: false });
    t.api.vwMode("photo");
    expect(t.vm.hidden).toBe(false);
    expect(t.card()?.innerHTML).toContain('data-trph="plan"');
  });
});
