import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// «ПОДТВЕРДИТЬ ПЛАНИРОВКУ» НА СТРАНИЦЕ ТУРА (план trial-confirm-plan-01, часть 2; T-20261111-19/4). Чистые функции берём прямо из
// страницы (блок TCF PURE): повтор запросов при 502 и обрыве связи, ход пересчёта из `rebuild-status`, таймеры, галочки по умолчанию.
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// TCF PURE START"), html.indexOf("// TCF PURE END"));
type Resp = { status: number } | null;
type Model = { st: string; err?: string; done?: number; total?: number; eta?: number | null; el?: number; queued?: boolean;
  rooms?: Record<string, { st: string; eta: number | null }> };
const api = new Function(`${block};return {tcfRetry,TCF_WAIT,tcfClock,tcfLeft,tcfEtaTxt,tcfPlural,tcfArea,tcfDraftName,tcfDefaultOk,tcfModel};`)() as {
  tcfRetry: (go: () => Promise<Resp>, wait: (ms: number) => Promise<void>, say?: (n: number) => void) => Promise<Resp>;
  TCF_WAIT: number[];
  tcfClock: (s: number) => string;
  tcfLeft: (eta: number | null, el: number, sinceMs: number) => number | null;
  tcfEtaTxt: (left: number | null, en: boolean) => string;
  tcfPlural: (n: number, en: boolean) => string;
  tcfArea: (a0: number, w0: number, d0: number, w: number, d: number) => number;
  tcfDraftName: (name: unknown, plan: unknown) => string;
  tcfDefaultOk: (draft: unknown, was: boolean, scale: string) => boolean;
  tcfModel: (j: unknown, ver: number, was: boolean) => Model;
};

describe("повтор запроса (502 после выкладки, обрыв связи)", () => {
  const run = async (answers: (Resp | "throw")[]) => {
    const waits: number[] = [], says: number[] = [];
    let calls = 0;
    const r = await api.tcfRetry(async () => {
      const a = answers[Math.min(calls++, answers.length - 1)];
      if (a === "throw") throw new Error("net");
      return a ?? null;
    }, async (ms) => { waits.push(ms); }, (n) => says.push(n));
    return { r, calls, waits, says };
  };
  it("паузы 2–4–8 с, до 5 повторов", () => expect(api.TCF_WAIT).toEqual([2000, 4000, 8000, 8000, 8000]));
  it("ответ сразу — без пауз", async () => {
    const x = await run([{ status: 200 }]);
    expect(x.calls).toBe(1); expect(x.waits).toEqual([]); expect(x.r).toEqual({ status: 200 });
  });
  it("502 дважды, потом ответ — две паузы и «Сохраняю…» дважды", async () => {
    const x = await run([{ status: 502 }, "throw", { status: 200 }]);
    expect(x.calls).toBe(3); expect(x.waits).toEqual([2000, 4000]); expect(x.says).toEqual([1, 2]); expect(x.r).toEqual({ status: 200 });
  });
  it("ошибка по делу (409, 429) не повторяется", async () => {
    for (const s of [409, 429, 403, 422]) { const x = await run([{ status: s }]); expect(x.calls).toBe(1); expect(x.r).toEqual({ status: s }); }
  });
  it("связи нет совсем — 6 попыток, затем пусто (страница скажет «Нет связи»)", async () => {
    const x = await run(["throw"]);
    expect(x.calls).toBe(6); expect(x.waits).toEqual([2000, 4000, 8000, 8000, 8000]); expect(x.r).toBeNull();
  });
  it("503 до конца — отдаётся последний ответ", async () => {
    const x = await run([{ status: 503 }]);
    expect(x.calls).toBe(6); expect(x.r).toEqual({ status: 503 });
  });
});

describe("ход пересчёта из rebuild-status", () => {
  const st = (rebuild: unknown, version = 5) => ({ ok: true, version, rebuild });
  const run = { id: "r1", kind: "edit", status: "running", error: null, elapsedS: 20, done: 1, total: 2, etaS: 120,
    rooms: { living: "ready", "bedroom-1": "building" }, roomEtaS: { living: 75, "bedroom-1": 135 } };
  it("идёт: N из M, оценка, комнаты с их оценкой", () => {
    expect(api.tcfModel(st(run), 5, false)).toEqual({ st: "run", queued: false, done: 1, total: 2, eta: 120, el: 20,
      rooms: { living: { st: "ready", eta: 75 }, "bedroom-1": { st: "building", eta: 135 } } });
  });
  it("в очереди, без оценки (правка старой страницы) — ход без чисел", () => {
    const m = api.tcfModel(st({ kind: "edit", status: "queued", elapsedS: 0 }), 5, false);
    expect(m).toMatchObject({ st: "run", queued: true, total: 0, eta: null, rooms: {} });
  });
  it("не правки (Обустроить, текст размеров) и нет пересборок — показывать нечего", () => {
    expect(api.tcfModel(st({ ...run, kind: "furnish" }), 5, true).st).toBe("idle");
    expect(api.tcfModel(st(null), 5, true).st).toBe("idle");
    expect(api.tcfModel(null, 5, true).st).toBe("idle");
  });
  it("готово: тому, кто ждал, или если версия новее показанной", () => {
    const done = { ...run, status: "done" };
    expect(api.tcfModel(st(done, 6), 6, true).st).toBe("done");
    expect(api.tcfModel(st(done, 7), 6, false).st).toBe("done");
    expect(api.tcfModel(st(done, 6), 6, false).st).toBe("idle");
  });
  it("не получилось — только тому, кто запускал", () => {
    const f = { ...run, status: "failed", error: "edit_failed" };
    expect(api.tcfModel(st(f), 5, true)).toEqual({ st: "fail", err: "edit_failed" });
    expect(api.tcfModel(st(f), 5, false).st).toBe("idle");
  });
});

describe("таймеры и подписи", () => {
  it("обратный отсчёт: оценка − прошло по серверу − прошло с ответа", () => {
    expect(api.tcfLeft(120, 20, 5000)).toBe(95);
    expect(api.tcfLeft(null, 20, 0)).toBeNull();
  });
  it("«≈ 1:35», в минус не уходит — «ещё немного»", () => {
    expect(api.tcfEtaTxt(95, false)).toBe("≈ 1:35");
    expect(api.tcfEtaTxt(9.6, false)).toBe("≈ 0:10");
    expect(api.tcfEtaTxt(0, false)).toBe("ещё немного");
    expect(api.tcfEtaTxt(-30, true)).toBe("almost there");
    expect(api.tcfEtaTxt(null, false)).toBe("");
    expect(api.tcfClock(-5)).toBe("0:00");
  });
  it("правка / правки / правок", () => {
    expect([1, 2, 5, 11, 21, 22, 25].map((n) => api.tcfPlural(n, false))).toEqual(["правка", "правки", "правок", "правок", "правка", "правки", "правок"]);
    expect(api.tcfPlural(1, true)).toBe("edit");
    expect(api.tcfPlural(3, true)).toBe("edits");
  });
  it("площадь черновика — пропорцией от построенной", () => {
    expect(api.tcfArea(12, 400, 300, 440, 300)).toBeCloseTo(13.2, 6);
    expect(api.tcfArea(12, 400, 300, 0, 300)).toBe(12);
  });
  it("площадь в окне правки — той же tcfArea, что и после пересчёта (T-20261112-28: 14,9 → 16,2, а не 12,3)", () => {
    expect(html).toContain("const areaOf=(w,l)=>tcfArea(A0,W0,L0,w,l);");
    expect(Math.round(api.tcfArea(14.9, 328.4, 364.4, 358, 364) * 100) / 100).toBe(16.23);   // = room_edits._scaled
  });
  it("имя черновика: не меняли — пусто (страница покажет своё «Спальня 1», не «Bedroom 1» с листа), сменили — как ввели", () => {
    expect(api.tcfDraftName("Bedroom 1", "Bedroom 1")).toBe("");
    expect(api.tcfDraftName(" Bedroom 1 ", "Bedroom 1")).toBe("");
    expect(api.tcfDraftName("Кабинет", "Bedroom 1")).toBe("Кабинет");
    expect(api.tcfDraftName("", "Bedroom 1")).toBe("");
    expect(api.tcfDraftName("Bedroom 1", "")).toBe("Bedroom 1");      // комнаты в плане нет — имя как есть
    expect(html).toContain("name:tcfDraftName(r.name,trPlanName(r.room))");
  });
  it("галочка «размеры верны» по умолчанию", () => {
    expect(api.tcfDefaultOk({ w: 1 }, false, "not_verified")).toBe(true);   // правил агент
    expect(api.tcfDefaultOk(null, true, "area")).toBe(true);                // уже подтверждал
    expect(api.tcfDefaultOk(null, false, "verified")).toBe(true);
    expect(api.tcfDefaultOk(null, false, "listing")).toBe(true);
    expect(api.tcfDefaultOk(null, false, "not_verified")).toBe(false);
    expect(api.tcfDefaultOk(null, false, "area")).toBe(false);
  });
});

describe("страница: черновики и одна кнопка вместо пересборки на каждую правку", () => {
  it("правка комнаты и проёмов уходит черновиком, через повтор", () => {
    expect(html).toMatch(/tcfPost\('room-edit',\{[^}]*draft:true\}/);
    expect(html).toMatch(/tcfPost\('opening-edit',\{[^}]*draft:true\}/);
    expect(html).toMatch(/tcfPost\('confirm',\{k:trKey\(\), request_id:TCF\.rid, rooms_ok:ok\}\)/);
  });
  it("GET с ключом — ровно `?k=<ключ>` (песочница тура пускает только так)", () => {
    expect(html).toContain("'/api/trial/'+trJobId()+'/'+path+'?k='+trKey()");
  });
  it("тексты без длинного тире", () => {
    const ui = block + html.slice(html.indexOf("function tcfBarHtml"), html.indexOf("document.addEventListener('click',e=>{\n  const b=e.target&&e.target.closest&&e.target.closest('[data-tcf-act]')"));
    for (const m of ui.matchAll(/T\('([^']*)','([^']*)'\)/g)) { expect(m[1]).not.toContain("—"); expect(m[2]).not.toContain("—"); }
  });
});
