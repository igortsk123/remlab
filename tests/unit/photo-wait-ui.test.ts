import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ХОД ЗАКАЗА ФОТО НА СТРАНИЦЕ (T-20261118-20/14/1, владелец 18.11, TG 1892–1941): «Создание фото…» / «Улучшение фото…», под ней убывающий срок «≈N с»
// (от eta сервера; за оценкой — «Ещё немного…», в минус не уходит), тонкая полоса; процентов нет; кнопка «Сделать фото» только блокируется, надпись та же;
// строки хода рядом с кнопкой в нижней панели нет; та же функция `jobProg` кормит окно и карточку комнаты. Функции читаются из страницы, как в real-shot.test.ts.
const SRC = "tools/scout/flat215-demo/index.html";
const src = readFileSync(SRC, "utf8");
const cut = (from: string, to: string) => src.slice(src.indexOf(from), src.indexOf(to, src.indexOf(from)));

type Prog = { pct: number; left: number; text: string; note: string; warm?: boolean };
const mk = (lang: "ru" | "en", t: number) => {
  const now = { t };
  const api = new Function(
    "LANG",
    "now",
    `const Date={now:()=>now.t};
     ${cut("const PHOTO_EST_S=", "// ПЛАШКА ОЖИДАНИЯ ФОТО")}
     ${cut("// ХОД — В ПРОЦЕНТАХ", "function photoWaitHtml(")}
     return {jobProg, jobCardProg, waitLeftText};`,
  )(lang, now) as { jobProg: (j: unknown) => Prog; jobCardProg: (j: unknown) => Prog; waitLeftText: (n: number) => string };
  return { api, now };
};

describe("ход на карточке комнаты: без процентов, с убывающим сроком", () => {
  it("рендер: «Создание фото…», срок убывает от eta сервера, полоса растёт и не откатывается", () => {
    const { api, now } = mk("ru", 100_000);
    const job = { kind: "render", t0: 100_000, eta: 20, etaAt: 100_000, est: 25, pct: 0, queue: 0 };
    const a = api.jobCardProg(job);
    expect(a.text).toBe("Создание фото…");
    expect(a.note).toBe("≈20 с");
    now.t += 10_000;
    const b = api.jobCardProg(job);
    expect(b.note).toBe("≈10 с");
    expect(b.pct).toBeGreaterThan(a.pct);
    expect(`${a.text}${a.note}`).not.toMatch(/%/);
    now.t += 30_000;                                  // за оценкой — «Ещё немного…», не «≈-10 с»
    const c = api.jobCardProg(job);
    expect(c.note).toBe("Ещё немного…");
    expect(c.pct).toBeGreaterThanOrEqual(b.pct);
    expect(c.pct).toBeLessThanOrEqual(99);
    now.t += 5_000;
    expect(api.jobCardProg(job).pct).toBeGreaterThanOrEqual(c.pct);   // назад не идёт
  });

  it("EN: «Creating photo…» / «≈N s» / «Almost there…»; улучшение — «Enhancing photo…»", () => {
    const { api, now } = mk("en", 100_000);
    const job = { kind: "render", t0: 100_000, eta: 5, etaAt: 100_000, est: 25, queue: 0 };
    expect(api.jobCardProg(job).text).toBe("Creating photo…");
    expect(api.jobCardProg(job).note).toBe("≈5 s");
    now.t += 9_000;
    expect(api.jobCardProg(job).note).toBe("Almost there…");
    const imp = api.jobCardProg({ kind: "improve", t0: now.t });
    expect(imp.text).toBe("Enhancing photo…");
    expect(imp.note).toMatch(/^≈\d+ s$/);
  });

  it("минуты — от 90 с; прогрев — текст сервера + полоса по сроку прогрева, без процентов", () => {
    const { api, now } = mk("ru", 100_000);
    expect(api.waitLeftText(120)).toBe("≈2 мин");
    expect(api.waitLeftText(45)).toBe("≈45 с");
    const text = "Первое создание снимка займёт ≈3 мин, далее ≈25 сек. Подождите, пожалуйста.";
    const job = { kind: "render", t0: 100_000, mach: { state: "warming", text, text_en: "x", eta_s: 180 }, machAt: 100_000, queue: 0 };
    const a = api.jobCardProg(job);
    expect(a.text).toBe(text);
    expect(a.pct).toBe(0);
    now.t += 90_000;
    const b = api.jobCardProg(job);
    expect(b.pct).toBeGreaterThan(40);
    expect(b.pct).toBeLessThan(60);
  });

  it("запасной путь: вместо отсчёта — текст сервера «Снимок будет готов через ≈N мин…»", () => {
    const { api } = mk("ru", 100_000);
    const t = "Снимок будет готов через ≈2 мин. Подождите, пожалуйста.";
    const p = api.jobCardProg({ kind: "render", t0: 100_000, eta: 100, etaAt: 100_000, est: 100, mach: { state: "fallback", text: t, text_en: "x" }, queue: 0 });
    expect(p.note).toBe(t);
  });
});

describe("ход по центру окна — прежний (владелец TG 1960: «зачем менять, не нужно»)", () => {
  it("jobProg: «Делаю фото · N %» + «Обычно около N с»; улучшение — «Улучшаю · N %»", () => {
    const { api } = mk("ru", 100_000);
    const r = api.jobProg({ kind: "render", t0: 100_000, eta: 18, eta0: 25, est: 25, pct: 37, queue: 0 });
    expect(r.text).toBe("Делаю фото · 37 %");
    expect(r.note).toBe("Обычно около 25 с");
    expect(api.jobProg({ kind: "improve", t0: 100_000 }).text).toMatch(/^Улучшаю · \d+ %$/);
    const en = mk("en", 100_000).api;
    expect(en.jobProg({ kind: "render", t0: 100_000, eta0: 25, est: 25, pct: 37, queue: 0 }).text).toBe("Rendering · 37 %");
  });
});

describe("кнопка и карточка комнаты — исходник страницы", () => {
  const cta = src.slice(src.indexOf("function vwCtaUi(){"), src.indexOf("function vwCtaUi(){") + 6000);

  it("кнопка при заказе только блокируется (disabled + .vwait), без процентов и полосы на ней; строки хода рядом нет", () => {
    expect(cta).toContain("cta.disabled=rj; cta.classList.toggle('vwait',rj)");
    expect(cta).toContain("const pn=rj?''");
    expect(src).toContain(".vcta.vwait,.vcta[disabled]{opacity:.5;cursor:default;pointer-events:none}");
  });

  it("карточка комнаты: ход из того же jobProg, кнопки disabled, «Вы изменили комнату» над кнопками на всех ширинах", () => {
    expect(src).toContain("jobCardProg(VJ.job):null;");
    expect(src).toContain("<div class=\"hm-bar\">");
    expect(src).toContain("data-hst=\"real\"${c.wait?' disabled':''}");
    expect(src).not.toMatch(/@media\(min-width:1000px\)\{\.hm-room \.hm-stale\{flex-direction:row/);
  });

  it("затемнение карточки «изменено» — вариант Б (.45 + обесцвечивание), без флага", () => {
    expect(src).toContain(".hm-room .hm-ph.stale::after{content:'';position:absolute;inset:0;background:rgba(38,30,24,.45)");
    expect(src).toContain(".hm-room .hm-ph.stale img{filter:grayscale(.75) saturate(.6)}");
    expect(src).not.toContain('data-stale="B"');
  });

  it("другой вариант витрины открывается со своей отделкой, не с чужой (ложное «изменено»)", () => {
    const pick = src.slice(src.indexOf("function pickVariant(i){"), src.indexOf("function showSwap(drawn)"));
    expect(pick).toContain("editShelf(nv)");
    expect(pick).toContain("nv.dev");
    expect(pick).toContain("DEVOPT=d");
  });
});

// ЖИВОЙ ДЕФЕКТ ВЛАДЕЛЬЦА (TG 1964): готовый заказ правленой комнаты не снимал «Вы изменили комнату», после перезагрузки терялся. Одно место решает «это фото комнаты» (`isPhotoShot`);
// заказ запоминается (`orderKeep`) и подхватывается при запуске (`ordersResume`); срок хранения — одна константа.
describe("фото комнаты — одно место; заказ переживает перезагрузку", () => {
  const photo = new Function(`${cut("function isPhotoShot(", "function bestShot(")}; return {isPhotoShot, photoPool};`)() as {
    isPhotoShot: (x: unknown) => boolean; photoPool: (l: { quality: string; n?: number }[]) => { quality: string; n?: number }[];
  };

  it("isPhotoShot: рендер и улучшенное — фото, черновик 3D и пусто — нет", () => {
    expect(photo.isPhotoShot({ quality: "render" })).toBe(true);
    expect(photo.isPhotoShot({ quality: "realistic" })).toBe(true);
    expect(photo.isPhotoShot({ quality: "draft" })).toBe(false);
    expect(photo.isPhotoShot(null)).toBe(false);
  });

  it("photoPool: улучшенное перекрывает рендер, рендер — всё прочее", () => {
    const l = [{ quality: "draft" }, { quality: "render", n: 1 }, { quality: "realistic", n: 2 }];
    expect(photo.photoPool(l)).toEqual([{ quality: "realistic", n: 2 }]);
    expect(photo.photoPool(l.slice(0, 2))).toEqual([{ quality: "render", n: 1 }]);
    expect(photo.photoPool([{ quality: "draft" }])).toEqual([{ quality: "draft" }]);
  });

  it("ни одно место карточек/окна не сверяет `quality===\'realistic\'` само — только isPhotoShot", () => {
    const own = src.match(/own=isPhotoShot\(bs\)/g) || [];
    expect(own.length).toBe(1);
    expect(src).not.toMatch(/bs&&bs\.quality==='realistic'/);
    expect(src).not.toMatch(/p&&p\.quality==='realistic'/);
  });

  it("заказ: запись при принятии сервером, стирание по готовности и ошибке, подхват при запуске; check и для правленой", () => {
    expect(src).toContain("job.jobId=j.job; if(!resumeId)orderKeep(job);");
    expect((src.match(/orderDrop\(job\.jobId\)/g) || []).length).toBe(2);
    expect(src).toContain("setTimeout(()=>{try{ordersResume();}catch(e){}},0);");
    expect(src).toContain("const ORDER_KEY='flat215-orders', ORDER_KEEP_S=6*3600;");
    expect(src).not.toContain("if(st!==pubStateOf(v)||vwRealShots().length)return;");
  });

  it("orderKeep/orderDrop: запись по номеру задания; старше срока — вычищается", () => {
    const store: Record<string, string> = {};
    const api = new Function(
      "localStorage", "TRIAL", "trJobId", "Date",
      `${cut("const ORDER_KEY=", "async function ordersResume(")}; return {orderKeep, orderDrop, ordersAll, ORDER_KEEP_S};`,
    )(
      { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } },
      () => false, () => "", { now: () => 10_000_000_000 },
    ) as { orderKeep: (j: unknown) => void; orderDrop: (id: string) => void; ordersAll: () => Record<string, { stateId: string; vid: string }>; ORDER_KEEP_S: number };
    api.orderKeep({ jobId: "OLD", vid: "set1", stateId: "s", t0: 10_000_000_000 - (api.ORDER_KEEP_S + 5) * 1000 });
    api.orderKeep({ jobId: "J1", vid: "set1", stateId: "s1-abc", t0: 10_000_000_000 - 1000 });
    expect(Object.keys(api.ordersAll())).toEqual(["J1"]);          // старый вычищен
    expect(api.ordersAll().J1).toMatchObject({ vid: "set1", stateId: "s1-abc" });
    api.orderDrop("J1");
    expect(api.ordersAll()).toEqual({});
  });
});
