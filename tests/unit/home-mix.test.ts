import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ВЫБРАННЫЙ ИНТЕРЬЕР КВАРТИРЫ (план home-mix-01, T-20261107-35). Чистые функции — блок HOMEMIX страницы демо; тест читает блок из
// страницы, как QUIZPICK в quiz-pick.test.ts. Выбор хранится (`selected` 1–2 стиля, `requested` комната → стиль), показанное — вычисляется.
const SRC = "tools/scout/flat215-demo/index.html";
type Sel = { selected: string[]; requested: Record<string, string> };
type Rv = { styleId: string; roomId: string; variantId: string; index: number };
type Room = { id: string; kind: string };
type Fb = Record<string, Record<string, string[]>>;
type Parsed = { open: "" | "v" | "c"; src: "" | "mix" | "style"; sel: Sel | null; room: string };

const src = readFileSync(SRC, "utf8");
const block = src.slice(src.indexOf("// HOMEMIX START"), src.indexOf("// HOMEMIX END"));
const page = new Function(`${block};return {mixSel,mixEff,mixZone,mixWant,mixShown,mixEncode,mixDecode,mixFromUrl,mixParams};`)() as {
  mixSel: (selected: unknown[], requested: Record<string, unknown>) => Sel;
  mixEff: (sel: Sel | null, ids: string[]) => Sel;
  mixZone: (kind: string) => number;
  mixWant: (sel: Sel, room: Room) => string[];
  mixShown: (rvs: Rv[], fb: Fb, sel: Sel, room: Room) => { rv: Rv | null; want: string };
  mixEncode: (sel: Sel) => string;
  mixDecode: (s: string | null) => Sel | null;
  mixFromUrl: (search: string, hash: string) => Parsed;
  mixParams: (sel: Sel, room: string) => { style: string | null; mix: string | null; room: string };
};

// витрина 07.11: гостиные шести стилей, спальни — пяти (у неоклассики спален нет, карта сборки подставляет похожие), прихожих нет
const STYLES = ["scandi", "modern", "minimal", "loft", "neoclassic", "japandi"];
const RVS: Rv[] = [];
STYLES.forEach((s) => RVS.push({ styleId: s, roomId: "living", variantId: `${s}-living`, index: RVS.length }));
for (const room of ["bedroom-1", "bedroom-2"])
  STYLES.filter((s) => s !== "neoclassic").forEach((s) => RVS.push({ styleId: s, roomId: room, variantId: `${s}-${room}`, index: RVS.length }));
const FB: Fb = {
  "bedroom-1": { neoclassic: ["modern", "japandi", "scandi", "minimal", "loft"] },
  "bedroom-2": { neoclassic: ["modern", "japandi", "scandi", "minimal", "loft"] },
};
const ROOMS: Room[] = [
  { id: "living", kind: "living" }, { id: "kitchen", kind: "kitchen" }, { id: "bedroom-1", kind: "bedroom" },
  { id: "bedroom-2", kind: "bedroom" }, { id: "hall", kind: "hall" },
];
const shown = (sel: Sel) => Object.fromEntries(ROOMS.map((r) => [r.id, page.mixShown(RVS, FB, sel, r).rv?.styleId ?? null]));
const S = (selected: string[], requested: Record<string, string> = {}): Sel => ({ selected, requested });

describe("раскладка по выбору", () => {
  it("один выбранный — все комнаты в нём; без вариантов (кухня, прихожая) — плашка", () => {
    expect(shown(S(["loft"]))).toEqual({ living: "loft", kitchen: null, "bedroom-1": "loft", "bedroom-2": "loft", hall: null });
  });
  it("два выбранных — по зонам: гостиная основной, обе спальни второй", () => {
    expect(shown(S(["scandi", "loft"]))).toMatchObject({ living: "scandi", "bedroom-1": "loft", "bedroom-2": "loft" });
    expect(page.mixZone("living")).toBe(0);
    expect(page.mixZone("hall")).toBe(0);
    expect(page.mixZone("bedroom")).toBe(1);
    expect(page.mixZone("nursery")).toBe(1);
  });
  it("назначенный стиль комнаты (опрос по комнатам) важнее зоны", () => {
    expect(shown(S(["scandi", "loft"], { "bedroom-2": "japandi", living: "modern" }))).toMatchObject({
      living: "modern", "bedroom-1": "loft", "bedroom-2": "japandi",
    });
  });
  it("приоритет: назначенный → стиль зоны → другой выбранный → запасной по карте сборки", () => {
    // второй выбранный — неоклассика, спален у неё нет: спальни берут ДРУГОЙ ВЫБРАННЫЙ (сканди), а не запасной из карты (современный)
    expect(shown(S(["scandi", "neoclassic"]))).toMatchObject({ living: "scandi", "bedroom-1": "scandi", "bedroom-2": "scandi" });
    expect(page.mixWant(S(["scandi", "neoclassic"]), { id: "bedroom-1", kind: "bedroom" })).toEqual(["neoclassic", "scandi"]);
    // запрошено и показано различаются — `want` остаётся запрошенным (менеджеру и `data-style`)
    expect(page.mixShown(RVS, FB, S(["scandi", "neoclassic"]), { id: "bedroom-1", kind: "bedroom" }).want).toBe("neoclassic");
  });
  it("запасной стиль: только неоклассика — спальни молча из карты сборки (первый, у кого вариант есть)", () => {
    expect(shown(S(["neoclassic"]))).toMatchObject({ living: "neoclassic", "bedroom-1": "modern", "bedroom-2": "modern" });
    const noModern = RVS.filter((x) => !(x.styleId === "modern" && x.roomId === "bedroom-1"));
    expect(page.mixShown(noModern, FB, S(["neoclassic"]), { id: "bedroom-1", kind: "bedroom" }).rv?.styleId).toBe("japandi");
  });
  it("вариантов комнаты нет ни у кого — rv null, запрошенный стиль всё равно назван", () => {
    expect(page.mixShown(RVS, FB, S(["scandi"]), { id: "kitchen", kind: "kitchen" })).toEqual({ rv: null, want: "scandi" });
  });
});

describe("выбор: нормализация и стили, которых на главной нет", () => {
  it("mixSel: без повторов, не больше двух, мусор отброшен", () => {
    expect(page.mixSel(["loft", "loft", "Bad!", "scandi", "modern"], { living: "modern", "x y": "loft", hall: 5 }))
      .toEqual(S(["loft", "scandi"], { living: "modern" }));
  });
  it("mixEff: стиль, которого на главной нет (реестр кадров его скрыл), отброшен; пусто — первый стиль вкладок", () => {
    expect(page.mixEff(S(["gothic", "loft"]), STYLES)).toEqual(S(["loft"]));
    expect(page.mixEff(S(["gothic"], { living: "gothic" }), STYLES)).toEqual(S(["scandi"]));
    expect(page.mixEff(null, STYLES)).toEqual(S(["scandi"]));
    expect(page.mixEff(null, [])).toEqual(S([]));
  });
});

describe("ссылки", () => {
  it("старая ?style= — этот стиль во всех комнатах; room сохраняется", () => {
    const p = page.mixFromUrl("?lang=ru&style=loft&room=bedroom-1", "");
    expect(p).toEqual({ open: "", src: "style", sel: S(["loft"]), room: "bedroom-1" });
    expect(shown(p.sel as Sel)).toMatchObject({ living: "loft", "bedroom-1": "loft", "bedroom-2": "loft" });
  });
  it("смесь mix= важнее ?style=; #v/#c открывают окно, но выбор квартиры берётся из параметров", () => {
    const p = page.mixFromUrl("?style=loft&mix=1.scandi.modern.bedroom-2_japandi", "#v=abc");
    expect(p).toEqual({ open: "v", src: "mix", sel: S(["scandi", "modern"], { "bedroom-2": "japandi" }), room: "" });
    expect(page.mixFromUrl("?style=loft", "#c=AAAAAAAAAAAAAAAAAAAAAA")).toMatchObject({ open: "c", src: "style", sel: S(["loft"]) });
  });
  it("без параметров — sel null (опрос или стиль по умолчанию)", () => {
    expect(page.mixFromUrl("", "")).toEqual({ open: "", src: "", sel: null, room: "" });
    expect(page.mixFromUrl("?lang=en&s=AAAAAAAAAAAAAAAAAAAAAA", "#plan")).toMatchObject({ src: "", sel: null });
  });
  it("чужая версия mix= — не наша ссылка, разбор идёт дальше к ?style=", () => {
    expect(page.mixDecode("2.scandi.loft")).toBeNull();
    expect(page.mixFromUrl("?mix=2.scandi&style=modern", "")).toMatchObject({ src: "style", sel: S(["modern"]) });
    expect(page.mixFromUrl("?mix=1", "")).toMatchObject({ src: "", sel: null });
  });
  it("кодирование туда-обратно; незнакомые части будущих версий пропускаются", () => {
    const sel = S(["scandi", "loft"], { living: "modern", "bedroom-1": "japandi" });
    const enc = page.mixEncode(sel);
    expect(enc).toBe("1.scandi.loft.bedroom-1_japandi.living_modern");
    expect(new URLSearchParams({ mix: enc }).toString()).toBe(`mix=${enc}`);   // адрес не кодирует — ссылка читается глазами
    expect(page.mixDecode(enc)).toEqual(sel);
    expect(page.mixDecode("1.scandi.~new~.x=y.loft")).toEqual(S(["scandi", "loft"]));
  });
  it("адрес главной: style= — всегда основной; mix= — только когда выбор шире одного стиля", () => {
    expect(page.mixParams(S(["loft"]), "living")).toEqual({ style: "loft", mix: null, room: "living" });
    expect(page.mixParams(S(["loft", "scandi"]), "")).toEqual({ style: "loft", mix: "1.loft.scandi", room: "living" });
    expect(page.mixParams(S(["loft"], { living: "modern" }), "bedroom-1")).toEqual({ style: "loft", mix: "1.loft.living_modern", room: "bedroom-1" });
  });
});

// ОТКРЫТИЕ КОМНАТЫ НЕ ПЕРЕПИСЫВАЕТ ВЫБОР КВАРТИРЫ (план, порядок работ п.2). Раньше `homeActive`/`drawHome` писали стиль открытого
// окна (`cur`) в `HOME.styleId` и адрес. Теперь выбор пишут только явные действия; стражем — места записи в исходнике страницы
// (поведение на живой странице — снимки Playwright в отчёте T-35).
describe("выбор пишут только явные действия", () => {
  const fnBody = (name: string) => {
    const at = src.indexOf(`function ${name}(`);
    expect(at, name).toBeGreaterThan(0);
    const next = src.indexOf("\nfunction ", at + 10);
    return src.slice(at, next);
  };
  it("HOME.sel присваивается только в homeSetSel и при разборе адреса на входе", () => {
    const writes = [...src.matchAll(/HOME\.sel\s*=(?!=)/g)].map((m) => m.index ?? 0);
    expect(writes.length).toBe(2);
    expect(fnBody("homeSetSel")).toMatch(/HOME\.sel\s*=(?!=)/);
    expect(src.slice(writes[0] - 900, writes[0])).toContain("ВЫБОР КВАРТИРЫ ИЗ АДРЕСА");
  });
  it("HOME.styleId — только зеркало выбора (homeSel), окно и отрисовка его не пишут", () => {
    const writes = [...src.matchAll(/HOME\.styleId\s*=(?!=)/g)];
    expect(writes.length).toBe(1);
    expect(fnBody("homeSel")).toMatch(/HOME\.styleId\s*=/);
    for (const f of ["drawHome", "applyHash", "pickVariant", "vwOpenVariant", "flatPlan"]) expect(fnBody(f), f).not.toMatch(/HOME\.(sel|styleId)\s*=(?!=)/);
    expect(src).not.toMatch(/function homeActive\(/);
  });
});
