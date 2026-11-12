// Чертёж агента во вкладке «План квартиры» (T-20261112-52): `/try/<id>/tour/source` (превью) и `source/file` (исходник) — только агенту
// по ключу в адресе; покупатель без ключа (и с cookie-пропуском, и после подтверждения) — 404; файл снят по сроку — 410; заголовки.
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { TrialJobView } from "@/contracts/trial";
import { agentOnly, readPass, type TourAccess, type TourCreds } from "@/lib/trial/buyer-gate";
import { editKeyHash } from "@/lib/trial/edit-key";
import type { SourceRow } from "@/lib/trial/repo-source";
import { PREVIEW_NAME_RE, previewName, previewPath, writePreview } from "@/lib/trial/storage";
import { tourResponse, tourTarget } from "@/lib/trial/tour";

const ID = "SrCpLaN0123456789abcde";
const K = "AgentKey_0123456789-ab";
const HASH = editKeyHash(K);
const NONE: TourCreds = { urlKey: null, cookieKey: null, worker: false };
const acc = (a: TourAccess | undefined) => async () => a;
const view = (async () => ({ id: ID, status: "done", resultVersion: 3, bundleVersion: 3 }) as unknown as TrialJobView) as
  (id: string) => Promise<TrialJobView>;
const WEBP = Buffer.concat([Buffer.from("RIFF\x10\x00\x00\x00WEBPVP8 ", "latin1"), Buffer.alloc(64, 7)]);
const PDF = Buffer.from("%PDF-1.4 test");

let dir = "";
beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), "t52-src-"));
  await writePreview(dir, ID, WEBP);
  writeFileSync(join(dir, `${ID}.pdf`), PDF);
});
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const row = (o: Partial<SourceRow> = {}): SourceRow => ({ preview: previewName(ID), input: `${ID}.pdf`, mime: "application/pdf", inputGone: false, ...o });
const get = (parts: string[], creds: TourCreds, a: TourAccess = { keyHash: HASH, confirmed: false }, r: SourceRow | undefined = row()) =>
  tourResponse(ID, parts, { view, dir, gate: { access: acc(a), creds }, source: async () => r });

describe("чертёж агента: адреса", () => {
  it("source и source/file — свои цели; прочее рядом — 404", () => {
    expect(tourTarget(["source"])).toEqual({ kind: "source" });
    expect(tourTarget(["source", "file"])).toEqual({ kind: "sourceFile" });
    expect(tourTarget(["source", "x"])).toBeNull();
    expect(tourTarget(["source.webp"])).toBeNull();
  });
  it("имя превью — только `<id>.src.webp` в папке пробы", () => {
    expect(PREVIEW_NAME_RE.test(previewName(ID))).toBe(true);
    expect(previewPath(dir, "../x.src.webp")).toBeNull();
    expect(previewPath(dir, `${ID}.webp`)).toBeNull();
  });
});

describe("чертёж агента: только по ключу в адресе", () => {
  it("агент с ключом — превью WEBP и исходный PDF, без кэша, nosniff, inline, песочница", async () => {
    const r = await get(["source"], { ...NONE, urlKey: K });
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("image/webp");
    expect(Buffer.from(await r.arrayBuffer()).equals(WEBP)).toBe(true);
    expect(r.headers.get("cache-control")).toBe("private, no-store");
    expect(r.headers.get("x-content-type-options")).toBe("nosniff");
    expect(r.headers.get("content-security-policy")).toContain("sandbox");
    const f = await get(["source", "file"], { ...NONE, urlKey: K });
    expect(f.status).toBe(200);
    expect(f.headers.get("content-type")).toBe("application/pdf");
    expect(f.headers.get("content-disposition")).toBe("inline");
    expect(f.headers.get("content-security-policy")).toBe("sandbox");
    expect(Buffer.from(await f.arrayBuffer()).equals(PDF)).toBe(true);
  });
  it("покупатель: без ключа, с cookie-пропуском, после подтверждения, Bearer воркера, чужой ключ — 404 (как будто файла нет)", async () => {
    const ok = { keyHash: HASH, confirmed: true };
    for (const parts of [["source"], ["source", "file"]]) {
      expect((await get(parts, NONE)).status).toBe(404);
      expect((await get(parts, { ...NONE, cookieKey: readPass(ID, HASH) })).status).toBe(404);
      expect((await get(parts, NONE, ok)).status).toBe(404);
      expect((await get(parts, { ...NONE, worker: true }, ok)).status).toBe(404);
      expect((await get(parts, { ...NONE, urlKey: "x".repeat(22) }, ok)).status).toBe(404);
    }
  });
  it("задание без ключа агента (старое) — никому", async () => {
    expect(await agentOnly({ access: acc({ keyHash: null, confirmed: false }), creds: { ...NONE, urlKey: K } }, ID)).toBe(false);
    expect(await agentOnly(undefined, ID)).toBe(false);
  });
  it("без строки файлов (маршрут не передал) — 404", async () => {
    const r = await tourResponse(ID, ["source"], { view, dir, gate: { access: acc({ keyHash: HASH, confirmed: false }), creds: { ...NONE, urlKey: K } } });
    expect(r.status).toBe(404);
  });
});

describe("чертёж агента: сроки", () => {
  const A = { ...NONE, urlKey: K };
  it("исходник снят по сроку — 410; превью ещё живо — 200", async () => {
    expect((await get(["source", "file"], A, undefined, row({ input: null, inputGone: true }))).status).toBe(410);
    expect((await get(["source"], A, undefined, row({ input: null, inputGone: true }))).status).toBe(200);
  });
  it("файла на диске нет — 410; превью не сделано — 404; тур снят — 410 до любых проверок", async () => {
    expect((await get(["source", "file"], A, undefined, row({ input: `${"Z".repeat(22)}.pdf` }))).status).toBe(410);
    expect((await get(["source"], A, undefined, row({ preview: null }))).status).toBe(404);
    const gone = await tourResponse(ID, ["source"], { view: async () => "expired", dir, gate: { access: acc({ keyHash: HASH, confirmed: false }), creds: A },
      source: async () => row() });
    expect(gone.status).toBe(410);
  });
});
