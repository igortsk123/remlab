import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// ЧТЕНИЕ КОЛЛЕКЦИЙ ПАЧКОЙ С ПОВТОРОМ (demo-19 А1). Функции берём прямо из страницы демо (блок COLLREAD): при открытии избранное
// читалось по запросу на коллекцию, сервер (60 чтений/мин) отказывал части, и она до перезагрузки считалась «без цены».
type Res = { status: number; json: unknown; retryAfter?: number };
type Out = { found: Record<string, { id: string }>; gone: string[]; failed: string[]; legacy: boolean };
const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
const block = html.slice(html.indexOf("// COLLREAD START"), html.indexOf("// COLLREAD END"));
const api = new Function(`${block};return {collReadAll,collChunks,COLL_BATCH,COLL_TRIES};`)() as {
  collReadAll: (ids: string[], get: (url: string) => Promise<Res>, wait: (ms: number) => Promise<void>) => Promise<Out>;
  collChunks: (ids: string[], n: number) => string[][];
  COLL_BATCH: number; COLL_TRIES: number;
};
const ids = (n: number) => Array.from({ length: n }, (_, k) => `id${String(k).padStart(20, "0")}`);
const idsOf = (url: string) => decodeURIComponent(url.split("ids=")[1] ?? "").split(",");
const ok = (url: string, skip: string[] = []): Res => ({ status: 200, json: { ok: true, collections: idsOf(url).filter((i) => !skip.includes(i)).map((id) => ({ id })) } });

// сервер-заглушка: ответы по очереди на каждый запрос пачки; паузы — записываем, не ждём
function run(n: number, answer: (url: string, call: number) => Res | Error) {
  const calls: string[] = [], waits: number[] = [];
  const get = (url: string) => { calls.push(url); const a = answer(url, calls.length); return a instanceof Error ? Promise.reject(a) : Promise.resolve(a); };
  return api.collReadAll(ids(n), get, (ms) => { waits.push(ms); return Promise.resolve(); }).then((out) => ({ out, calls, waits }));
}

describe("демо: чтение коллекций пачкой", () => {
  it("200 коллекций — 8 пачек по 25, все прочитаны", async () => {
    const { out, calls } = await run(200, (u) => ok(u));
    expect(api.COLL_BATCH).toBe(25);
    expect(calls).toHaveLength(8);
    expect(Object.keys(out.found)).toHaveLength(200);
    expect(out).toMatchObject({ gone: [], failed: [], legacy: false });
  });

  it("отказ 429 и обрыв сети — повтор с паузой 1, 2 с, затем прочитано", async () => {
    const { out, calls, waits } = await run(10, (u, c) => (c === 1 ? { status: 429, json: null } : c === 2 ? new Error("network") : ok(u)));
    expect(calls).toHaveLength(3);
    expect(waits).toEqual([1000, 2000]);
    expect(Object.keys(out.found)).toHaveLength(10);
    expect(out.failed).toEqual([]);
  });

  it("сервер просит подождать (Retry-After) — ждём столько, но не дольше 15 с", async () => {
    const a = await run(5, (u, c) => (c === 1 ? { status: 429, json: null, retryAfter: 9 } : ok(u)));
    expect(a.waits).toEqual([9000]);
    const b = await run(5, (u, c) => (c === 1 ? { status: 429, json: null, retryAfter: 60 } : ok(u)));
    expect(b.waits).toEqual([15000]);
  });

  it("все попытки неудачны — «не прочитаны» (failed), а не «нет на сервере»", async () => {
    const { out, calls, waits } = await run(30, () => ({ status: 503, json: null }));
    expect(calls).toHaveLength(2 * api.COLL_TRIES);          // две пачки × 4 попытки
    expect([...waits].sort((x, y) => x - y)).toEqual([1000, 1000, 2000, 2000, 4000, 4000]);   // пачки идут параллельно
    expect(out.failed).toHaveLength(30);
    expect(out.gone).toEqual([]);
  });

  it("сервер ответил пачкой без коллекции — её нет (gone); 404/405 — старый сервер (legacy), без повторов", async () => {
    const missing = ids(3)[1]!;
    const a = await run(3, (u) => ok(u, [missing]));
    expect(a.out.gone).toEqual([missing]);
    expect(Object.keys(a.out.found)).toHaveLength(2);
    const b = await run(3, () => ({ status: 405, json: null }));
    expect(b.out).toMatchObject({ legacy: true, failed: [], gone: [] });
    expect(b.calls).toHaveLength(1);
  });

  it("пачки нарезаются без потерь", () => {
    expect(api.collChunks(ids(51), 25).map((c) => c.length)).toEqual([25, 25, 1]);
    expect(api.collChunks([], 25)).toEqual([]);
  });
});
