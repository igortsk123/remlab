import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { TrialJobView } from "@/contracts/trial";
import { bundleProblem, trialBundle } from "@/contracts/trial-bundle";
import { ensureJobRelease, pinJobRelease, pinRelease, writeTourData } from "@/lib/trial/tour-bundle";
import { jobDir, releaseDir } from "@/lib/trial/tour-files";
import { devCardPaths, injectTour, tourLinks } from "@/lib/trial/tour-page";
import { tourResponse, tourTarget } from "@/lib/trial/tour";
import { acceptsBrotli, BROTLI_CACHE_MAX_BYTES, brotliCacheReset, brotliCacheStats, brotliPage } from "@/lib/trial/tour-brotli";
import { tagMatches } from "@/lib/trial/tour-cache";
import { randomBytes } from "node:crypto";
import { brotliDecompressSync } from "node:zlib";

const ID = "AbCdEfGhIjKlMnOpQrStUv";
const OTHER = "ZZZZZZZZZZZZZZZZZZZZZZ";
const view = (async () => ({ id: ID, status: "done", resultVersion: 7 }) as unknown as TrialJobView) as (id: string) => Promise<TrialJobView>;

describe("тур пробы: список разрешённых адресов", () => {
  it("страница, данные, общие файлы витрины", () => {
    expect(tourTarget([])).toEqual({ kind: "page" });
    expect(tourTarget(["demo-data.json"])).toEqual({ kind: "data" });
    expect(tourTarget(["lib", "scene.json"])).toMatchObject({ kind: "release", rel: "lib/scene.json" });
    expect(tourTarget(["lib", "scene.50b388b725c6.js"])).toMatchObject({ kind: "release" });
    expect(tourTarget(["lib", "basket.c8af646371ed.js"])).toMatchObject({ kind: "release" });
    expect(tourTarget(["rt-meshes.json"])).toMatchObject({ kind: "release" });
    expect(tourTarget(["version.json"])).toEqual({ kind: "version" });
  });

  it("картинки витрины — ссылкой на общую папку", () => {
    expect(tourTarget(["img", "af0e178adc985d1e.jpg"])).toEqual({ kind: "shared", url: "/demo/img/af0e178adc985d1e.jpg" });
    expect(tourTarget(["topsprites", "99272_44.front.png"])).toEqual({ kind: "shared", url: "/demo/topsprites/99272_44.front.png" });
  });

  it("всё остальное — отказ: обход пути, чужие имена и расширения", () => {
    for (const p of [["..", "secret"], ["lib", "..", "index.html"], ["index.html"], ["release"], ["lib", "scene.js"],
      ["img", "x.html"], ["img", "sub", "x.jpg"], ["input.png"], ["%2e%2e"], ["lib", "scene.zz.js"], ["demo-data.json", "x"]]) {
      expect(tourTarget(p), p.join("/")).toBeNull();
    }
  });
});

describe("тур пробы: вставка песочницы", () => {
  const html = '<html><head><meta charset="utf-8"><script>window.first=1</script></head></html>';
  it("первым в <head>, ключи хранилища — по заданию", () => {
    const out = injectTour(html, ID);
    expect(out.indexOf(`trial:${ID}:`)).toBeLessThan(out.indexOf("window.first"));
    expect(out).toContain("Storage.prototype");
  });
  it("сеть: запрещены все ручки /api и реестр кадров", () => {
    const m = injectTour(html, ID).match(/var BLOCK=(\/.+\/);/);
    const re = new RegExp(String(m?.[1]).slice(1, -1));
    for (const p of ["/api/render", "/api/render/frame", "/api/job", "/api/share", "/api/warm", "/api/draft/paid", "/api/events", "/api/collections/x", "/api/sends/x", "/api/apartments/x", "/test/share/shots.json"]) {
      expect(re.test(p), p).toBe(true);
    }
    for (const p of ["/demo/img/a.jpg", "/try/x/tour/demo-data.json", "/rt/x.glb"]) expect(re.test(p), p).toBe(false);
  });
  it("две ссылки задания: агент без опроса, покупатель с опросом", () => {
    expect(tourLinks(ID)).toEqual({ agent: `/try/${ID}/tour?quiz=0`, buyer: `/try/${ID}/tour?quiz=1` });
  });
  it("ключ правки — только в ссылке агента; кривой ключ не переносится", () => {
    const k = "K".repeat(22);
    expect(tourLinks(ID, k)).toEqual({ agent: `/try/${ID}/tour?quiz=0&k=${k}`, buyer: `/try/${ID}/tour?quiz=1` });
    expect(tourLinks(ID, "<x>").agent).toBe(`/try/${ID}/tour?quiz=0`);
  });
  it("песочница пропускает «Обустроить», «размеры словами» и фото этого задания, кадры и опрос задания — только через fetch", async () => {
    const boot = injectTour(html, ID).match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? "";
    const seen: string[] = [];
    const store = new Map<string, string>();
    class FakeStorage { getItem(k: string) { return store.get(k) ?? null; } setItem(k: string, v: string) { store.set(k, v); }
      removeItem(k: string) { store.delete(k); } key() { return null; } get length() { return 0; } }
    const win: Record<string, unknown> = { fetch: async (u: string) => { seen.push(String(u)); return new Response("{}"); } };
    const nav = { sendBeacon: (u: string) => { seen.push(`beacon:${u}`); return true; } };
    const loc = { origin: "https://x.test", pathname: `/try/${ID}/tour/`, search: "", hash: "" };
    new Function("window", "Storage", "history", "location", "navigator", "document", "URL", "Response", boot)(
      win, FakeStorage, { replaceState: () => undefined, state: null }, loc, nav, { baseURI: "https://x.test/try/" }, URL, Response);
    const f = win.fetch as (u: string) => Promise<Response>;
    expect((await f(`/api/trial/${ID}/rebuild`)).status).toBe(200);
    expect((await f(`/api/trial/${OTHER}/rebuild`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}/rebuild?x=1`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}/listing`)).status).toBe(200);
    expect((await f(`/api/trial/${OTHER}/listing`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}/listing?x=1`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}/listing/x`)).status).toBe(403);
    // фото (T-20261109-34): заказ — своей ручкой этого задания, кадры — общей загрузкой, ход — опросом номера задания
    expect((await f(`/api/trial/${ID}/photo`)).status).toBe(200);
    expect((await f(`/api/trial/${OTHER}/photo`)).status).toBe(403);
    expect((await f(`/api/trial/${ID}/photo?x=1`)).status).toBe(403);
    expect((await f("/api/render/frame")).status).toBe(200);
    expect((await f("/api/job?id=abc123")).status).toBe(200);
    for (const p of ["/api/render", "/api/render?async=1", "/api/render/frame?x=1", "/api/job", "/api/job?id=a&x=1", "/api/jobs?id=a",
      "/api/job/x?id=a", "/api/share", "/api/draft/paid", "/api/events"]) expect((await f(p)).status, p).toBe(403);
    // отделка застройщика (T-20261110-37 Г): только карточка квартиры витрины /demo и её британского двойника, только язык + demo=1
    expect(devCardPaths()).toEqual(["/api/apartments/demo-uk-215", "/api/apartments/flat215"]);
    expect((await f("/api/apartments/flat215?lang=ru&demo=1")).status).toBe(200);
    expect((await f("/api/apartments/demo-uk-215?lang=en&demo=1")).status).toBe(200);
    for (const p of ["/api/apartments/flat215", "/api/apartments/flat215?lang=ru", "/api/apartments/flat215?lang=de&demo=1",
      "/api/apartments/flat215?lang=ru&demo=1&x=1", "/api/apartments/demo-uk-1?lang=en&demo=1", "/api/apartments/flat215/x?lang=ru&demo=1"])
      expect((await f(p)).status, p).toBe(403);
    // «Подтвердить планировку» (T-20261111-16): кнопка — без параметров; черновики и ход — GET только с `?k=<22 знака>`
    const K = "K".repeat(22);
    expect((await f(`/api/trial/${ID}/confirm`)).status).toBe(200);
    expect((await f(`/api/trial/${ID}/edits?k=${K}`)).status).toBe(200);
    expect((await f(`/api/trial/${ID}/rebuild-status?k=${K}`)).status).toBe(200);
    for (const p of [`/api/trial/${OTHER}/confirm`, `/api/trial/${ID}/confirm?x=1`, `/api/trial/${ID}/edits`, `/api/trial/${ID}/rebuild-status`,
      `/api/trial/${ID}/edits?k=short`, `/api/trial/${ID}/edits?k=${K}&x=1`, `/api/trial/${OTHER}/edits?k=${K}`,
      `/api/trial/${ID}/rebuild-status?k=${K}x`, `/api/trial/${ID}/confirm?k=${K}`]) expect((await f(p)).status, p).toBe(403);
    (nav.sendBeacon as (u: string) => boolean)(`/api/trial/${ID}/rebuild`);
    (nav.sendBeacon as (u: string) => boolean)("/api/render/frame");
    (nav.sendBeacon as (u: string) => boolean)(`/api/trial/${ID}/listing`);
    expect(seen).toEqual([`/api/trial/${ID}/rebuild`, `/api/trial/${ID}/listing`, `/api/trial/${ID}/photo`, "/api/render/frame",
      "/api/job?id=abc123", "/api/apartments/flat215?lang=ru&demo=1", "/api/apartments/demo-uk-215?lang=en&demo=1",
      `/api/trial/${ID}/confirm`, `/api/trial/${ID}/edits?k=${"K".repeat(22)}`, `/api/trial/${ID}/rebuild-status?k=${"K".repeat(22)}`]);
  });
  it("мусор в id — отказ", () => {
    expect(() => injectTour(html, "<script>")).toThrow();
    expect(() => injectTour("<p>no head</p>", ID)).toThrow();
  });
});

describe("тур пробы: ответы и закреплённая версия", () => {
  let root: string, demo: string, dir: string, release: string;
  const get = (parts: string[], id = ID) => tourResponse(id, parts, { view, dir });

  beforeAll(async () => {
    root = mkdtempSync(join(tmpdir(), "tour-"));
    demo = join(root, "demo");
    dir = join(root, "trial");
    mkdirSync(join(demo, "lib"), { recursive: true });
    writeFileSync(join(demo, "index.html"), "<html><head></head><body>v1</body></html>");
    writeFileSync(join(demo, "lib", "scene.json"), JSON.stringify({ file: "scene.abc123.js", basket: { file: "basket.def456.js" } }));
    writeFileSync(join(demo, "lib", "scene.abc123.js"), "// scene v1");
    writeFileSync(join(demo, "lib", "basket.def456.js"), "// basket v1");
    writeFileSync(join(demo, "rt-meshes.json"), '{"meshes":{}}');
    release = await pinRelease(demo, dir);
    await pinJobRelease(ID, release, dir);
    await writeTourData(ID, JSON.stringify({ trial: { id: ID }, variants: [] }), dir);
  });
  afterAll(() => rmSync(root, { recursive: true, force: true }));

  it("страница: закреплённая версия + песочница, заголовки пробы", async () => {
    const r = await get([]);
    expect(r.status).toBe(200);
    expect(r.headers.get("cache-control")).toBe("private, no-cache");
    expect(r.headers.get("x-robots-tag")).toContain("noindex");
    expect(r.headers.get("referrer-policy")).toBe("no-referrer");
    const body = await r.text();
    expect(body).toContain("v1");
    expect(body).toContain(`trial:${ID}:`);
    expect(body).toContain("window.__TOUR_VER=7;");
  });

  it("опрос версии: номер результата без кэша, нужен только сам номер", async () => {
    const r = await get(["version.json"]);
    expect(r.status).toBe(200);
    expect(r.headers.get("cache-control")).toBe("private, no-store");
    expect(await r.json()).toMatchObject({ version: 7 });
    expect((await tourResponse(ID, ["version.json"], { view: async () => "expired", dir })).status).toBe(410);
  });

  it("данные и закрепление — в папке задания, отдельной папки тура на задание нет", () => {
    expect(readFileSync(join(dir, ID, "release"), "utf8").trim()).toBe(release);
    expect(existsSync(join(dir, ID, "demo-data.json"))).toBe(true);
    expect(existsSync(join(dir, "tour", ID))).toBe(false);
  });

  it("новая выкладка витрины не меняет страницу задания", async () => {
    writeFileSync(join(demo, "index.html"), "<html><head></head><body>v2</body></html>");
    const fresh = await pinRelease(demo, dir);
    expect(fresh).not.toBe(release);
    expect(await (await get([])).text()).toContain("v1");
    writeFileSync(join(demo, "index.html"), "<html><head></head><body>v1</body></html>");
  });

  it("одно содержимое — одна копия", async () => {
    expect(await pinRelease(demo, dir)).toBe(release);
  });

  it("данные — из папки задания, общие файлы — из закреплённой копии", async () => {
    const d = await get(["demo-data.json"]);
    expect(d.headers.get("content-type")).toContain("application/json");
    expect(d.headers.get("cache-control")).toBe("private, no-store");
    expect((await d.json()).trial.id).toBe(ID);
    const s = await get(["lib", "scene.abc123.js"]);
    expect(s.headers.get("content-type")).toContain("javascript");
    expect(await s.text()).toBe("// scene v1");
    expect((await get(["rt-meshes.json"])).status).toBe(200);
  });

  it("картинка витрины — переход на /demo/ без кэша ответа", async () => {
    const r = await get(["img", "a1.jpg"]);
    expect(r.status).toBe(302);
    expect(r.headers.get("location")).toBe("/demo/img/a1.jpg");
    expect(r.headers.get("cache-control")).toBe("private, no-store");
  });

  it("картинка витрины — переход без запроса к базе (T-20261111-23)", async () => {
    let asked = 0;
    const r = await tourResponse(ID, ["img", "a1.jpg"], { view: async () => { asked++; return undefined; }, dir });
    expect(r.status).toBe(302);
    expect(asked).toBe(0);
  });

  it("таблица лёгких копий: закреплённые записи как есть, новые модели — из текущей витрины (T-20261111-23)", async () => {
    const rd = releaseDir(dir, release);
    const pinned = readFileSync(join(rd, "rt-meshes.json"));
    const demo2 = join(root, "demo-now");
    mkdirSync(demo2, { recursive: true });
    try {
      writeFileSync(join(rd, "rt-meshes.json"), JSON.stringify({ baseUrl: "/rt/", meshes: { a: { size: 1, src_sha: "old" } } }));
      writeFileSync(join(demo2, "rt-meshes.json"), JSON.stringify({ meshes: { a: { size: 2, src_sha: "new" }, b: { size: 3 } } }));
      const r = await tourResponse(ID, ["rt-meshes.json"], { view, dir, demoDir: demo2 });
      expect(await r.json()).toEqual({ baseUrl: "/rt/", meshes: { a: { size: 1, src_sha: "old" }, b: { size: 3 } } });
      writeFileSync(join(demo2, "rt-meshes.json"), "{битый");
      const same = await tourResponse(ID, ["rt-meshes.json"], { view, dir, demoDir: demo2 });
      expect((await same.json()).meshes).toEqual({ a: { size: 1, src_sha: "old" } });
      const none = await tourResponse(ID, ["rt-meshes.json"], { view, dir, demoDir: join(root, "нет") });
      expect((await none.json()).meshes).toEqual({ a: { size: 1, src_sha: "old" } });
    } finally {
      writeFileSync(join(rd, "rt-meshes.json"), pinned);
    }
  });

  it("нет задания / кривой id / срок вышел / нет бандла", async () => {
    expect((await tourResponse(ID, [], { view: async () => undefined, dir })).status).toBe(404);
    expect((await tourResponse("../../etc", [], { view, dir })).status).toBe(404);
    expect((await tourResponse(ID, [], { view: async () => "expired", dir })).status).toBe(410);
    expect((await get([], OTHER)).status).toBe(404);
  });

  it("запрещённые пути не читают файлы и не спрашивают базу", async () => {
    let asked = 0;
    const r = await tourResponse(ID, ["..", "release"], { view: async () => { asked++; return undefined; }, dir });
    expect(r.status).toBe(404);
    expect(asked).toBe(0);
  });

  it("симлинк вместо данных не читается", async () => {
    const jd = jobDir(dir, OTHER);
    mkdirSync(jd, { recursive: true });
    writeFileSync(join(jd, "release"), `${release}\n`);
    symlinkSync(join(demo, "index.html"), join(jd, "demo-data.json"));
    expect((await tourResponse(OTHER, ["demo-data.json"], { view, dir })).status).toBe(404);
  });

  it("битая запись версии — как нет бандла", async () => {
    const jd = jobDir(dir, "bad0000000000000000000");
    mkdirSync(jd, { recursive: true });
    writeFileSync(join(jd, "release"), "../../etc\n");
    expect((await tourResponse("bad0000000000000000000", [], { view, dir })).status).toBe(404);
  });

  it("данные — последняя версия по манифесту (ETag = база «Обустроить»), без версий — запасной demo-data.json", async () => {
    const r = await tourResponse(ID, ["demo-data.json"], { view, dir, latest: async () => ({ version: 3, json: '{"rev":3}' }) });
    expect(r.headers.get("etag")).toBe('"v3"');
    expect(await r.json()).toEqual({ rev: 3 });
    const old = await tourResponse(ID, ["demo-data.json"], { view, dir, latest: async () => "not_ready" });
    expect(old.headers.get("etag")).toBe('"v0"');
    expect((await old.json()).trial.id).toBe(ID);
  });

  // T-20261110-43: повторное открытие без повторной загрузки — хранить со сверкой (304 без тела); с ключом агента — не хранить
  it("кэш: страница без ключа — метка по телу и 304; с ключом `k` — не хранится; новая версия тура — новая метка", async () => {
    const r = await get([]);
    const tag = r.headers.get("etag") ?? "";
    expect(tag).toMatch(/^"h[\w-]{22}"$/);
    const again = await tourResponse(ID, [], { view, dir, ifNoneMatch: tag });
    expect(again.status).toBe(304);
    expect(await again.text()).toBe("");
    expect(again.headers.get("etag")).toBe(tag);
    expect(again.headers.get("cache-control")).toBe("private, no-cache");
    expect((await tourResponse(ID, [], { view, dir, ifNoneMatch: `"x", W/${tag}` })).status).toBe(304);
    expect((await tourResponse(ID, [], { view, dir, ifNoneMatch: '"x"' })).status).toBe(200);
    const keyed = await tourResponse(ID, [], { view, dir, keyed: true, ifNoneMatch: tag });
    expect(keyed.status).toBe(200);
    expect(keyed.headers.get("cache-control")).toBe("private, no-store");
    expect(keyed.headers.get("etag")).toBeNull();
    const v8 = (async () => ({ id: ID, status: "done", resultVersion: 8 }) as unknown as TrialJobView) as (id: string) => Promise<TrialJobView>;
    const next = await tourResponse(ID, [], { view: v8, dir, ifNoneMatch: tag });
    expect(next.status).toBe(200);
    expect(next.headers.get("etag")).not.toBe(tag);
  });

  it("кэш: данные версии — метка v<N> и 304; запасной файл без версии не хранится; движок — навсегда, scene.json — со сверкой", async () => {
    const latest = async () => ({ version: 3, json: '{"rev":3}' });
    const d = await tourResponse(ID, ["demo-data.json"], { view, dir, latest });
    expect(d.headers.get("cache-control")).toBe("private, no-cache");
    const same = await tourResponse(ID, ["demo-data.json"], { view, dir, latest, ifNoneMatch: '"v3"' });
    expect(same.status).toBe(304);
    expect(await same.text()).toBe("");
    expect((await tourResponse(ID, ["demo-data.json"], { view, dir, latest, ifNoneMatch: '"v2"' })).status).toBe(200);
    const old = await tourResponse(ID, ["demo-data.json"], { view, dir, ifNoneMatch: '"v0"' });
    expect(old.status).toBe(200);
    expect(old.headers.get("cache-control")).toBe("private, no-store");
    expect((await get(["lib", "scene.abc123.js"])).headers.get("cache-control")).toBe("private, max-age=31536000, immutable");
    const man = await get(["lib", "scene.json"]);
    expect(man.headers.get("cache-control")).toBe("private, no-cache");
    expect((await tourResponse(ID, ["lib", "scene.json"], { view, dir, ifNoneMatch: man.headers.get("etag") })).status).toBe(304);
    expect((await get(["version.json"])).headers.get("cache-control")).toBe("private, no-store");
  });

  it("brotli: страница сжата, если клиент просит, метка «-br» и 304 по ней; без br — как было; с ключом — сжата, но не хранится", async () => {
    brotliCacheReset();
    const plain = await get([]);
    const body = await plain.text();
    const br = await tourResponse(ID, [], { view, dir, acceptEncoding: "gzip, deflate, br, zstd" });
    expect(br.headers.get("content-encoding")).toBe("br");
    expect(br.headers.get("vary")).toContain("Accept-Encoding");
    expect(br.headers.get("etag")).toBe(`${(plain.headers.get("etag") ?? "").slice(0, -1)}-br"`);
    expect(brotliDecompressSync(Buffer.from(await br.arrayBuffer())).toString("utf8")).toBe(body);
    expect((await tourResponse(ID, [], { view, dir, acceptEncoding: "br", ifNoneMatch: br.headers.get("etag") })).status).toBe(304);
    expect((await tourResponse(ID, [], { view, dir, acceptEncoding: "gzip, br;q=0" })).headers.get("content-encoding")).toBeNull();
    const keyed = await tourResponse(ID, [], { view, dir, keyed: true, acceptEncoding: "br" });
    expect(keyed.headers.get("content-encoding")).toBe("br");
    expect(keyed.headers.get("cache-control")).toBe("private, no-store");
    expect(keyed.headers.get("etag")).toBeNull();
  });

  it("закрепление страницы при первой версии: гонка трёх публикаций — один release; повтор — exists; нет витрины — ошибка", async () => {
    const J = "PinPinPinPinPinPinPinA";
    const got = await Promise.all([1, 2, 3].map(() => ensureJobRelease(J, dir, demo)));
    expect(got.filter((x) => x === "pinned")).toHaveLength(1);
    expect(readFileSync(join(dir, J, "release"), "utf8").trim()).toBe(release);
    expect(await ensureJobRelease(J, dir, demo)).toBe("exists");
    expect((await tourResponse(J, [], { view, dir })).status).toBe(200);
    await expect(ensureJobRelease("PinPinPinPinPinPinPinB", dir, join(root, "no-demo"))).rejects.toThrow();
    expect(existsSync(join(dir, "PinPinPinPinPinPinPinB", "release"))).toBe(false);
  });

  // T-20261110-07: тур не открывается — человеку страница на его языке со ссылкой на задание, машинным адресам — текст как раньше
  const as = (over: Partial<TrialJobView>) => (async () => ({ id: ID, status: "done", resultVersion: 1, bundleVersion: 0, ...over }) as TrialJobView);
  const K = "k".repeat(22);

  it("нет закрепления: задание идёт — «готовится» (обновить + ход работы), машинные адреса — текст", async () => {
    const J = "WaitWaitWaitWaitWaitWa";
    const r = await tourResponse(J, [], { view: as({ status: "running" }), dir, stub: { lang: "ru", k: K } });
    expect(r.status).toBe(404);
    expect(r.headers.get("content-type")).toContain("text/html");
    expect(r.headers.get("x-robots-tag")).toContain("noindex");
    const html = await r.text();
    expect(html).toContain('data-stub="wait"');
    expect(html).toContain("Тур ещё готовится");
    expect(html).not.toContain("not ready");
    expect(html).toContain(`href="/try/${J}/tour?lang=ru&amp;k=${K}"`);
    expect(html).toContain(`href="/try/${J}?k=${K}&amp;lang=ru"`);
    const d = await tourResponse(J, ["demo-data.json"], { view: as({ status: "running" }), dir, stub: { lang: "ru" } });
    expect(d.status).toBe(404);
    expect(await d.text()).toBe("not ready");
  });

  it("задание закрыто без версии данных — «не получилось собрать тур» со ссылкой на загрузку и на задание; кривой ключ не переносится", async () => {
    const J = "FailFailFailFailFailFa";
    const html = await (await tourResponse(J, [], { view: as({}), dir, stub: { lang: "en", k: "<x>" } })).text();
    expect(html).toContain('data-stub="failed"');
    expect(html).toContain("We couldn&#39;t build this tour");
    expect(html).toContain('href="/try?lang=en"');
    expect(html).toContain(`href="/try/${J}?lang=en"`);
    expect(html).not.toContain("&lt;x&gt;");
  });

  it("нет задания / срок вышел / кривой id — страница «не найден» / «срок истёк» с кодом 404 / 410", async () => {
    const miss = await tourResponse(ID, [], { view: async () => undefined, dir, stub: { lang: "ru" } });
    expect(miss.status).toBe(404);
    expect(await miss.text()).toContain("Тур не найден");
    const exp = await tourResponse(ID, [], { view: async () => "expired", dir, stub: { lang: "en" } });
    expect(exp.status).toBe(410);
    expect(await exp.text()).toContain("This tour has expired");
    expect(await (await tourResponse("../../etc", [], { view, dir })).text()).toContain('data-stub="missing"');
    expect(await (await tourResponse(ID, ["version.json"], { view: async () => "expired", dir })).text()).toBe("expired");
  });

  it("версия данных есть, а закрепления нет — закрепляем при открытии; закрепить не вышло — «готовится», без петли", async () => {
    const J = "LazyLazyLazyLazyLazyLa";
    let calls = 0;
    const pin = async (id: string, d: string) => { calls++; return ensureJobRelease(id, d, demo); };
    const r = await tourResponse(J, [], { view: as({ bundleVersion: 2, resultVersion: 2 }), dir, pin });
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("v1");
    expect(readFileSync(join(dir, J, "release"), "utf8").trim()).toBe(release);
    expect((await tourResponse(J, [], { view: as({ bundleVersion: 2 }), dir, pin })).status).toBe(200);
    expect(calls).toBe(1);                                          // второй раз закрепление уже есть
    const B = "BrokBrokBrokBrokBrokBr";
    const bad = await tourResponse(B, [], { view: as({ bundleVersion: 1 }), dir, pin: async () => { throw new Error("no demo"); } });
    expect(bad.status).toBe(404);
    expect(await bad.text()).toContain('data-stub="wait"');
    const none = await tourResponse(B, [], { view: as({ bundleVersion: 0, status: "running" }), dir, pin: async () => { throw new Error("must not pin"); } });
    expect(await none.text()).toContain('data-stub="wait"');      // версии данных нет — закреплять нечего
  });

  it("копия версии целая: index, сцена, корзина, модели", () => {
    const rd = releaseDir(dir, release);
    for (const f of ["index.html", "lib/scene.json", "lib/scene.abc123.js", "lib/basket.def456.js", "rt-meshes.json"]) {
      expect(readFileSync(join(rd, f)).length, f).toBeGreaterThan(0);
    }
  });
});

describe("фикстуры тура пробы", () => {
  const read = (f: string) => JSON.parse(readFileSync(join(process.cwd(), "tests", "fixtures", f), "utf8")) as Record<string, unknown> & {
    trial: { id: string }; rooms_geo: Record<string, { w: number; d: number }>;
    variants: Array<{ id: string; room_id: string; style: string; items: unknown[]; pending?: boolean }>;
  };
  it("пустая: варианты валидны и помечены «подбирается»", () => {
    const d = read("trial-tour-empty.json");
    expect(d.trial).toBeTruthy();
    expect(d.apartment_id).toBeUndefined();
    expect(d.variants.length).toBeGreaterThan(0);
    for (const v of d.variants) {
      expect(v.id).toBeTruthy();
      expect(v.style).toBeTruthy();
      expect(v.items).toEqual([]);
      expect(v.pending).toBe(true);
      expect(d.rooms_geo[v.room_id]?.w ?? 0).toBeGreaterThan(0);
      expect(d.rooms_geo[v.room_id]?.d ?? 0).toBeGreaterThan(0);
    }
  });
  it("приближённая комната помечена в данных", () => {
    for (const f of ["trial-tour-empty.json", "trial-tour-furnished.json"]) {
      expect(Object.values(read(f).rooms_geo).some((r) => (r as { approx?: boolean }).approx), f).toBe(true);
    }
  });
  it("с мебелью: в вариантах есть предметы, пометки «подбирается» нет", () => {
    const d = read("trial-tour-furnished.json");
    expect(d.trial).toBeTruthy();
    expect(d.apartment_id).toBeUndefined();
    expect(d.variants.some((v) => v.items.length > 0)).toBe(true);
    expect(d.variants.every((v) => !v.pending)).toBe(true);
  });
  // контракт сборщика данных (`contracts/trial-bundle.ts`): страница читает исходы и подписи из тех же полей, что пишет сборщик
  it("обе фикстуры проходят контракт сборщика: форма и связи", () => {
    for (const f of ["trial-tour-empty.json", "trial-tour-furnished.json"]) {
      const b = trialBundle.parse(read(f));
      expect(bundleProblem(b, b.trial.job_id), f).toBeNull();
    }
  });
  it("исходы мебели по комнате — кодами: подбирается / обставлена / нет товаров / не разобрана / не обставляется", () => {
    type Room = { id: string; kind: string; titleRu: string; titleEn: string; furniture_state: string; furniture_outcome: string;
      furniture_text_en?: string | null };
    const OUTCOMES = ["pending", "furnished", "no_products", "not_readable", "not_furnished"];
    const rooms = (f: string) => (read(f) as unknown as { apartment_rooms: Room[] }).apartment_rooms;
    for (const f of ["trial-tour-empty.json", "trial-tour-furnished.json"]) {
      for (const r of rooms(f)) {
        expect(OUTCOMES, `${f} ${r.id}`).toContain(r.furniture_outcome);
        expect(r.titleRu && r.titleEn, `${f} ${r.id}: подписи на двух языках`).toBeTruthy();
        if (r.furniture_state === "refused" || r.furniture_state === "not_furnished") expect(r.furniture_text_en, `${f} ${r.id}`).toBeTruthy();
      }
    }
    expect(rooms("trial-tour-empty.json").some((r) => r.furniture_outcome === "pending")).toBe(true);
    const furn = rooms("trial-tour-furnished.json");
    expect(furn.filter((r) => r.furniture_outcome === "no_products").map((r) => r.id)).toEqual(["bedroom-1"]);
    expect(furn.filter((r) => r.furniture_outcome === "not_readable").map((r) => r.id)).toEqual(["hall"]);
    expect(furn.some((r) => r.furniture_outcome === "furnished")).toBe(true);
    expect(furn.filter((r) => r.furniture_outcome === "not_furnished").every((r) => !["living", "bedroom"].includes(r.kind))).toBe(true);
    for (const v of read("trial-tour-furnished.json").variants.filter((x) => x.room_id === "bedroom-1")) expect(v.items).toEqual([]);
  });
  it("подписи геометрии на двух языках, правило опроса — в данных (ссылка покупателя `?quiz=1`)", () => {
    for (const f of ["trial-tour-empty.json", "trial-tour-furnished.json"]) {
      const d = read(f) as unknown as { rooms_geo: Record<string, { title_ru?: string; title_en?: string }>; quiz?: { questions?: unknown[] } };
      for (const [k, g] of Object.entries(d.rooms_geo)) expect(g.title_ru && g.title_en && !/[Ѐ-ԯ]/.test(g.title_en), `${f} ${k}`).toBeTruthy();
      expect(d.quiz?.questions?.length ?? 0, f).toBeGreaterThan(0);
    }
  });
  it("масштаб задания в данных: не подтверждён — на пустой", () => {
    const scale = (f: string) => (read(f).trial as { scale?: string }).scale;
    expect(scale("trial-tour-empty.json")).toBe("not_verified");
    expect(scale("trial-tour-furnished.json")).toBe("verified");
  });
});

describe("тур пробы: brotli и метки (T-20261110-43)", () => {
  it("Accept-Encoding: br, br;q=0.5 — да; br;q=0, нет br — нет", () => {
    expect(acceptsBrotli("gzip, deflate, br, zstd")).toBe(true);
    expect(acceptsBrotli("br;q=0.5")).toBe(true);
    expect(acceptsBrotli("gzip, br;q=0")).toBe(false);
    expect(acceptsBrotli("gzip")).toBe(false);
    expect(acceptsBrotli(null)).toBe(false);
  });
  it("сверка меток: список, W/, суффикс сжатия, *", () => {
    expect(tagMatches('"a", W/"hX"', '"hX"')).toBe(true);
    expect(tagMatches('"hX-br"', '"hX"')).toBe(true);
    expect(tagMatches('"v9-gzip"', '"v9"')).toBe(true);
    expect(tagMatches("*", '"v9"')).toBe(true);
    expect(tagMatches('"v91"', '"v9"')).toBe(false);
    expect(tagMatches(null, '"v9"')).toBe(false);
  });
  it("память сжатых страниц — не больше предела: старые записи вытесняются", async () => {
    brotliCacheReset();
    // случайные байты в base64 сжимаются до ~75 %: 12 записей по 4 МБ ≈ 36 МБ сжатого > 32 МБ
    for (let i = 0; i < 12; i++) await brotliPage(`"t${i}"`, randomBytes(3 * 1024 * 1024).toString("base64"));
    const st = brotliCacheStats();
    expect(st.bytes).toBeLessThanOrEqual(BROTLI_CACHE_MAX_BYTES);
    expect(st.entries).toBeLessThan(12);
    expect(st.entries).toBeGreaterThan(5);
    brotliCacheReset();
  });
});
