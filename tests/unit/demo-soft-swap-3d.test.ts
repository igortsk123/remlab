import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ЗАМЕНА ТКАНИ ОСТАЁТСЯ В 3D (T-20261113-24, владелец TG 1629: «подушку Удина заменяю на другую — подушка вообще исчезает»;
// TG 1623: что в списке — видно в 3D). `tryOn` страницы для строки декора с местом (подушка, плед, шторы) берёт цвет и модель
// НОВОГО товара из ленты (`textile_abstract.annotate_feeds`); раньше менялся только `sku`, `look.of` оставался от прежнего —
// `isCloth3d` → false, строка выпадала из `liveDecor`, сцена убирала вещь. Функции — прямо из страницы.
const html = readFileSync(process.env.DEMO_HTML ?? "tools/scout/flat215-demo/index.html", "utf8");   // DEMO_HTML — проверка на прежней странице
const rules = html.slice(html.indexOf("const SOFT_DEF="), html.indexOf("// КАРТИНА (viz-decor-01"));
const tryOnSrc = html.slice(html.indexOf("function tryOn(p){"), html.indexOf("\nfunction ", html.indexOf("function tryOn(p){") + 10));

type Row = { role: string; strategy?: string; place?: Record<string, unknown>; look?: Record<string, unknown>; sku: Record<string, unknown> };
type Feed = Record<string, unknown>;
interface Page {
  tryOn: (p: Feed) => unknown;
  in3dDecor: (x: Row) => boolean;
  isClothAbstract: (x: Row) => boolean;
  toasts: string[];
}
const page = (decor: Row[], selDec: number): Page =>
  new Function(
    "decor",
    "selDec",
    `const D={rules:{}}; const toasts=[];
     ${rules}
     let cur=0, items=[], TRY_LAST=null;
     const V=[{decor}];
     const allVariants=()=>V, vwEditLock=()=>false, basket=()=>{}, showSwap=()=>{}, refreshShotList=()=>{};
     const toastErr=t=>toasts.push('err:'+t), softSwapToast=()=>toasts.push('soft');
     const decorSel=i=>{const x=decor[i]||{}; return {role:x.role, dec:i, sku:x.sku||{}};};
     let sel=decorSel(selDec);
     ${tryOnSrc}
     return {tryOn, in3dDecor, isClothAbstract, toasts};`,
  )(decor, selDec) as Page;

const udina = (): Row => ({
  role: "подушка 2",
  strategy: "textile_abstract",
  place: { x: 108, y: 289, rot: 180, elev_cm: 45, slot_instance_id: "soft.pillows#1", parent: "seating.sofa#0", kind: "pillow", w: 45, d: 12, h: 45 },
  look: { hex: "#9a9c9e", from: "name:сер", sheer: false, of: "112923_3705291971722056715" },
  sku: { name: "Подушка divan.ru Удина Рогожка Серый 45x45", sid: "112923_3705291971722056715", msid: null, price: 990 },
});
const homelines: Feed = {
  name: "Подушка декоративная Homelines textiles double зеленый 45х45 см", sid: "99272_3056323142846323720", msid: null, price: 1290, w: 45, d: 45, h: 11,
  look: { hex: "#6f8a63", from: "name:зелен", sheer: false, of: "99272_3056323142846323720" },
  pillow: { msid: null, w: 45, d: 11, h: 45 },
};

describe("замена подушки, пледа, штор — вещь остаётся в 3D", () => {
  it("подушка Удина → Homelines: строка в 3D, цвет и размер нового товара, место прежнее, без подсказки «Сделать фото»", () => {
    const d = udina();
    const pg = page([d], 0);
    expect(pg.in3dDecor(d)).toBe(true);
    pg.tryOn(homelines);
    expect(d.sku.name).toBe(homelines.name);
    expect(pg.in3dDecor(d)).toBe(true);   // раньше — false: подушка исчезала
    expect(d.look).toMatchObject({ hex: "#6f8a63", of: "99272_3056323142846323720" });
    expect(d.place).toMatchObject({ x: 108, y: 289, elev_cm: 45, parent: "seating.sofa#0", w: 45, d: 11, h: 45 });
    expect(pg.isClothAbstract(d)).toBe(true);   // модели нет — условная подушка цветом товара
    expect(pg.toasts).not.toContain("soft");
  });

  it("модель подушки — только проверенная сборкой (`pillow.msid`), не артикул из ленты", () => {
    const d = udina();
    page([d], 0).tryOn({ ...homelines, msid: "feed_m" });
    expect(d.sku.msid).toBeNull();
    const d2 = udina();
    page([d2], 0).tryOn({ ...homelines, pillow: { msid: "99272_ok", w: 44, d: 13, h: 44 } });
    expect(d2.sku.msid).toBe("99272_ok");
    expect(d2.place).toMatchObject({ w: 44, d: 13, h: 44 });
  });

  it("плед и шторы — тем же правилом: цвет нового товара, место прежнее", () => {
    const throwRow: Row = { role: "плед", strategy: "textile_abstract", place: { x: 50, y: 60, elev_cm: 60, kind: "throw", w: 36, d: 55, h: 5 },
      look: { hex: "#d8c4a6", of: "t_old" }, sku: { name: "Плед бежевый", sid: "t_old" } };
    const pg = page([throwRow], 0);
    pg.tryOn({ name: "Плед Ваби синий", sid: "t_new", price: 2000, look: { hex: "#3d5a8a", from: "name:син", sheer: false, of: "t_new" } });
    expect(pg.in3dDecor(throwRow)).toBe(true);
    expect(throwRow.place).toMatchObject({ x: 50, y: 60, w: 36 });
  });

  it("старые данные (у товара ленты нет цвета) — как раньше: строка только в списке и подсказка «Сделать фото»", () => {
    const d = udina();
    const pg = page([d], 0);
    const bare: Feed = { ...homelines };
    delete bare.look;
    delete bare.pillow;
    pg.tryOn(bare);
    expect(pg.in3dDecor(d)).toBe(false);
    expect(pg.toasts).toContain("soft");
  });
});
