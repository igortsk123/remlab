// Ворота ссылки покупателя (T-20261112-40, план trial-buyer-gate-01): до «Подтвердить планировку» агента тур без ключа не отдаёт ни
// страницы, ни данных, ни снимков карточек; ключ агента (адрес / cookie для данных), Bearer воркера и задание без ключа — проходят.
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { TrialJobView } from "@/contracts/trial";
import { cookieKey, gateCheck, isSecure, keyCookie, KEY_COOKIE, readPass, type TourAccess, type TourCreds } from "@/lib/trial/buyer-gate";
import { editKeyHash } from "@/lib/trial/edit-key";
import { tourResponse } from "@/lib/trial/tour";
import { pinJobRelease, pinRelease, writeTourData } from "@/lib/trial/tour-bundle";
import { stubHtml } from "@/lib/trial/tour-stub";
import { readCardIndex, writeCards } from "@/lib/trial/tour-cards";

const ID = "BuYeRgAtE0123456789abc";
const K = "AgentKey_0123456789-ab";
const HASH = editKeyHash(K);
const NONE: TourCreds = { urlKey: null, cookieKey: null, worker: false };
const acc = (a: TourAccess | undefined) => async () => a;
const view = (async () => ({ id: ID, status: "done", resultVersion: 3, bundleVersion: 3 }) as unknown as TrialJobView) as
  (id: string) => Promise<TrialJobView>;

describe("ворота покупателя: решение", () => {
  const closed = { keyHash: HASH, confirmed: false };
  const PASS = readPass(ID, HASH);
  it("не подтверждено: без ключа — закрыто и страница, и данные", async () => {
    expect(await gateCheck({ access: acc(closed), creds: NONE }, ID, true)).toEqual({ open: false, pass: null });
    expect(await gateCheck({ access: acc(closed), creds: NONE }, ID, false)).toEqual({ open: false, pass: null });
  });
  it("ключ агента в адресе — открыто, страница выдаёт пропуск на данные; чужой / кривой ключ — закрыто", async () => {
    expect(await gateCheck({ access: acc(closed), creds: { ...NONE, urlKey: K } }, ID, true)).toEqual({ open: true, pass: PASS });
    expect(await gateCheck({ access: acc(closed), creds: { ...NONE, urlKey: K } }, ID, false)).toEqual({ open: true, pass: null });
    expect((await gateCheck({ access: acc(closed), creds: { ...NONE, urlKey: "x".repeat(22) } }, ID, true)).open).toBe(false);
  });
  it("пропуск — не ключ правки и привязан к заданию", () => {
    expect(PASS).not.toContain(K);
    expect(PASS).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(readPass("OtherJob00000000000000", HASH)).not.toBe(PASS);
  });
  it("cookie-пропуск открывает данные, но не страницу (ссылка покупателя в браузере агента — заглушка)", async () => {
    const g = { access: acc(closed), creds: { ...NONE, cookieKey: PASS } };
    expect((await gateCheck(g, ID, false)).open).toBe(true);
    expect((await gateCheck(g, ID, true)).open).toBe(false);
    expect((await gateCheck({ access: acc(closed), creds: { ...NONE, cookieKey: readPass("OtherJob00000000000000", HASH) } }, ID, false)).open)
      .toBe(false);
  });
  it("Bearer воркера (снимки карточек) — открыто", async () => {
    expect((await gateCheck({ access: acc(closed), creds: { ...NONE, worker: true } }, ID, true)).open).toBe(true);
  });
  it("подтверждено — открыто всем; пропуск больше не выдаётся", async () => {
    const ok = { keyHash: HASH, confirmed: true };
    expect(await gateCheck({ access: acc(ok), creds: NONE }, ID, true)).toEqual({ open: true, pass: null });
    expect(await gateCheck({ access: acc(ok), creds: { ...NONE, urlKey: K } }, ID, true)).toEqual({ open: true, pass: null });
  });
  it("старое задание без ключа (подтвердить некому) — открыто", async () => {
    expect((await gateCheck({ access: acc({ keyHash: null, confirmed: false }), creds: NONE }, ID, true)).open).toBe(true);
  });
});

describe("ворота покупателя: cookie", () => {
  const PASS = readPass(ID, HASH);
  it("читается только своё имя и правильная форма", () => {
    expect(cookieKey(`a=1; ${KEY_COOKIE}=${PASS}; b=2`)).toBe(PASS);
    expect(cookieKey(`${KEY_COOKIE}=<x>`)).toBeNull();
    expect(cookieKey(`${KEY_COOKIE}=${K}`)).toBeNull();          // сам ключ правки — не пропуск
    expect(cookieKey(null)).toBeNull();
    expect(cookieKey(`x${KEY_COOKIE}=${PASS}`)).toBeNull();
  });
  it("только адреса этого тура, без скриптов, Secure по https", () => {
    const c = keyCookie(ID, PASS, true);
    expect(c).toContain(`${KEY_COOKIE}=${PASS};`);
    expect(c).toContain(`Path=/try/${ID}/tour;`);
    expect(c).toContain("HttpOnly");
    expect(c).toContain("SameSite=Lax");
    expect(c).toContain("Secure");
    expect(keyCookie(ID, PASS, false)).not.toContain("Secure");
    expect(isSecure(new Request("http://x.test/a", { headers: { "x-forwarded-proto": "https" } }))).toBe(true);
    expect(isSecure(new Request("http://x.test/a"))).toBe(false);
  });
});

describe("ворота покупателя: заглушка", () => {
  it("ровно фраза владельца, без кнопок; EN — своя", () => {
    const ru = stubHtml("inactive", ID, "/x", { lang: "ru" });
    expect(ru).toContain("<h1>Ссылка не активирована, обратитесь к вашему менеджеру</h1>");
    expect(ru).toContain('data-stub="inactive"');
    expect(ru).not.toContain("<a ");
    expect(ru).not.toContain("<p>");
    expect(stubHtml("inactive", ID, "/x", { lang: "en" })).toContain("This link isn’t active yet — please contact your agent");
  });
});

// страница тура (`tools/scout/flat215-demo/index.html`): покупатель (без ключа) зова «Подтвердите планировку» не видит нигде
describe("страница тура: покупателю без «Подтвердите планировку»", () => {
  const html = readFileSync("tools/scout/flat215-demo/index.html", "utf8");
  const src = html.slice(html.indexOf("const confirmTag="), html.indexOf("// на вкладку «План квартиры»"));
  type Env = { key: string; consent: boolean; approx: boolean; ok?: boolean };
  const tag = (e: Env) => new Function("trKey", "roomConsent", "roomApprox", "trRoomConfirmed", "consentTxt", "TR_EN",
    `${src};return confirmTag('living');`)(() => e.key, () => e.consent, () => e.approx, () => !!e.ok, () => "Размеры примерные", () => false) as string;
  it("покупатель: согласие «как есть» — «Размеры примерные», форма примерная — ничего; кнопки нет", () => {
    expect(tag({ key: "", consent: true, approx: false })).toContain("Размеры примерные");
    expect(tag({ key: "", consent: true, approx: false })).not.toContain("Подтвердите");
    expect(tag({ key: "", consent: false, approx: true })).toBe("");
  });
  it("агент (ключ): как раньше — кнопка-подсказка, пока комната не подтверждена", () => {
    expect(tag({ key: "K".repeat(22), consent: false, approx: true })).toContain("Подтвердите планировку");
    expect(tag({ key: "K".repeat(22), consent: false, approx: true, ok: true })).toBe("");
  });
  it("карточка «Фото» у покупателя — без «подтвердите планировку» и без перехода к планировке", () => {
    const fn = html.slice(html.indexOf("function trPhotoStubUi(){"), html.indexOf("function vwMode(m){"));
    const buyer = /:!trKey\(\)\?`([^`]*)`/.exec(fn)?.[1] ?? "";
    expect(buyer).toContain("trPhT('ready')");
    expect(buyer).not.toContain("ask");
    expect(buyer).not.toContain("data-trph");
  });
});

describe("ворота покупателя: ответы тура", () => {
  let root: string, dir: string;
  const closed = { keyHash: HASH, confirmed: false };
  const get = (parts: string[], a: TourAccess, creds: TourCreds = NONE, lang: "ru" | "en" = "ru") =>
    tourResponse(ID, parts, { view, dir, stub: { lang }, gate: { access: acc(a), creds, secure: true } });

  beforeAll(async () => {
    root = mkdtempSync(join(tmpdir(), "gate-"));
    const demo = join(root, "demo");
    dir = join(root, "trial");
    mkdirSync(join(demo, "lib"), { recursive: true });
    writeFileSync(join(demo, "index.html"), "<html><head></head><body>TOUR-PAGE</body></html>");
    writeFileSync(join(demo, "lib", "scene.json"), JSON.stringify({ file: "scene.abc123.js" }));
    writeFileSync(join(demo, "lib", "scene.abc123.js"), "// scene");
    writeFileSync(join(demo, "rt-meshes.json"), '{"meshes":{}}');
    await pinJobRelease(ID, await pinRelease(demo, dir), dir);
    await writeTourData(ID, JSON.stringify({ trial: { id: ID }, secret: "PLAN-DATA" }), dir);
  });
  afterAll(() => rmSync(root, { recursive: true, force: true }));

  it("ссылка покупателя до подтверждения: заглушка 403 без данных тура, не хранится", async () => {
    const r = await get([], closed);
    expect(r.status).toBe(403);
    expect(r.headers.get("cache-control")).toBe("private, no-store");
    expect(r.headers.get("etag")).toBeNull();
    expect(r.headers.get("set-cookie")).toBeNull();
    const html = await r.text();
    expect(html).toContain("Ссылка не активирована, обратитесь к вашему менеджеру");
    expect(html).not.toContain("TOUR-PAGE");
    const d = await get(["demo-data.json"], closed);
    expect(d.status).toBe(403);
    expect(await d.text()).not.toContain("PLAN-DATA");
    expect((await get([], closed, NONE, "en")).status).toBe(403);
  });

  it("снимок карточки до подтверждения — 403, после — отдаётся", async () => {
    const jpg = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff]), Buffer.alloc(200, 1)]);
    expect((await writeCards(dir, ID, [{ key: "living|v1|a", jpg }])).ok).toBe(true);
    const file = Object.values(await readCardIndex(dir, ID))[0]!;
    expect((await get(["cards", file], closed)).status).toBe(403);
    expect((await get(["cards", file], { keyHash: HASH, confirmed: true })).status).toBe(200);
  });

  it("опрос версии и код витрины — без ворот (личного в них нет)", async () => {
    expect((await get(["version.json"], closed)).status).toBe(200);
    expect((await get(["lib", "scene.json"], closed)).status).toBe(200);
  });

  it("агент по ключу: страница + cookie для данных; данные по этой cookie", async () => {
    const r = await get([], closed, { ...NONE, urlKey: K });
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("TOUR-PAGE");
    expect(r.headers.get("set-cookie")).toBe(keyCookie(ID, readPass(ID, HASH), true));
    const d = await get(["demo-data.json"], closed, { ...NONE, cookieKey: readPass(ID, HASH) });
    expect(d.status).toBe(200);
    expect(await d.text()).toContain("PLAN-DATA");
  });

  it("после подтверждения та же ссылка покупателя открывает тур", async () => {
    const ok = { keyHash: HASH, confirmed: true };
    const r = await get([], ok);
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("TOUR-PAGE");
    expect((await get(["demo-data.json"], ok)).status).toBe(200);
  });

  it("заглушка не мешает 304: метка прошлой страницы до подтверждения не даёт 304", async () => {
    const tag = (await get([], { keyHash: HASH, confirmed: true })).headers.get("etag");
    const r = await tourResponse(ID, [], { view, dir, ifNoneMatch: tag, gate: { access: acc(closed), creds: NONE } });
    expect(r.status).toBe(403);
  });
});
